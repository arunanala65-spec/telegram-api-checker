"""
Local test / example generator. Uses ONLY obviously-fake dummy credentials.
- DEAD examples below are REAL responses from the live provider APIs.
- LIVE examples are SIMULATED formats (mock data) showing exactly how a
  successful check will look with a real key. They are labeled as simulated.
Run: python test_examples.py
"""

from checkers import (
    check_brevo,
    check_mailgun,
    check_mailjet,
    check_sendgrid,
    check_ses,
    check_smtp,
    format_result,
)

print("=" * 70)
print("REAL DEAD EXAMPLES (dummy invalid keys -> live provider APIs)")
print("=" * 70)

print("\n--- SendGrid (dummy key) ---")
print(format_result(check_sendgrid("SG.INVALIDEXAMPLEKEY00000000000000000000000000")))

print("\n--- Brevo (dummy key) ---")
print(format_result(check_brevo("xkeysib-invalid-example-key-0000000000000000")))

print("\n--- Mailgun (dummy key) ---")
print(format_result(check_mailgun("key-invalid-example-0000000000000000")))

print("\n--- Mailjet (dummy key pair) ---")
print(format_result(check_mailjet("invalidapikey0000000000000000", "invalidsecret000000000000000")))

print("\n--- AWS SES (dummy key pair, ap-south-1) ---")
print(format_result(check_ses("AKIAINVALIDEXAMPLE", "invalidSecretExample0000000000000000000", "ap-south-1")))

print("\n--- SMTP (dummy login, smtp.gmail.com:587) ---")
print(format_result(check_smtp("smtp.gmail.com", 587, "invalid-example@gmail.com", "invalid-password")))

print("\n" + "=" * 70)
print("SIMULATED LIVE EXAMPLES (mock data — exact format with a real key)")
print("=" * 70)

simulated = [
    {
        "provider": "SendGrid", "ok": True, "status": "LIVE", "masked": "SG.abc1...wxyz",
        "lines": ["Account email: you@example.com", "Credits remaining: 98", "Credits used: 2", "Total credits: 100", "Next reset: 2026-12-01"],
        "detail": "",
    },
    {
        "provider": "Brevo", "ok": True, "status": "LIVE", "masked": "xkeysi...wxyz",
        "lines": ["Account email: you@example.com", "Plan: free (sendLimit)", "Credits remaining: 287", "SMTP relay enabled: True"],
        "detail": "",
    },
    {
        "provider": "Mailgun", "ok": True, "status": "LIVE", "masked": "key-12...wxyz",
        "lines": ["Region: US", "Domains: 1", "• mg.example.com — active", "Domain mg.example.com: active (type: custom)", "Limit: Mailgun does not expose the sending limit via API — check Sending → Overview in the dashboard"],
        "detail": "",
    },
    {
        "provider": "Mailjet", "ok": True, "status": "LIVE", "masked": "a1b2c3...wxyz",
        "lines": ["API keys on account: 1", "Senders: 1 listed, 1 active", "• you@example.com — Active", "Limit: Mailjet does not expose remaining credits via this endpoint — check Dashboard → Usage"],
        "detail": "",
    },
    {
        "provider": "AWS SES", "ok": True, "status": "LIVE", "masked": "AKIA12...WXYZ",
        "lines": ["Region: ap-south-1", "Max per 24h: 200", "Sent last 24h: 3", "Remaining (24h): 197", "Max send rate: 1.0/sec", "Note: looks like SANDBOX (≤200/day) — production access not granted yet", "Verified identities (first 10): 1", "• you@example.com"],
        "detail": "",
    },
    {
        "provider": "SMTP", "ok": True, "status": "LIVE", "masked": "apikey@smtp.sendgrid.net:587",
        "lines": ["Host: smtp.sendgrid.net:587", "Banner: smtp.sendgrid.net ESMTP", "TLS: yes", "AUTH methods: PLAIN LOGIN", "Capabilities: 8BITMIME, AUTH, ENHANCEDSTATUSCODES, PIPELINING, SIZE, STARTTLS", "Login: OK (no email was sent)"],
        "detail": "",
    },
]

for r in simulated:
    print("\n--- " + r["provider"] + " (SIMULATED LIVE) ---")
    print(format_result(r))
