"""
API limit + SMTP checkers — for accounts YOU own.
=================================================
Each checker only calls the provider's official read-only endpoints
(or an SMTP AUTH handshake). Nothing is sent, nothing is stored,
secrets are never logged and are masked in every result.

Providers: SendGrid, Mailgun, Mailjet, Brevo, AWS SES, generic SMTP.
"""

import hashlib
import hmac
import smtplib
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

TIMEOUT = 15


def mask(secret: str) -> str:
    s = (secret or "").strip()
    if len(s) <= 12:
        return "***"
    return f"{s[:6]}...{s[-4:]}"


def _result(provider, ok, masked, lines, detail=""):
    return {
        "provider": provider,
        "ok": ok,
        "status": "LIVE" if ok else "DEAD",
        "masked": masked,
        "lines": lines,
        "detail": detail,
    }


def format_result(r: dict) -> str:
    icon = "✅" if r["ok"] else "❌"
    head = f"{icon} {r['status']} — {r['provider']}"
    if r.get("masked"):
        head += f"\nKey: `{r['masked']}`"
    body = "\n".join(r.get("lines") or [])
    out = head + ("\n" + body if body else "")
    if r.get("detail"):
        out += f"\n{r['detail']}"
    return out


# ---------------------------------------------------------------- SendGrid
def check_sendgrid(api_key: str) -> dict:
    key = (api_key or "").strip()
    m = mask(key)
    if not key:
        return _result("SendGrid", False, m, [], "Empty API key.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        r = requests.get("https://api.sendgrid.com/v3/user/credits", headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        return _result("SendGrid", False, m, [], f"Network error: {e}")

    if r.status_code == 401:
        return _result("SendGrid", False, m, ["Status: Invalid API key (401)"], "Check the key in SendGrid → Settings → API Keys.")
    if r.status_code == 403:
        # Key is valid but lacks permission for the credits endpoint.
        lines = ["Status: Key valid, but no permission to read credits (403)"]
        try:
            p = requests.get("https://api.sendgrid.com/v3/user/profile", headers=headers, timeout=TIMEOUT)
            if p.ok:
                j = p.json()
                if j.get("email"):
                    lines.append(f"Account email: {j['email']}")
                if j.get("username"):
                    lines.append(f"Username: {j['username']}")
        except requests.RequestException:
            pass
        lines.append("Limit: not readable with this key's scopes")
        return _result("SendGrid", True, m, lines, "Create a key with full access to see the exact limit.")
    if not r.ok:
        return _result("SendGrid", False, m, [f"HTTP {r.status_code}"], (r.text or "")[:200])

    j = r.json() if r.text else {}
    total = j.get("total")
    used = j.get("used")
    remain = j.get("remain")
    lines = []
    try:
        p = requests.get("https://api.sendgrid.com/v3/user/profile", headers=headers, timeout=TIMEOUT)
        if p.ok:
            pj = p.json()
            if pj.get("email"):
                lines.append(f"Account email: {pj['email']}")
    except requests.RequestException:
        pass
    if remain is not None:
        lines.append(f"Credits remaining: {remain}")
    if used is not None:
        lines.append(f"Credits used: {used}")
    if total is not None:
        lines.append(f"Total credits: {total}")
    if j.get("next_reset"):
        lines.append(f"Next reset: {j['next_reset']}")
    if not lines:
        lines.append("Credits endpoint OK (no quota fields returned)")
    return _result("SendGrid", True, m, lines)


# ---------------------------------------------------------------- Mailgun
def check_mailgun(api_key: str, domain: str = "", region: str = "us") -> dict:
    key = (api_key or "").strip()
    m = mask(key)
    if not key:
        return _result("Mailgun", False, m, [], "Empty API key.")
    region = (region or "us").strip().lower()
    bases = []
    if region == "eu":
        bases = [("eu", "https://api.eu.mailgun.net"), ("us", "https://api.mailgun.net")]
    else:
        bases = [("us", "https://api.mailgun.net"), ("eu", "https://api.eu.mailgun.net")]

    last_err = ""
    for reg, base in bases:
        try:
            r = requests.get(f"{base}/v3/domains", params={"limit": 10}, auth=("api", key), timeout=TIMEOUT)
        except requests.RequestException as e:
            last_err = f"Network error: {e}"
            continue
        if r.status_code == 401:
            last_err = "Invalid API key (401)"
            continue
        if not r.ok:
            last_err = f"HTTP {r.status_code}: {(r.text or '')[:160]}"
            continue
        j = r.json() if r.text else {}
        items = j.get("items") or []
        total = j.get("total_count", len(items))
        lines = [f"Region: {reg.upper()}", f"Domains: {total}"]
        for it in items[:5]:
            lines.append(f"• {it.get('name', '?')} — {it.get('state', '?')}")
        if domain:
            d = domain.strip()
            try:
                dr = requests.get(f"{base}/v3/domains/{d}", auth=("api", key), timeout=TIMEOUT)
                if dr.ok:
                    dj = (dr.json() or {}).get("domain") or {}
                    lines.append(f"Domain {d}: {dj.get('state', '?')} (type: {dj.get('type', '?')})")
                else:
                    lines.append(f"Domain {d}: not found / HTTP {dr.status_code}")
            except requests.RequestException:
                pass
        lines.append("Limit: Mailgun does not expose the sending limit via API — check Sending → Overview in the dashboard")
        return _result("Mailgun", True, m, lines)
    return _result("Mailgun", False, m, [], last_err or "Invalid API key.")


# ---------------------------------------------------------------- Mailjet
def check_mailjet(api_key: str, secret_key: str) -> dict:
    key = (api_key or "").strip()
    sec = (secret_key or "").strip()
    m = mask(key)
    if not key or not sec:
        return _result("Mailjet", False, m, [], "Mailjet needs BOTH the API key and the Secret key.")
    try:
        r = requests.get("https://api.mailjet.com/v3/REST/apikey", auth=(key, sec), timeout=TIMEOUT)
    except requests.RequestException as e:
        return _result("Mailjet", False, m, [], f"Network error: {e}")
    if r.status_code == 401:
        return _result("Mailjet", False, m, ["Status: Invalid API key / Secret key (401)"], "Copy both keys from Mailjet → Account → API Keys.")
    if not r.ok:
        return _result("Mailjet", False, m, [f"HTTP {r.status_code}"], (r.text or "")[:200])

    j = r.json() if r.text else {}
    count = j.get("Count", len(j.get("Data") or []))
    lines = [f"API keys on account: {count}"]
    # Senders give a practical "can it send" signal.
    try:
        s = requests.get("https://api.mailjet.com/v3/REST/sender", auth=(key, sec), params={"Limit": 10}, timeout=TIMEOUT)
        if s.ok:
            sj = s.json() or {}
            senders = sj.get("Data") or []
            active = sum(1 for x in senders if str(x.get("Status", "")).lower() == "active")
            lines.append(f"Senders: {len(senders)} listed, {active} active")
            for x in senders[:5]:
                lines.append(f"• {x.get('Email', '?')} — {x.get('Status', '?')}")
    except requests.RequestException:
        pass
    lines.append("Limit: Mailjet does not expose remaining credits via this endpoint — check Dashboard → Usage")
    return _result("Mailjet", True, m, lines)


# ---------------------------------------------------------------- Brevo
def check_brevo(api_key: str) -> dict:
    key = (api_key or "").strip()
    m = mask(key)
    if not key:
        return _result("Brevo", False, m, [], "Empty API key.")
    try:
        r = requests.get("https://api.brevo.com/v3/account", headers={"api-key": key, "accept": "application/json"}, timeout=TIMEOUT)
    except requests.RequestException as e:
        return _result("Brevo", False, m, [], f"Network error: {e}")
    if r.status_code == 401:
        return _result("Brevo", False, m, ["Status: Invalid API key (401)"], "Use an API key from Brevo → SMTP & API → API Keys (starts with xkeysib-).")
    if not r.ok:
        return _result("Brevo", False, m, [f"HTTP {r.status_code}"], (r.text or "")[:200])

    j = r.json() if r.text else {}
    lines = []
    if j.get("email"):
        lines.append(f"Account email: {j['email']}")
    plans = j.get("plan") or []
    for p in plans:
        ptype = p.get("type", "?")
        ctype = p.get("creditsType", "")
        credits = p.get("credits")
        label = f"Plan: {ptype}"
        if ctype:
            label += f" ({ctype})"
        lines.append(label)
        if credits is not None:
            lines.append(f"Credits remaining: {credits}")
    if j.get("relay") and isinstance(j["relay"], dict) and j["relay"].get("enabled") is not None:
        lines.append(f"SMTP relay enabled: {j['relay']['enabled']}")
    if not lines:
        lines.append("Account endpoint OK")
    return _result("Brevo", True, m, lines)


# ---------------------------------------------------------------- AWS SES
# Implemented with plain SigV4-signed HTTPS calls (no AWS SDK) to keep the
# bot image small enough for tiny free hosts (128 MB RAM).
def _ses_call(ak: str, sk: str, region: str, action: str, extra: str = ""):
    """POST one SES Query API action. Return (status_code, xml_root_or_none, raw_text)."""
    host = f"email.{region}.amazonaws.com"
    body = f"Action={action}&Version=2010-12-01" + (f"&{extra}" if extra else "")
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body.encode()).hexdigest()
    canonical_headers = f"content-type:application/x-www-form-urlencoded\nhost:{host}\nx-amz-date:{amz_date}\n"
    signed_headers = "content-type;host;x-amz-date"
    canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    scope = f"{date_stamp}/{region}/ses/aws4_request"
    string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k_signing = _sign(_sign(_sign(_sign(("AWS4" + sk).encode(), date_stamp), region), "ses"), "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Amz-Date": amz_date,
        "Authorization": f"AWS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={signed_headers}, Signature={signature}",
    }
    r = requests.post(f"https://{host}/", data=body, headers=headers, timeout=TIMEOUT)
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        root = None
    return r.status_code, root, r.text or ""


