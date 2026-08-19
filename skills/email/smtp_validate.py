"""
SMTP email validation skill — powered by check-if-email-exists (Reacher).

Self-hosted backend (Docker required):
    docker run -p 8080:8080 reacherhq/backend:latest

Then set in .env:
    REACHER_URL=http://localhost:8080

Without Docker, falls back to basic MX-only check.

https://github.com/reacherhq/check-if-email-exists
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

_REACHER_URL = os.environ.get("REACHER_URL", "http://localhost:8080").rstrip("/")

# ── is_reachable verdict mapping ───────────────────────────────
# "safe"    → confirmed deliverable
# "risky"   → catch-all or disposable — exists but uncertain
# "invalid" → definitely doesn't exist
# "unknown" → couldn't verify (port 25 blocked, timeout, etc.)
_REACHABLE_VALID     = {"safe"}
_REACHABLE_RISKY     = {"risky"}
_REACHABLE_INVALID   = {"invalid"}
# "unknown" → treated as unverifiable


def _check_reacher_available() -> bool:
    """Quick ping to see if the Reacher Docker container is running."""
    import requests
    try:
        r = requests.get(f"{_REACHER_URL}/health", timeout=2)
        return r.status_code in (200, 404)  # 404 = server running, route just doesn't exist
    except Exception:
        return False


def _check_reacher(email: str) -> dict:
    """
    Call the Reacher /v0/check_email endpoint.
    Returns the raw Reacher JSON dict.
    Raises requests.exceptions.RequestException on failure.
    """
    import requests
    resp = requests.post(
        f"{_REACHER_URL}/v0/check_email",
        json={"to_email": email},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_reacher(data: dict, email: str) -> dict:
    """
    Convert Reacher response into PAW's standard email result format.
    Returns:
        {
            "email":         str,
            "valid":         True | False | None,   # None = unverifiable
            "reachable":     "safe" | "risky" | "invalid" | "unknown",
            "is_catch_all":  bool,
            "is_disposable": bool,
            "is_role":       bool,
            "mx_records":    list[str],
            "smtp_details":  dict,
            "domain_type":   "reacher",
            "source":        "reacher",
        }
    """
    reachable    = data.get("is_reachable", "unknown")
    smtp         = data.get("smtp", {})
    mx           = data.get("mx", {})
    misc         = data.get("misc", {})

    is_catch_all  = smtp.get("is_catch_all", False)
    is_disposable = misc.get("is_disposable", False)
    is_role       = misc.get("is_role_account", False)

    if reachable in _REACHABLE_VALID:
        valid = True
    elif reachable in _REACHABLE_INVALID:
        valid = False
    else:
        valid = None   # risky or unknown → unverifiable

    return {
        "email":         email,
        "valid":         valid,
        "reachable":     reachable,
        "is_catch_all":  is_catch_all,
        "is_disposable": is_disposable,
        "is_role":       is_role,
        "mx_records":    mx.get("records", []),
        "smtp_details":  {
            "can_connect":    smtp.get("can_connect_smtp"),
            "is_deliverable": smtp.get("is_deliverable"),
            "is_disabled":    smtp.get("is_disabled"),
            "has_full_inbox": smtp.get("has_full_inbox"),
        },
        "domain_type":   "reacher",
        "source":        "reacher",
    }


def _check_mx_only(email: str) -> dict:
    """
    Fallback when Reacher is unavailable: check DNS MX records only.
    Cannot verify actual deliverability — marks as unverifiable.
    """
    import socket
    domain = email.split("@")[-1].lower() if "@" in email else ""
    has_mx = False
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX")
        has_mx = len(answers) > 0
    except Exception:
        try:
            socket.getaddrinfo(domain, None)
            has_mx = True
        except Exception:
            has_mx = False

    return {
        "email":         email,
        "valid":         None if has_mx else False,
        "reachable":     "unknown",
        "is_catch_all":  False,
        "is_disposable": False,
        "is_role":       False,
        "mx_records":    [],
        "smtp_details":  {},
        "domain_type":   "mx_only",
        "source":        "fallback",
    }


_reacher_available: bool | None = None   # cached after first check


def _check_serp_hit(email: str) -> dict:
    """
    Search DuckDuckGo for the email address in quotes.
    If results appear the email has been published somewhere → likely real.
    Returns {"hit": bool, "count": int}
    """
    try:
        from skills.utils.search import web_search

        res = web_search(f'"{email}"', num_results=10, region="us-en")
        results = res.get("results", [])
        if not results:
            return {"hit": False, "count": 0}
        return {"hit": True, "count": len(results)}
    except Exception:
        return {"hit": False, "count": 0}


def run_sync(email: str) -> dict:
    """
    Validate a single email — MX check or Reacher.
    SERP enrichment is NOT done here (too slow for bulk); call validate_all()
    which applies SERP only to the surviving shortlist.
    """
    global _reacher_available

    if _reacher_available is None:
        _reacher_available = _check_reacher_available()

    email = email.strip().lower()

    if _reacher_available:
        try:
            data = _check_reacher(email)
            result = _parse_reacher(data, email)
        except Exception:
            _reacher_available = False
            result = _check_mx_only(email)
    else:
        result = _check_mx_only(email)

    result["serp_hit"]   = False
    result["serp_count"] = 0
    result["serp_likely"] = False
    return result


# Maximum candidates to run MX/SMTP checks against
_MAX_VALIDATE = 80
# Maximum survivors (valid + risky + unverifiable) to enrich with SERP
_MAX_SERP     = 20


def validate_batch(emails: list[str], max_results: int = 20) -> dict:
    """
    Validate a list of emails with MX or Reacher.
    Sleep between calls only when Reacher is active (SMTP rate limiting).
    """
    valid: list[str]        = []
    risky: list[str]        = []
    unverifiable: list[str] = []
    invalid: list[str]      = []
    details: list[dict]     = []

    for email in emails[:max_results]:
        r = run_sync(email)
        details.append(r)
        if r["valid"] is True:
            valid.append(email)
        elif r["valid"] is False:
            invalid.append(email)
        elif r.get("reachable") == "risky":
            risky.append(email)
        else:
            unverifiable.append(email)
        if _reacher_available:
            time.sleep(0.3)   # pace only when hitting real SMTP servers

    return {
        "valid":              valid,
        "risky":              risky,
        "unverifiable":       unverifiable,
        "invalid":            invalid,
        "details":            details,
        "valid_count":        len(valid),
        "risky_count":        len(risky),
        "unverifiable_count": len(unverifiable),
        "invalid_count":      len(invalid),
        "source":             "reacher" if _reacher_available else "fallback",
    }


def validate_all(candidates: list[str]) -> dict:
    """
    Pipeline entry-point. Caps bulk check at _MAX_VALIDATE, then runs
    SERP enrichment on the top _MAX_SERP survivors (valid + risky + unverifiable).
    """
    capped = candidates[:_MAX_VALIDATE]
    result = validate_batch(capped, max_results=len(capped))

    # SERP enrichment — only on non-invalid survivors, capped to avoid rate-limits
    survivors = result["valid"] + result["risky"] + result["unverifiable"]
    serp_targets = set(survivors[:_MAX_SERP])
    for det in result["details"]:
        if det["email"] not in serp_targets:
            continue
        serp = _check_serp_hit(det["email"])
        det["serp_hit"]    = serp["hit"]
        det["serp_count"]  = serp["count"]
        det["serp_likely"] = (det["valid"] is None and serp["hit"])
        if _reacher_available:
            time.sleep(0.2)

    # "valid" for pipeline = confirmed safe; pass risky as unverifiable
    return {
        "checked":      len(capped),
        "total":        len(candidates),
        "valid":        result["valid"],
        "risky":        result["risky"],
        "unverifiable": result["unverifiable"] + result["risky"],
        "invalid":      result["invalid"],
        "valid_count":  result["valid_count"],
        "details":      result["details"],
        "source":       result["source"],
    }


async def run(email: str) -> dict:
    """Async wrapper — usable from async pipeline."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_sync, email)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Email validation via Reacher")
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
