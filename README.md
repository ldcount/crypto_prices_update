# crypto_prices_update

Telegram bot that fetches Bybit prices for tracked tickers and sends periodic updates.

## Features

- Default tracked tickers: `BTC`, `ETH`, `PEPE`
- Price source fallback:
  - Try Bybit `spot`
  - If unavailable, try Bybit `linear` (perps)
- Telegram commands:
  - `/tickers` list currently tracked tickers
  - `/add <TICKER>` add ticker
  - `/remove <TICKER>` remove ticker
  - `/status` send current prices now
  - `/frequency <minutes>` change periodic push interval

## Requirements

- Linux server with `systemd`
- Python `3.12.10`
- Network access to:
  - `api.bybit.com`
  - `api.telegram.org`

## Environment Variables

Use the values from `.env.example`:

- `BOT_TOKEN`: Telegram bot token from BotFather
- `CHAT_ID`: Telegram chat ID to receive updates

## Deploy (Same Layout As This Server)

Project path:

- `/opt/bots/crypto_prices_update`

Python path:

- `/opt/py31210/bin/python3.12`

### 1. Create virtual environment and install dependencies

```bash
cd /opt/bots/crypto_prices_update
/opt/py31210/bin/python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 2. Create runtime env file (server-local, not in git)

```bash
sudo install -m 600 /dev/null /etc/crypto_prices_update.env
sudo tee /etc/crypto_prices_update.env >/dev/null << 'ENV'
BOT_TOKEN=replace_with_real_bot_token
CHAT_ID=replace_with_real_chat_id
ENV
```

### 3. Create systemd service

```bash
sudo tee /etc/systemd/system/crypto_prices_update.service >/dev/null << 'UNIT'
[Unit]
Description=Crypto Prices Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bots/crypto_prices_update
EnvironmentFile=/etc/crypto_prices_update.env
ExecStart=/opt/bots/crypto_prices_update/venv/bin/python /opt/bots/crypto_prices_update/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
```

### 4. Start and enable

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now crypto_prices_update.service
```

### 5. Check status/logs

```bash
sudo systemctl status crypto_prices_update.service
sudo journalctl -u crypto_prices_update.service -n 100 --no-pager
```

## Update / Redeploy

```bash
cd /opt/bots/crypto_prices_update
git pull
./venv/bin/pip install -r requirements.txt
sudo systemctl restart crypto_prices_update.service
```

## Security Notes

- Do not commit real tokens or `/etc/crypto_prices_update.env`.
- If a token is exposed, revoke and issue a new one in BotFather.
