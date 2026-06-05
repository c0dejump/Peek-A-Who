"""
Instagram account lookup by username (obfuscated email + phone).

Given a username, queries Instagram's private user lookup endpoint to retrieve
the obfuscated email and phone number associated with that Instagram account.
No authentication required. May be rate-limited (HTTP 429) after repeated calls.

Usage:
    python -m skills.social_media.ig_lookup johndoe
    python -m skills.social_media.ig_lookup johndoe --phone +33612345678

Returns JSON:
    {
        "status":           "found" | "not_found" | "rate_limited" | "error",
        "username":         "johndoe",
        "obfuscated_email": "j***@g***.com",
        "obfuscated_phone": "+33 ** ** ** 78",
        "phone_match":      true | false,   # present if --phone given
    }

Technique: POST i.instagram.com/api/v1/users/lookup/ with q=<username>.
Based on original technique from: PAW / FuckFacebook OSINT tools.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

warnings.filterwarnings("ignore", message="Unverified HTTPS")


def run_sync(username: str, phone: str = "") -> dict:
    """Synchronous wrapper — usable without asyncio."""
    import requests

    url = "https://i.instagram.com/api/v1/users/lookup/"
    headers = {
        "User-Agent":   "Instagram 101.0.0.15.120",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    signed_body = (
        f'.[{{"login_attempt_count":"0","directly_sign_in":"true",'
        f'"source":"default","q":"{username}","ig_sig_key_version":"4"}}]'
    )
    data = {"ig_sig_key_version": "4", "signed_body": signed_body}

    try:
        r = requests.post(url, headers=headers, data=data, verify=False, timeout=20)
        if r.status_code == 200:
            res = r.json()
            obfu_email = res.get("obfuscated_email", "")
            obfu_phone = res.get("obfuscated_phone", "")

            phone_match = False
            if phone and obfu_phone:
                cp = phone.lstrip("+")
                co = obfu_phone.lstrip("+")
                if (len(cp) >= 3 and len(co) >= 3
                        and cp[1:3] == co[1:3] and cp[-2:] == co[-2:]):
                    phone_match = True

            return {
                "status":           "found",
                "username":         username,
                "obfuscated_email": obfu_email,
                "obfuscated_phone": obfu_phone,
                **({"phone_match": phone_match} if phone else {}),
            }
        elif r.status_code == 429:
            return {"status": "rate_limited", "username": username}
        elif r.status_code == 400:
            return {"status": "not_found", "username": username}
        else:
            return {"status": f"http_{r.status_code}", "username": username}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "username": username}


async def run(username: str, phone: str = "") -> dict:
    """Async wrapper — called by agent.py."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_sync, username, phone)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Instagram account lookup by username (obfuscated email + phone)"
    )
    parser.add_argument("username", help="Instagram username to look up")
    parser.add_argument("--phone", default="", help="Known phone number for partial-match check")
    args = parser.parse_args()

    result = asyncio.run(run(args.username, args.phone))
    print(json.dumps(result, ensure_ascii=False, indent=2))
