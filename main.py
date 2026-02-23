#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from pybit.unified_trading import HTTP
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

DEFAULT_TICKERS = ["BTC", "ETH", "PEPE"]
DEFAULT_FREQUENCY_MINUTES = 30

TICKER_RE = re.compile(r"^[A-Z0-9]{2,10}$")


@dataclass
class AppConfig:
    tickers: list[str]
    frequency_minutes: int


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        cfg = AppConfig(tickers=DEFAULT_TICKERS[:], frequency_minutes=DEFAULT_FREQUENCY_MINUTES)
        save_config(cfg)
        return cfg
    data = json.loads(CONFIG_PATH.read_text())
    tickers = [str(t).upper() for t in data.get("tickers", DEFAULT_TICKERS)]
    freq = int(data.get("frequency_minutes", DEFAULT_FREQUENCY_MINUTES))
    return AppConfig(tickers=tickers, frequency_minutes=freq)


def save_config(cfg: AppConfig) -> None:
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"tickers": cfg.tickers, "frequency_minutes": cfg.frequency_minutes}, indent=2))
    tmp.replace(CONFIG_PATH)


def normalize_ticker(raw: str) -> str | None:
    t = raw.strip().upper()
    if not TICKER_RE.fullmatch(t):
        return None
    return t


def to_symbol(ticker: str) -> str:
    return f"{ticker}USDT"


def format_price(value: str) -> str:
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError):
        return value
    if d >= 1:
        return f"{d:,.2f}"
    s = f"{d:.8f}".rstrip("0").rstrip(".")
    return s


class PriceBot:
    def __init__(self, token: str, chat_id: int):
        self.token = token
        self.chat_id = chat_id
        self.cfg = load_config()
        self.http = HTTP(testnet=False)

    async def fetch_prices(self, tickers: Iterable[str]) -> list[tuple[str, str]]:
        prices: list[tuple[str, str]] = []
        for t in tickers:
            symbol = to_symbol(t)
            last_price = self._get_last_price(category="spot", symbol=symbol)
            if last_price is None:
                last_price = self._get_last_price(category="linear", symbol=symbol)
            if last_price is None:
                prices.append((t, "error: not available in spot or linear"))
            else:
                prices.append((t, last_price))
        return prices

    def _get_last_price(self, category: str, symbol: str) -> str | None:
        try:
            data = self.http.get_tickers(category=category, symbol=symbol)
        except Exception:
            logging.exception("Bybit request failed for %s (%s)", symbol, category)
            return None
        if not isinstance(data, dict) or data.get("retCode") != 0:
            return None
        items = data.get("result", {}).get("list", [])
        if not items:
            return None
        return items[0].get("lastPrice")

    async def send_prices(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        prices = await self.fetch_prices(self.cfg.tickers)
        lines = ["Spot prices (Bybit):"]
        for t, p in prices:
            if p.startswith("error:"):
                lines.append(f"{t}: {p}")
            else:
                lines.append(f"{t}: ${format_price(p)}")
        await context.bot.send_message(chat_id=self.chat_id, text="\n".join(lines))

    def reschedule(self, application: Application) -> None:
        job_queue = application.job_queue
        for job in job_queue.get_jobs_by_name("price_push"):
            job.schedule_removal()
        job_queue.run_repeating(
            self.send_prices,
            interval=self.cfg.frequency_minutes * 60,
            first=1,
            name="price_push",
        )

    async def cmd_tickers(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Tickers: " + ", ".join(self.cfg.tickers))

    async def cmd_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /add <TICKER>")
            return
        ticker = normalize_ticker(context.args[0])
        if not ticker:
            await update.message.reply_text("Invalid ticker format.")
            return
        if ticker in self.cfg.tickers:
            await update.message.reply_text(f"{ticker} already in list.")
            return
        self.cfg.tickers.append(ticker)
        save_config(self.cfg)
        await update.message.reply_text(f"Added {ticker}.")

    async def cmd_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /remove <TICKER>")
            return
        ticker = normalize_ticker(context.args[0])
        if not ticker:
            await update.message.reply_text("Invalid ticker format.")
            return
        if ticker not in self.cfg.tickers:
            await update.message.reply_text(f"{ticker} not in list.")
            return
        self.cfg.tickers = [t for t in self.cfg.tickers if t != ticker]
        save_config(self.cfg)
        await update.message.reply_text(f"Removed {ticker}.")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.send_prices(context)

    async def cmd_frequency(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /frequency <minutes>")
            return
        try:
            minutes = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Frequency must be an integer number of minutes.")
            return
        if minutes < 1:
            await update.message.reply_text("Frequency must be at least 1 minute.")
            return
        self.cfg.frequency_minutes = minutes
        save_config(self.cfg)
        self.reschedule(context.application)
        await update.message.reply_text(f"Frequency updated to {minutes} minutes.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    token = os.getenv("BOT_TOKEN")
    chat_id_raw = os.getenv("CHAT_ID")
    if not token or not chat_id_raw:
        raise SystemExit("BOT_TOKEN and CHAT_ID must be set in the environment.")

    try:
        chat_id = int(chat_id_raw)
    except ValueError as exc:
        raise SystemExit("CHAT_ID must be an integer.") from exc

    bot = PriceBot(token=token, chat_id=chat_id)

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("tickers", bot.cmd_tickers))
    application.add_handler(CommandHandler("add", bot.cmd_add))
    application.add_handler(CommandHandler("remove", bot.cmd_remove))
    application.add_handler(CommandHandler("status", bot.cmd_status))
    application.add_handler(CommandHandler("frequency", bot.cmd_frequency))

    bot.reschedule(application)

    application.run_polling()


if __name__ == "__main__":
    main()
