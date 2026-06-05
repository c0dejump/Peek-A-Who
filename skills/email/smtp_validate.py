"""
SMTP email validation skill.

Validates email addresses using MX checks + SMTP probe via isitarealemail.com.
Consumer domains (Gmail, Outlook, Yahoo…) are immediately marked unverifiable
since they block SMTP enumeration — use HIBP for those instead.

Usage:
    python -m skills.email.smtp_validate jean.dupont@example.com
    python -m skills.email.smtp_validate --batch jean@a.com,paul@b.com

Returns JSON:
    {
        "email":       "jean@example.com",
        "valid":       true | false | null,   # null = unverifiable (big provider)
        "domain_type": "custom" | "unverifiable"
    }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
warnings.filterwarnings("ignore", message="Unverified HTTPS")

# ── Domain classifications ─────────────────────────────────────

_GMAIL      = {"gmail.com", "googlemail.com"}
_MICROSOFT  = {"outlook.com", "hotmail.com", "hotmail.fr", "live.com",
               "live.fr", "msn.com", "outlook.fr"}
_YAHOO      = {"yahoo.com", "yahoo.fr", "yahoo.co.uk", "ymail.com",
               "yahoo.es", "yahoo.de", "yahoo.it"}
_UNVERIFIABLE = (
    _GMAIL | _MICROSOFT | _YAHOO |
    {"protonmail.com", "pm.me", "icloud.com", "me.com",
     "laposte.net", "orange.fr", "sfr.fr", "free.fr"}
)


def _check_smtp(email: str) -> bool | None:
    """SMTP probe via isitarealemail — reliable only on custom/corporate domains."""
    import requests
    try:
        r = requests.get(
            "https://isitarealemail.com/api/email/validate",
            params={"email": email},
            timeout=8,
        )
        return r.json().get("status") == "valid"
    except Exception:
        return None


def run_sync(email: str) -> dict:
    """
    Validate a single email address.
    Returns {"email", "valid": True/False/None, "domain_type"}.
    valid=None means the domain blocks SMTP probing — check HIBP instead.
    """
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain in _UNVERIFIABLE:
        return {"email": email, "valid": None, "domain_type": "unverifiable"}
    time.sleep(0.8)
    valid = _check_smtp(email)
    return {"email": email, "valid": valid, "domain_type": "custom"}


def validate_batch(emails: list[str], max_results: int = 20) -> dict:
    """
    Validate an explicit list of email addresses.
    Returns categorised results: valid, unverifiable, invalid.
    """
    valid, unverifiable, invalid = [], [], []
    for email in emails[:max_results]:
        r = run_sync(email)
        if r["valid"] is True:
            valid.append(email)
        elif r["valid"] is None:
            unverifiable.append(email)
        else:
            invalid.append(email)
    return {
        "valid":              valid,
        "unverifiable":       unverifiable,
        "invalid":            invalid,
        "valid_count":        len(valid),
        "unverifiable_count": len(unverifiable),
        "invalid_count":      len(invalid),
    }


def validate_all(candidates: list[str]) -> dict:
    """
    Validate all candidates sequentially (no session overhead).
    Returns {"checked", "valid", "valid_count"}.
    """
    valid: list[str] = []
    for email in candidates:
        r = run_sync(email)
        if r["valid"] is True:
            valid.append(email)
    return {"checked": len(candidates), "valid": valid, "valid_count": len(valid)}


async def run(email: str) -> dict:
    """Async wrapper — usable from async pipeline."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_sync, email)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SMTP email validation")
    parser.add_argument("email", nargs="?", help="Single email to validate")
    parser.add_argument("--batch", help="Comma-separated list of emails")
    args = parser.parse_args()

    if args.batch:
        emails = [e.strip() for e in args.batch.split(",") if e.strip()]
        print(json.dumps(validate_batch(emails), ensure_ascii=False, indent=2))
    elif args.email:
        print(json.dumps(run_sync(args.email), ensure_ascii=False, indent=2))
    else:
        parser.print_help()