def _xml_text(root, tag: str):
    if root is None:
        return None
    for el in root.iter():
        if el.tag.endswith("}" + tag) or el.tag == tag:
            return (el.text or "").strip()
    return None


def check_ses(access_key: str, secret_key: str, region: str = "ap-south-1") -> dict:
    ak = (access_key or "").strip()
    sk = (secret_key or "").strip()
    region = (region or "ap-south-1").strip() or "ap-south-1"
    m = mask(ak)
    if not ak or not sk:
        return _result("AWS SES", False, m, [], "AWS SES needs BOTH the Access Key ID and the Secret Access Key.")
    try:
        status, root, raw = _ses_call(ak, sk, region, "GetSendQuota")
    except requests.RequestException as e:
        return _result("AWS SES", False, m, [f"Region checked: {region}"], f"Network error: {e}"[:250])

    if status != 200:
        code = _xml_text(root, "Code") or f"HTTP {status}"
        msg = _xml_text(root, "Message") or raw[:200]
        if code in ("InvalidClientTokenId", "SignatureDoesNotMatch", "AuthFailure"):
            return _result("AWS SES", False, m, [f"Status: Invalid credentials ({code})", f"Region checked: {region}"], msg[:200])
        return _result("AWS SES", False, m, [f"AWS error: {code}", f"Region checked: {region}"], msg[:200])

    max24 = _xml_text(root, "Max24HourSend")
    rate = _xml_text(root, "MaxSendRate")
    sent = _xml_text(root, "SentLast24Hours")
    lines = [f"Region: {region}"]
    if max24 is not None:
        lines.append(f"Max per 24h: {int(float(max24)) if float(max24).is_integer() else max24}")
    if sent is not None:
        lines.append(f"Sent last 24h: {int(float(sent)) if float(sent).is_integer() else sent}")
    if max24 is not None and sent is not None:
        try:
            lines.append(f"Remaining (24h): {int(float(max24) - float(sent))}")
        except Exception:
            pass
    if rate is not None:
        lines.append(f"Max send rate: {rate}/sec")
    if max24 is not None and float(max24) <= 200:
        lines.append("Note: looks like SANDBOX (≤200/day) — production access not granted yet")
    try:
        s2, root2, _ = _ses_call(ak, sk, region, "ListIdentities", "MaxItems=10")
        if s2 == 200 and root2 is not None:
            idents = [(el.text or "").strip() for el in root2.iter() if (el.tag.endswith("}member") or el.tag == "member")]
            lines.append(f"Verified identities (first 10): {len(idents)}")
            for x in idents[:5]:
                lines.append(f"• {x}")
    except Exception:
        pass
    return _result("AWS SES", True, m, lines)


