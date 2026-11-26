"""
Telegram API Limit + SMTP Checker Bot — English, no VPS needed
===============================================================
Check the sending limit / validity of YOUR OWN accounts:
SendGrid, Mailgun, Mailjet, Brevo, AWS SES, and generic SMTP.

Usage in Telegram:
  /sendgrid SG.your_key
  /brevo xkeysib-your_key
  /mailgun key-your_key [domain] [us|eu]
  /mailjet api_key:secret_key
  /ses AKIA...:secret_key [region]
  /smtp host:port:username:password
  Send a .txt file (max 100 lines) for bulk checks — see /help.

Only needs BOT_TOKEN from @BotFather, set as an env var / secret
on the host. NEVER paste the token in chat.

Safety:
- Keys are never stored and never shown in full (masked everywhere).
- Logs (file + Telegram log chat) contain ONLY masked keys, provider,
  LIVE/DEAD, limit summary, time and checker user ID — never secrets.
- Read-only checks only. No email is sent. SMTP check is AUTH only.
- Restrict the bot to your own Telegram ID via ALLOWED_USER_IDS.
- Only check accounts you own.

Logs to Telegram:
- Set env LOG_CHAT_ID to your Telegram chat ID, OR just send /loghere
  once in your private chat with the bot after deploy.
- Every single check and every bulk summary is then forwarded there.
- /myid shows your IDs, /logs shows the last 20 file-log entries.
"""

