"""
HaveIBeenPwned (HIBP) breach lookup skill.

Checks whether an email address appears in any known data breach.
Requires HIBP_API_KEY environment variable (https://haveibeenpwned.com/API/Key).

Usage:
    python -m skills.email.hibp jean.dupont@example.com

Returns JSON:
    {
        "email":    "jean@example.com",
        "breached": true,
        "count":    3,
        "breaches": [{"name": "LinkedIn", "date": "2012-05-05", "data": ["Emails", "Passwords"]}]
    }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
warnings.filterwarnings("ignore", message="Unverified HTTPS")


def run_sync(email: str) -> dict:
    """
    Check a single email against HIBP v3.
    Returns {"email", "breached", "count", "breaches"} or {"email", "error"}.
    """
    import requests

    api_key = os.environ.get("HIBP_API_KEY", "").strip()
    if not api_key:
        return {
            "email": email,
            "error": "no_api_key",
            "hint": "Add HIBP_API_KEY to .env (https://haveibeenpwned.com/API/Key)",
        }

    time.sleep(random.uniform(1.5, 2.5))
    headers = {
        "User-Agent":   "PAW-OSINT/2.0",
        "hibp-api-key": api_key,
    }

    try:
        url  = f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}?truncateResponse=false"
        resp = requests.get(url, headers=headers, timeout=10, verify=False)

        if resp.status_code == 200:
            breaches = [
                {
                    "name": b["Name"],
                    "date": b.get("BreachDate"),
                    "data": b.get("DataClasses", []),
                }
                for b in resp.json()
            ]
            return {"email": email, "breached": True, "count": len(breaches), "breaches": breaches}

        if resp.status_code == 404:
            return {"email": email, "breached": False, "count": 0}
        if resp.status_code == 401:
            return {
                "email": email,
                "error": "invalid_api_key",
                "hint": "HIBP API key rejected — check HIBP_API_KEY",
            }
        if resp.status_code == 429:
            return {"email": email, "error": "rate_limited"}

        return {"email": email, "error": f"http_{resp.status_code}"}

    except Exception as exc:
        return {"email": email, "error": str(exc)}


async def run(email: str) -> dict:
    """Async wrapper — usable from async pipeline."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_sync, email)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HIBP breach lookup")
    parser.add_argument("email", help="Email address to check")
    args = parser.parse_args()
    print(json.dumps(run_sync(args.email), ensure_ascii=False, indent=2))