# ---------------------------------------------------------------- SMTP
def check_smtp(host: str, port: int, username: str, password: str) -> dict:
    host = (host or "").strip()
    user = (username or "").strip()
    pw = password or ""
    m = f"{user}@{host}:{port}" if user and host else mask(user)
    if not host or not user or not pw:
        return _result("SMTP", False, m, [], "SMTP needs host, port, username and password.")
    try:
        port = int(port)
    except Exception:
        return _result("SMTP", False, m, [], "Port must be a number (587, 465, 25...).")

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT)
    except Exception as e:
        return _result("SMTP", False, m, [f"Host: {host}:{port}"], f"Cannot connect: {e}"[:250])

    try:
        code, banner = server.ehlo()
        banner_s = banner.decode(errors="ignore") if isinstance(banner, bytes) else str(banner)
        caps = sorted(server.esmtp_features.keys()) if hasattr(server, "esmtp_features") else []
        tls_used = port == 465
        if port != 465 and server.has_extn("starttls"):
            server.starttls(context=ctx)
            server.ehlo()
            caps = sorted(server.esmtp_features.keys())
            tls_used = True
        auth_methods = server.esmtp_features.get("auth", "") if hasattr(server, "esmtp_features") else ""
        server.login(user, pw)
        lines = [
            f"Host: {host}:{port}",
            f"Banner: {banner_s.strip()[:90]}",
            f"TLS: {'yes' if tls_used else 'no'}",
        ]
        if auth_methods:
            lines.append(f"AUTH methods: {auth_methods}")
        if caps:
            lines.append(f"Capabilities: {', '.join(caps[:10])}")
        lines.append("Login: OK (no email was sent)")
        try:
            server.quit()
        except Exception:
            pass
        return _result("SMTP", True, m, lines)
    except smtplib.SMTPAuthenticationError as e:
        try:
            server.quit()
        except Exception:
            pass
        return _result("SMTP", False, m, [f"Host: {host}:{port}", "Login: rejected"], f"SMTP auth failed ({e.smtp_code}): {e.smtp_error.decode(errors='ignore') if isinstance(e.smtp_error, bytes) else e.smtp_error}"[:250])
    except Exception as e:
        try:
            server.quit()
        except Exception:
            pass
        return _result("SMTP", False, m, [f"Host: {host}:{port}"], f"Error: {e}"[:250])


def parse_smtp_line(text: str):
    """Parse host:port:user:pass (also | or ; separators). Password may contain : — split only first 3 separators."""
    t = (text or "").strip()
    for sep in ("|", ";"):
        if sep in t:
            parts = t.split(sep)
            if len(parts) >= 4:
                return parts[0].strip(), parts[1].strip(), parts[2].strip(), sep.join(parts[3:]).strip()
    parts = t.split(":", 3)
    if len(parts) == 4:
        return parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
    return None
