# Telegram API Limit + SMTP Checker

English Telegram bot that checks the validity and remaining sending limit of **your own** email provider accounts:

- **SendGrid** — credits remaining / used / total (`GET /v3/user/credits`)
- **Brevo** — plan + credits remaining (`GET /v3/account`)
- **Mailgun** — domains + state, US/EU auto-try (Mailgun does not expose the numeric limit via API)
- **Mailjet** — API keys + senders (remaining credits are dashboard-only)
- **AWS SES** — max/24h, sent last 24h, remaining, send rate, sandbox note (`GetSendQuota`)
- **SMTP** — generic AUTH check (EHLO/STARTTLS/LOGIN). No email is sent.

## Commands

```
/sendgrid SG.your_key
/brevo xkeysib-your_key
/mailgun key-your_key [domain] [us|eu]
/mailjet api_key:secret_key
/ses AKIA...:secret_key [region]
/smtp host:port:username:password
```

Auto-detect: send a bare `SG.` / `xkeysib-` / `key-` key and the bot routes it.

Bulk: send a `.txt` file (max 100 lines by default), one check per line:

```
sendgrid|SG.your_key
brevo|xkeysib-your_key
mailgun|key-your_key|mg.example.com|us
mailjet|api_key:secret_key
ses|AKIA...:secret_key|ap-south-1
smtp|host:port:username:password
```

Results return as `live.txt` / `dead.txt` with keys masked.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Set env vars on your host (never commit them):
   - `BOT_TOKEN` (required)
   - `ALLOWED_USER_IDS` (strongly recommended — your Telegram user ID)
   - `MAX_FILE_LINES=100`, `BULK_CONCURRENCY=5`, `AWS_REGION=ap-south-1` (optional)
3. Run: `pip install -r requirements.txt && python bot.py`
   Or use the included `Dockerfile` / `render.yaml` / `Procfile` (polling worker, no VPS needed).

## Logs to Telegram

Every single check and every bulk summary is logged (masked keys only) to a file (`logs/checker.log`) and forwarded to your Telegram:

1. Easiest: after deploy, open your private chat with the bot and send `/loghere` once. Done — logs arrive in that chat.
2. Or set env `LOG_CHAT_ID` to your chat ID on the host (send `/myid` to the bot to see your IDs).

Commands: `/loghere` (set log chat), `/myid` (show IDs), `/logs` (last 20 entries). The bot also sends a "Bot started" log on startup when a log chat is set. Note: on hosts with ephemeral disks the file log resets on restart — the Telegram log chat is the durable copy.

Example log message:

```
📝 LOG — SendGrid LIVE ✅
Time: 2026-11-26 15:45:00 WIB
Checked by: @you (id 123456789)
Key: SG.abc1...wxyz
Account email: you@example.com
Credits remaining: 98
Credits used: 2
Total credits: 100
```

## Safety

- Keys are never stored or displayed in full (masked like `SG.abc...wxyz`), including in logs.
- The bot tries to delete your message containing a key after reading it.
- Read-only checks only; SMTP check never sends mail.
- Only check accounts you own.