import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from checkers import (
    check_brevo,
    check_mailgun,
    check_mailjet,
    check_sendgrid,
    check_ses,
    check_smtp,
    format_result,
    parse_smtp_line,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ALLOWED_USER_IDS = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(",", " ").split() if x.strip().isdigit()
}
MAX_FILE_LINES = int(os.environ.get("MAX_FILE_LINES", "100"))
BULK_CONCURRENCY = int(os.environ.get("BULK_CONCURRENCY", "5"))
MAX_FILE_BYTES = 200_000
DEFAULT_SES_REGION = os.environ.get("AWS_REGION", "ap-south-1").strip() or "ap-south-1"
# Telegram log forwarding: env LOG_CHAT_ID wins; otherwise /loghere at runtime.
# Logs are OWNER-ONLY: env OWNER_ID wins; otherwise the first user to send
# /loghere claims ownership. Only the owner can set the log chat or view /logs.
LOG_CHAT_ID_ENV = os.environ.get("LOG_CHAT_ID", "").strip()
OWNER_ID_ENV = os.environ.get("OWNER_ID", "").strip()
_runtime_owner_id = None  # claimed via /loghere, persisted to LOG_STATE_FILE
LOG_FILE = os.environ.get("LOG_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "checker.log"))
LOG_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log_config.json")
_runtime_log_chat_id = None  # set by /loghere, persisted to LOG_STATE_FILE

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger("api-checker")
_executor = ThreadPoolExecutor(max_workers=10)


async def run_sync(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, fn, *args)


def is_allowed(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return bool(update.effective_user and update.effective_user.id in ALLOWED_USER_IDS)


async def try_delete(update: Update):
    try:
        await update.message.delete()
    except Exception:
        pass


# ---------- Logging (masked only — never secrets) ----------
def _now_str() -> str:
    # WIB is a fixed UTC+7 offset (no DST) — avoids any tzdata dependency.
    from datetime import timedelta

    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S WIB")


def _load_log_state():
    global _runtime_log_chat_id, _runtime_owner_id
    try:
        with open(LOG_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        v = data.get("log_chat_id")
        if v is not None:
            _runtime_log_chat_id = int(v)
        o = data.get("owner_id")
        if o is not None:
            _runtime_owner_id = int(o)
    except Exception:
        pass


def _save_log_state():
    try:
        with open(LOG_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"log_chat_id": _runtime_log_chat_id, "owner_id": _runtime_owner_id}, f)
    except Exception:
        pass


def get_owner_id():
    if OWNER_ID_ENV:
        try:
            return int(OWNER_ID_ENV)
        except ValueError:
            pass
    if _runtime_owner_id is not None:
        return _runtime_owner_id
    if ALLOWED_USER_IDS:
        return sorted(ALLOWED_USER_IDS)[0]
    return None


def is_owner(update: Update) -> bool:
    owner = get_owner_id()
    return bool(owner and update.effective_user and update.effective_user.id == owner)


def get_log_chat_id():
    if LOG_CHAT_ID_ENV:
        try:
            return int(LOG_CHAT_ID_ENV)
        except ValueError:
            return LOG_CHAT_ID_ENV
    if _runtime_log_chat_id is not None:
        return _runtime_log_chat_id
    owner = get_owner_id()
    if owner:
        return owner  # owner's private chat ID == owner user ID
    return None


def _append_log_file(text: str):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
    except Exception:
        pass


def _user_label(update: Update) -> str:
    u = update.effective_user
    if not u:
        return "unknown"
    name = f"@{u.username}" if u.username else (u.first_name or "user")
    return f"{name} (id {u.id})"


def format_log_single(update: Update, result: dict) -> str:
    icon = "✅" if result["ok"] else "❌"
    lines = [
        f"📝 LOG — {result['provider']} {result['status']} {icon}",
        f"Time: {_now_str()}",
        f"Checked by: {_user_label(update)}",
        f"Key: {result.get('masked') or '***'}",
    ]
    lines.extend(result.get("lines") or [])
    if result.get("detail"):
        lines.append(result["detail"])
    return "\n".join(lines)


def format_log_bulk(update: Update, total: int, live_labels, dead_pairs) -> str:
    lines = [
        "📝 LOG — Bulk check done",
        f"Time: {_now_str()}",
        f"Checked by: {_user_label(update)}",
        f"Total: {total} — LIVE {len(live_labels)} • DEAD {len(dead_pairs)}",
    ]
    for label in live_labels[:10]:
        lines.append(f"✅ {label}")
    if len(live_labels) > 10:
        lines.append(f"… +{len(live_labels) - 10} more LIVE (see live.txt)")
    for label, why in dead_pairs[:10]:
        lines.append(f"❌ {label} | {why}")
    if len(dead_pairs) > 10:
        lines.append(f"… +{len(dead_pairs) - 10} more DEAD (see dead.txt)")
    return "\n".join(lines)


async def send_log(context: ContextTypes.DEFAULT_TYPE, text: str):
    """Append to file log + forward to Telegram log chat. Never raises."""
    _append_log_file(text)
    chat_id = get_log_chat_id()
    if chat_id is None:
        return
    try:
        await context.bot.send_message(chat_id=chat_id, text=text[:4000])
    except Exception as e:
        log.warning("Log forward failed: %s", e)


START_TEXT = """👋 Hi! I'm the API Limit + SMTP Checker.

I check *your own* SendGrid, Mailgun, Mailjet, Brevo, AWS SES and SMTP accounts — valid or not, and how much limit is left. Nothing is stored, no email is sent.

*Commands:*
`/sendgrid SG.your_key`
`/brevo xkeysib-your_key`
`/mailgun key-your_key [domain] [us|eu]`
`/mailjet api_key:secret_key`
`/ses AKIA...:secret_key [region]`
`/smtp host:port:username:password`

*Examples:*
`/sendgrid SG.abc123...`
`/ses AKIAEXAMPLE:secretkey ap-south-1`
`/smtp smtp.sendgrid.net:587:apikey:SG.abc123...`

*Bulk file:*
Send a `.txt` file, one check per line (max {max_lines}). Format is in /help.

*Logs (owner-only):*
The bot owner sends `/loghere` once and every check result (masked) is forwarded to the owner. `/myid` shows your IDs, `/logs` (owner only) shows recent logs.

Tap a checker button below to start:

Your message with a key is deleted automatically when possible, and keys are only shown masked.

Type /help for details.
"""

HELP_TEXT = """🛠 *Help — API Limit + SMTP Checker*

*SendGrid* (needs API key):
`/sendgrid SG.your_key`
Shows credits remaining / used / total.

*Brevo* (needs API key):
`/brevo xkeysib-your_key`
Shows plan + credits remaining.

*Mailgun* (needs API key):
`/mailgun key-your_key`
`/mailgun key-your_key mg.example.com us`
Shows domains + state. Mailgun does not expose the numeric limit via API.

*Mailjet* (needs API key + Secret key):
`/mailjet api_key:secret_key`
Shows API keys + senders. Remaining credits are only in the dashboard.

*AWS SES* (needs Access Key ID + Secret, region optional):
`/ses AKIA...:secret_key`
`/ses AKIA...:secret_key ap-south-1`
Shows max/24h, sent last 24h, remaining, send rate, sandbox note.

*SMTP* (AUTH check only, no email sent):
`/smtp host:port:username:password`
Example: `/smtp email-smtp.ap-south-1.amazonaws.com:587:AKIA...:secret`

*Bulk .txt file* — one per line:
```
sendgrid|SG.your_key
brevo|xkeysib-your_key
mailgun|key-your_key|mg.example.com|us
mailjet|api_key:secret_key
ses|AKIA...:secret_key|ap-south-1
smtp|host:port:username:password
```
Max {max_lines} lines per file. Results come back as live.txt / dead.txt (keys masked).

*Auto-detect:* you can also just send a key — `SG.` = SendGrid, `xkeysib-` = Brevo, `key-` = Mailgun. SES / Mailjet / SMTP need their command because they need 2+ parts.

*Menu:* tap /menu (or /start) and pick a checker button — SendGrid, Brevo, Mailgun, Mailjet, AWS SES, SMTP — then send the key when asked. /cancel aborts. Commands below still work too. Results also show the account's sender emails/identities when the provider exposes them.

*Logs to Telegram (owner-only):*
`/loghere` — owner only: set THIS chat as the log destination (the first user to send it becomes the owner; or set env OWNER_ID)
`/myid` — show your user ID + chat ID (for OWNER_ID / LOG_CHAT_ID / ALLOWED_USER_IDS)
`/logs` — owner only: show the last 20 log entries
Every single check and every bulk summary is forwarded to the owner's log chat. Logs contain masked keys only — never full secrets.

*Privacy:* read-only official endpoints + SMTP login only. Full keys/passwords are never saved or logged.
"""


PROVIDER_PROMPTS = {
    "sendgrid": "Send your *SendGrid* API key (starts with `SG.`):",
    "brevo": "Send your *Brevo* API key (starts with `xkeysib-`):",
    "mailgun": "Send your *Mailgun* API key (starts with `key-`). Optional: add domain + region after it, e.g. `key-xxx mg.example.com us`:",
    "mailjet": "Send your *Mailjet* keys as `api_key:secret_key`:",
    "ses": "Send your *AWS SES* keys as `ACCESS_KEY:SECRET_KEY` (optional region after, e.g. `AKIA...:secret ap-south-1`):",
    "smtp": "Send your *SMTP* login as `host:port:username:password`:",
}


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("SendGrid", callback_data="prov:sendgrid"), InlineKeyboardButton("Brevo", callback_data="prov:brevo")],
            [InlineKeyboardButton("Mailgun", callback_data="prov:mailgun"), InlineKeyboardButton("Mailjet", callback_data="prov:mailjet")],
            [InlineKeyboardButton("AWS SES", callback_data="prov:ses"), InlineKeyboardButton("SMTP", callback_data="prov:smtp")],
            [InlineKeyboardButton("Bulk .txt", callback_data="menu:bulk"), InlineKeyboardButton("Help", callback_data="menu:help")],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    await update.message.reply_text(
        START_TEXT.format(max_lines=MAX_FILE_LINES), parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    await update.message.reply_text("Pick a checker:", reply_markup=main_menu_keyboard())


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending", None)
    await update.message.reply_text("Cancelled. Pick a checker:", reply_markup=main_menu_keyboard())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_allowed(update):
        return
    data = query.data or ""
    if data.startswith("prov:"):
        provider = data.split(":", 1)[1]
        if provider in PROVIDER_PROMPTS:
            context.user_data["pending"] = provider
            await query.message.reply_text(
                PROVIDER_PROMPTS[provider] + "\n\n(/cancel to abort)", parse_mode="Markdown"
            )
    elif data == "menu:bulk":
        await query.message.reply_text(
            "Send a `.txt` file, one check per line (max "
            f"{MAX_FILE_LINES}). Formats are in /help — e.g. `sendgrid|SG.your_key`.",
            parse_mode="Markdown",
        )
    elif data == "menu:help":
        await query.message.reply_text(HELP_TEXT.format(max_lines=MAX_FILE_LINES), parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(HELP_TEXT.format(max_lines=MAX_FILE_LINES), parse_mode="Markdown")


def _args_text(update: Update) -> str:
    return re.sub(r"^/\w+(?:@\w+)?\s*", "", update.message.text or "").strip()


async def _reply_result(update: Update, context: ContextTypes.DEFAULT_TYPE, result: dict):
    await try_delete(update)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=format_result(result), parse_mode="Markdown")
    await send_log(context, format_log_single(update, result))


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    u = update.effective_user
    chat = update.effective_chat
    await update.message.reply_text(
        f"Your user ID: {u.id if u else '?'}\n"
        f"This chat ID: {chat.id if chat else '?'}\n"
        f"Log chat ID (current): {get_log_chat_id() or 'not set — send /loghere'}\n\n"
        "Use the user ID for ALLOWED_USER_IDS and the chat ID for LOG_CHAT_ID on the host."
    )


async def loghere_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    global _runtime_log_chat_id, _runtime_owner_id
    owner = get_owner_id()
    if owner and not is_owner(update):
        await update.message.reply_text("🔒 Logs are owner-only. Only the bot owner can set the log destination.")
        return
    if not owner:
        # First claim: this user becomes the bot owner for log purposes.
        _runtime_owner_id = update.effective_user.id
    _runtime_log_chat_id = update.effective_chat.id
    _save_log_state()
    await update.message.reply_text(
        "✅ Log destination set to this chat (owner-only).\n"
        "Every check result (masked keys only) will now be forwarded here.\n"
        "Send /logs anytime to see recent entries."
    )
    await send_log(context, f"📝 LOG — Log destination set\nTime: {_now_str()}\nSet by: {_user_label(update)}")


async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    if not is_owner(update):
        await update.message.reply_text("🔒 Logs are owner-only. The bot owner can view them with /logs after sending /loghere.")
        return
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            entries = [ln.rstrip() for ln in f if ln.strip()]
    except Exception:
        entries = []
    if not entries:
        await update.message.reply_text("No logs yet. Run a check first, e.g. /sendgrid SG.your_key")
        return
    tail = entries[-20:]
    text = "🗂 Last logs:\n\n" + "\n".join(tail)
    if len(text) > 4000:
        await update.message.reply_document(document="\n".join(entries).encode(), filename="checker.log", caption="Full log file (masked)")
    else:
        await update.message.reply_text(text)


async def sendgrid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    key = _args_text(update).split()[0] if _args_text(update) else ""
    if not key:
        await update.message.reply_text("Usage:\n`/sendgrid SG.your_key`", parse_mode="Markdown")
        return
    await _reply_result(update, context, await run_sync(check_sendgrid, key))


async def brevo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    key = _args_text(update).split()[0] if _args_text(update) else ""
    if not key:
        await update.message.reply_text("Usage:\n`/brevo xkeysib-your_key`", parse_mode="Markdown")
        return
    await _reply_result(update, context, await run_sync(check_brevo, key))


async def mailgun_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    parts = _args_text(update).split()
    if not parts:
        await update.message.reply_text("Usage:\n`/mailgun key-your_key [domain] [us|eu]`", parse_mode="Markdown")
        return
    key = parts[0]
    domain = parts[1] if len(parts) > 1 and "." in parts[1] else ""
    region = parts[-1] if parts[-1].lower() in ("us", "eu") else "us"
    await _reply_result(update, context, await run_sync(check_mailgun, key, domain, region))


async def mailjet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    raw = _args_text(update)
    key = sec = ""
    if ":" in raw and " " not in raw.strip():
        key, sec = raw.split(":", 1)
    else:
        p = raw.split()
        if len(p) >= 2:
            key, sec = p[0], p[1]
    if not key or not sec:
        await update.message.reply_text("Usage:\n`/mailjet api_key:secret_key`", parse_mode="Markdown")
        return
    await _reply_result(update, context, await run_sync(check_mailjet, key.strip(), sec.strip()))


async def ses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    raw = _args_text(update)
    region = DEFAULT_SES_REGION
    ak = sk = ""
    # Forms: AKIA:secret [region]  |  AKIA secret [region]
    tokens = raw.split()
    if tokens and re.fullmatch(r"[a-z]{2}-[a-z]+-\d", tokens[-1]):
        region = tokens.pop()
    joined = " ".join(tokens)
    if ":" in joined and len(tokens) == 1:
        ak, sk = joined.split(":", 1)
    elif len(tokens) >= 2:
        ak, sk = tokens[0], tokens[1]
    elif ":" in joined:
        ak, sk = joined.split(":", 1)
    if not ak or not sk:
        await update.message.reply_text("Usage:\n`/ses AKIA...:secret_key [region]`\nExample:\n`/ses AKIAEXAMPLE:secretkey ap-south-1`", parse_mode="Markdown")
        return
    await _reply_result(update, context, await run_sync(check_ses, ak.strip(), sk.strip(), region))


async def smtp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    raw = _args_text(update)
    parsed = parse_smtp_line(raw)
    if not parsed:
        await update.message.reply_text("Usage:\n`/smtp host:port:username:password`", parse_mode="Markdown")
        return
    host, port, user, pw = parsed
    await _reply_result(update, context, await run_sync(check_smtp, host, port, user, pw))


def detect_provider(text: str):
    t = (text or "").strip()
    if t.startswith("SG."):
        return ("sendgrid", t.split()[0])
    if t.startswith("xkeysib-"):
        return ("brevo", t.split()[0])
    if t.startswith("key-") or t.startswith("pubkey-"):
        return ("mailgun", t.split()[0])
    return None


async def _run_pending(update: Update, context: ContextTypes.DEFAULT_TYPE, provider: str, text: str):
    """Run a check for the provider chosen via the menu buttons."""
    if provider == "sendgrid":
        await _reply_result(update, context, await run_sync(check_sendgrid, text.split()[0]))
    elif provider == "brevo":
        await _reply_result(update, context, await run_sync(check_brevo, text.split()[0]))
    elif provider == "mailgun":
        parts = text.split()
        domain = parts[1] if len(parts) > 1 else ""
        region = parts[2] if len(parts) > 2 else "us"
        await _reply_result(update, context, await run_sync(check_mailgun, parts[0], domain, region))
    elif provider == "mailjet":
        if ":" not in text:
            await update.message.reply_text("Mailjet needs `api_key:secret_key`. Tap Mailjet in /menu and try again.", parse_mode="Markdown")
            return
        k, s = text.split(":", 1)
        await _reply_result(update, context, await run_sync(check_mailjet, k.strip(), s.strip()))
    elif provider == "ses":
        parts = text.split()
        pair = parts[0]
        if ":" in pair:
            ak, sk = pair.split(":", 1)
        elif len(parts) >= 2:
            ak, sk = parts[0], parts[1]
            parts = [pair, ""] + parts[2:]
        else:
            await update.message.reply_text("SES needs `ACCESS_KEY:SECRET_KEY`. Tap AWS SES in /menu and try again.", parse_mode="Markdown")
            return
        region = parts[1] if len(parts) > 1 and parts[1] else DEFAULT_SES_REGION
        await _reply_result(update, context, await run_sync(check_ses, ak.strip(), sk.strip(), region))
    elif provider == "smtp":
        parsed = parse_smtp_line(text)
        if not parsed:
            await update.message.reply_text("SMTP needs `host:port:username:password`. Tap SMTP in /menu and try again.", parse_mode="Markdown")
            return
        await _reply_result(update, context, await run_sync(check_smtp, *parsed))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    text = (update.message.text or "").strip()
    pending = context.user_data.pop("pending", None)
    if pending:
        await _run_pending(update, context, pending, text)
        return
    det = detect_provider(text)
    if det:
        provider, key = det
        if provider == "sendgrid":
            await _reply_result(update, context, await run_sync(check_sendgrid, key))
        elif provider == "brevo":
            await _reply_result(update, context, await run_sync(check_brevo, key))
        elif provider == "mailgun":
            await _reply_result(update, context, await run_sync(check_mailgun, key, "", "us"))
        return
    await update.message.reply_text(
        "Pick a checker from the menu, or send a command like `/sendgrid SG.your_key`.\n"
        "Auto-detect works for SendGrid (`SG.`), Brevo (`xkeysib-`) and Mailgun (`key-`) keys.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def _check_bulk_line(line: str):
    """Return (ok, label, detail). Label is masked — never contains the full secret."""
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 2:
        return (False, line[:40], "Bad format — use provider|credential (see /help)")
    provider = parts[0].lower()
    try:
        if provider == "sendgrid":
            r = await run_sync(check_sendgrid, parts[1])
        elif provider == "brevo":
            r = await run_sync(check_brevo, parts[1])
        elif provider == "mailgun":
            domain = parts[2] if len(parts) > 2 else ""
            region = parts[3] if len(parts) > 3 else "us"
            r = await run_sync(check_mailgun, parts[1], domain, region)
        elif provider == "mailjet":
            if ":" not in parts[1]:
                return (False, "Mailjet ?", "Needs api_key:secret_key")
            k, s = parts[1].split(":", 1)
            r = await run_sync(check_mailjet, k, s)
        elif provider in ("ses", "aws", "awsses"):
            if ":" not in parts[1]:
                return (False, "AWS SES ?", "Needs ACCESS:SECRET")
            ak, sk = parts[1].split(":", 1)
            region = parts[2] if len(parts) > 2 else DEFAULT_SES_REGION
            r = await run_sync(check_ses, ak, sk, region)
        elif provider == "smtp":
            parsed = parse_smtp_line(parts[1])
            if not parsed:
                return (False, "SMTP ?", "Needs host:port:user:pass")
            r = await run_sync(check_smtp, *parsed)
        else:
            return (False, line[:40], f"Unknown provider: {provider}")
    except Exception as e:
        return (False, provider, f"Error: {e}"[:150])
    summary = " • ".join(r["lines"][:3]) if r["lines"] else r["detail"]
    label = f"{r['provider']} {r['masked']} | {summary}"[:220]
    return (bool(r["ok"]), label, "" if r["ok"] else (r["detail"] or summary)[:180])


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    doc = update.message.document
    if not doc or not (doc.file_name or "").lower().endswith(".txt"):
        await update.message.reply_text("Send a `.txt` file, one check per line. See /help for the format.", parse_mode="Markdown")
        return
    if doc.file_size and doc.file_size > MAX_FILE_BYTES:
        await update.message.reply_text("File too large (max ~200 KB).")
        return
    f = await doc.get_file()
    data = await f.download_as_bytearray()
    text = bytes(data).decode("utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        await update.message.reply_text("File is empty.")
        return
    if len(lines) > MAX_FILE_LINES:
        await update.message.reply_text(f"Max {MAX_FILE_LINES} lines per file, yours has {len(lines)}. Split it first.")
        return

    status = await update.message.reply_text(f"⏳ Checking {len(lines)} lines… (parallel {BULK_CONCURRENCY})")
    sem = asyncio.Semaphore(BULK_CONCURRENCY)

    async def one(line: str):
        async with sem:
            return await _check_bulk_line(line)

    results = await asyncio.gather(*[one(ln) for ln in lines])
    live = [label for ok, label, _ in results if ok]
    dead = [(label, why) for ok, label, why in results if not ok]
    await status.edit_text(f"📊 Done: {len(lines)} checks — ✅ LIVE {len(live)} • ❌ DEAD {len(dead)}\nResult files below (keys masked).")
    live_txt = "\n".join(live) if live else "(none)"
    dead_txt = "\n".join(f"{a} | {b}" for a, b in dead) if dead else "(none)"
    await update.message.reply_document(document=live_txt.encode(), filename="live.txt", caption=f"✅ LIVE {len(live)}")
    await update.message.reply_document(document=dead_txt.encode(), filename="dead.txt", caption=f"❌ DEAD {len(dead)}")
    await send_log(context, format_log_bulk(update, len(lines), live, dead))


def _start_keepalive_server():
    port = int(os.environ.get("PORT", "0") or 0)
    if not port:
        return
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    threading.Thread(target=HTTPServer(("0.0.0.0", port), H).serve_forever, daemon=True).start()
    log.info("Keep-alive HTTP on port %s", port)


async def _post_init(app: Application):
    chat_id = get_log_chat_id()
    if chat_id is None:
        return
    try:
        await app.bot.send_message(chat_id=chat_id, text=f"📝 LOG — Bot started\nTime: {_now_str()}\nAPI Limit + SMTP Checker is online.")
    except Exception:
        pass


def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Set env var BOT_TOKEN from @BotFather. See .env.example")
    _load_log_state()
    _start_keepalive_server()
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("loghere", loghere_cmd))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(CommandHandler("sendgrid", sendgrid_cmd))
    app.add_handler(CommandHandler("brevo", brevo_cmd))
    app.add_handler(CommandHandler("mailgun", mailgun_cmd))
    app.add_handler(CommandHandler("mailjet", mailjet_cmd))
    app.add_handler(CommandHandler(["ses", "aws"], ses_cmd))
    app.add_handler(CommandHandler("smtp", smtp_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    log.info("API Limit + SMTP Checker running (polling). Max file: %s lines.", MAX_FILE_LINES)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
