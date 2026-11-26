# Example checker results

Bot language: English. Keys are always masked.

- **DEAD examples for SendGrid / Brevo / Mailgun / Mailjet / AWS SES are REAL** — dummy invalid keys checked against the live provider APIs on 26 Nov 2026.
- **LIVE examples are SIMULATED formats** (mock numbers) showing exactly how a successful check looks with a real key, because no real valid keys were used for this test.
- **SMTP**: the Muse VM blocks outgoing SMTP, so a live SMTP login could not be tested from here. Both SMTP formats below are simulated; the code itself (EHLO → STARTTLS → LOGIN, no mail sent) is standard `smtplib` and will run on a normal host.

---

## 1. SendGrid

Command: `/sendgrid SG.your_key`

LIVE (simulated format):
```
✅ LIVE — SendGrid
Key: SG.abc1...wxyz
Account email: you@example.com
Credits remaining: 98
Credits used: 2
Total credits: 100
Next reset: 2026-12-01
```

DEAD (real, dummy key):
```
❌ DEAD — SendGrid
Key: SG.INV...0000
Status: Invalid API key (401)
Check the key in SendGrid → Settings → API Keys.
```

## 2. Brevo

Command: `/brevo xkeysib-your_key`

LIVE (simulated format):
```
✅ LIVE — Brevo
Key: xkeysi...wxyz
Account email: you@example.com
Plan: free (sendLimit)
Credits remaining: 287
SMTP relay enabled: True
```

DEAD (real, dummy key):
```
❌ DEAD — Brevo
Key: xkeysi...0000
Status: Invalid API key (401)
Use an API key from Brevo → SMTP & API → API Keys (starts with xkeysib-).
```

## 3. Mailgun

Command: `/mailgun key-your_key [domain] [us|eu]`

LIVE (simulated format):
```
✅ LIVE — Mailgun
Key: key-12...wxyz
Region: US
Domains: 1
• mg.example.com — active
Domain mg.example.com: active (type: custom)
Limit: Mailgun does not expose the sending limit via API — check Sending → Overview in the dashboard
```

DEAD (real, dummy key):
```
❌ DEAD — Mailgun
Key: key-in...0000
Invalid API key (401)
```

## 4. Mailjet

Command: `/mailjet api_key:secret_key`

LIVE (simulated format):
```
✅ LIVE — Mailjet
Key: a1b2c3...wxyz
API keys on account: 1
Senders: 1 listed, 1 active
• you@example.com — Active
Limit: Mailjet does not expose remaining credits via this endpoint — check Dashboard → Usage
```

DEAD (real, dummy key pair):
```
❌ DEAD — Mailjet
Key: invali...0000
Status: Invalid API key / Secret key (401)
Copy both keys from Mailjet → Account → API Keys.
```

## 5. AWS SES

Command: `/ses AKIA...:secret_key [region]` (default region ap-south-1)

LIVE (simulated format):
```
✅ LIVE — AWS SES
Key: AKIA12...WXYZ
Region: ap-south-1
Max per 24h: 200
Sent last 24h: 3
Remaining (24h): 197
Max send rate: 1.0/sec
Note: looks like SANDBOX (≤200/day) — production access not granted yet
Verified identities (first 10): 1
• you@example.com
```

DEAD (real, dummy key pair):
```
❌ DEAD — AWS SES
Key: AKIAIN...MPLE
Status: Invalid credentials (InvalidClientTokenId)
Region checked: ap-south-1
The security token included in the request is invalid.
```

## 6. SMTP (generic, AUTH only — no email sent)

Command: `/smtp host:port:username:password`

LIVE (simulated format):
```
✅ LIVE — SMTP
Key: apikey@smtp.sendgrid.net:587
Host: smtp.sendgrid.net:587
Banner: smtp.sendgrid.net ESMTP
TLS: yes
AUTH methods: PLAIN LOGIN
Capabilities: 8BITMIME, AUTH, ENHANCEDSTATUSCODES, PIPELINING, SIZE, STARTTLS
Login: OK (no email was sent)
```

DEAD — wrong password (simulated format):
```
❌ DEAD — SMTP
Key: user@example.com@smtp.example.com:587
Host: smtp.example.com:587
Login: rejected
SMTP auth failed (535): 5.7.8 Error: authentication failed
```

Note: from the Muse VM the real test returned "Outgoing email (SMTP) is turned off for this assistant" — that is a VM egress block, not a bot bug. On the hosting server the same code connects normally (unless the host blocks SMTP ports).

## Bulk file format (.txt, max 100 lines)

```
sendgrid|SG.your_key
brevo|xkeysib-your_key
mailgun|key-your_key|mg.example.com|us
mailjet|api_key:secret_key
ses|AKIA...:secret_key|ap-south-1
smtp|host:port:username:password
```

Results return as `live.txt` / `dead.txt` with masked keys.

## Telegram logs (sent to the owner's Telegram)

Setup: send `/loghere` once in your private chat with the bot (or set env `LOG_CHAT_ID`). `/myid` shows your IDs, `/logs` shows the last 20 entries. Logs contain masked keys only — never full secrets.

Single check log (example):
```
📝 LOG — SendGrid LIVE ✅
Time: 2026-11-26 15:45:00 WIB
Checked by: @you (id 123456789)
Key: SG.abc1...wxyz
Account email: you@example.com
Credits remaining: 98
Credits used: 2
Total credits: 100
Next reset: 2026-12-01
```

Failed check log (example):
```
📝 LOG — AWS SES DEAD ❌
Time: 2026-11-26 15:46:00 WIB
Checked by: @you (id 123456789)
Key: AKIAIN...MPLE
Status: Invalid credentials (InvalidClientTokenId)
Region checked: ap-south-1
The security token included in the request is invalid.
```

Bulk log (example — one summary message, not one per line):
```
📝 LOG — Bulk check done
Time: 2026-11-26 15:50:00 WIB
Checked by: @you (id 123456789)
Total: 5 — LIVE 3 • DEAD 2
✅ SendGrid SG.abc1...wxyz | Credits remaining: 98
✅ Brevo xkeysi...wxyz | Credits remaining: 287
❌ Mailgun key-in...0000 | Invalid API key (401)
```

Startup log:
```
📝 LOG — Bot started
Time: 2026-11-26 15:40:00 WIB
API Limit + SMTP Checker is online.
```
