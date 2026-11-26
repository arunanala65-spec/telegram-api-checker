"""Local log-format test: verifies logs are masked and never contain full secrets."""
from types import SimpleNamespace

import bot
from checkers import check_sendgrid

# Fake update/user for log formatting
fake_user = SimpleNamespace(id=123456789, username="you", first_name="You")
fake_update = SimpleNamespace(effective_user=fake_user, effective_chat=SimpleNamespace(id=123456789))

SECRET = "SG.INVALIDEXAMPLEKEY00000000000000000000000000"
result = check_sendgrid(SECRET)
log_text = bot.format_log_single(fake_update, result)
print(log_text)
assert SECRET not in log_text, "FAIL: full secret leaked into log!"
assert "SG.INV...0000" in log_text, "FAIL: masked key missing"
print("\nMASKING_OK: full secret NOT in log, masked key present")

bulk_text = bot.format_log_bulk(
    fake_update, 3,
    ["SendGrid SG.abc1...wxyz | Credits remaining: 98"],
    [("Mailgun key-in...0000", "Invalid API key (401)")],
)
print("\n" + bulk_text)
assert SECRET not in bulk_text
print("\nBULK_LOG_OK")

# File log round-trip
bot._append_log_file(log_text)
print("\nFILE_LOG_OK:", bot.LOG_FILE)
print("LOG_CHAT_ID (unset expected):", bot.get_log_chat_id())
print("NOW:", bot._now_str())
