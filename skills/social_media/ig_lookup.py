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
import re
import sys
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

warnings.filterwarnings("ignore", message="Unverified HTTPS")


# ── Domain resolution table ────────────────────────────────────
# Key: (first_chars_of_domain, total_domain_length, tld) → real domain
# total_domain_length = len(visible_prefix) + star_count
_DOMAIN_TABLE: dict[tuple[str, int, str], str] = {
    # French providers
    ("h", 7,  "fr"):  "hotmail.fr",
    ("h", 7,  "com"): "hotmail.com",
    ("o", 6,  "fr"):  "orange.fr",
    ("o", 7,  "fr"):  "outlook.fr",
    ("o", 7,  "com"): "outlook.com",
    ("f", 4,  "fr"):  "free.fr",
    ("f", 5,  "fr"):  "freed.fr",
    ("y", 5,  "fr"):  "yahoo.fr",
    ("y", 5,  "com"): "yahoo.com",
    ("l", 7,  "net"): "laposte.net",
    ("l", 4,  "fr"):  "live.fr",
    ("l", 4,  "com"): "live.com",
    ("w", 7,  "fr"):  "wanadoo.fr",
    ("b", 4,  "fr"):  "bbox.fr",
    ("s", 3,  "fr"):  "sfr.fr",
    ("n", 9,  "fr"):  "neuf.cegetel.fr",
    ("a", 5,  "fr"):  "alice.fr",
    # International
    ("g", 5,  "com"): "gmail.com",
    ("gm", 5, "com"): "gmail.com",
    ("i", 6,  "com"): "icloud.com",
    ("p", 6,  "com"): "pm.com",
    ("p", 10, "com"): "protonmail.com",
    ("p", 8,  "me"):  "proton.me",
    ("m", 2,  "com"): "me.com",
    ("m", 3,  "com"): "msn.com",
    ("a", 3,  "com"): "aol.com",
    ("z", 6,  "com"): "zoho.com",
    ("t", 12, "com"): "tutanota.com",
    ("m", 4,  "com"): "mx.com",
    ("g", 2,  "com"): "gmx.com",    # g** = gmx (3 chars but Instagram may show g**)
    ("g", 3,  "com"): "gmx.com",    # g*** = gmx.com ambiguous with gmail short prefix
    ("g", 6,  "com"): "gmx.com",
    ("g", 6,  "fr"):  "gmx.fr",
    ("g", 4,  "net"): "gmx.net",
}


def resolve_domain(pattern: dict) -> str | None:
    """
    Try to resolve an obfuscated domain to its real name using the lookup table.
    Returns the full domain string (e.g. "hotmail.fr") or None if unknown.
    """
    prefix = pattern.get("domain_prefix", "")
    stars  = pattern.get("domain_stars", 0)
    tld    = pattern.get("tld", "")
    if not prefix or not tld:
        return None
    total = len(prefix) + stars
    # Try exact prefix first, then single first char
    for key_prefix in (prefix, prefix[0]):
        result = _DOMAIN_TABLE.get((key_prefix, total, tld))
        if result:
            return result
    return None


def parse_obfuscated_email(obfu: str) -> dict:
    """
    Parse Instagram's obfuscated email into matchable components.

    Examples:
      "m***x@h******.fr"  → {local_prefix:"m",  local_suffix:"x",  domain_prefix:"h",  tld:"fr", local_stars:3, domain_stars:6}
      "na***@gm***.com"   → {local_prefix:"na", local_suffix:"",   domain_prefix:"gm", tld:"com", ...}
      "j***@g***.com"     → {local_prefix:"j",  local_suffix:"",   domain_prefix:"g",  tld:"com", ...}
    """
    if not obfu or "@" not in obfu:
        return {}
    local_raw, domain_raw = obfu.split("@", 1)

    def _split_stars(s: str) -> tuple[str, str, int]:
        """Returns (prefix_visible, suffix_visible, star_count)."""
        m = re.match(r'^([^*]*)\*+([^*]*)$', s)
        if m:
            return m.group(1), m.group(2), s.count("*")
        return s, "", 0

    lp, ls, lk = _split_stars(local_raw)

    # Domain may have TLD: "h******.fr" → domain_body="h******", tld="fr"
    if "." in domain_raw:
        dot_idx = domain_raw.rfind(".")
        tld = domain_raw[dot_idx + 1:]
        dom_body = domain_raw[:dot_idx]
    else:
        tld = ""
        dom_body = domain_raw

    dp, ds, dk = _split_stars(dom_body)

    partial = {
        "local_prefix":  lp,
        "local_suffix":  ls,
        "local_stars":   lk,
        "domain_prefix": dp,
        "domain_suffix": ds,
        "domain_stars":  dk,
        "tld":           tld,
        "raw":           obfu,
    }
    partial["resolved_domain"] = resolve_domain(partial)
    return partial


def parse_obfuscated_phone(obfu: str) -> dict:
    """
    Parse Instagram's obfuscated phone into matchable components.

    Examples:
      "+33 * ** ** ** 72"  → {country_code:"+33", last_digits:"72", visible:["33","72"]}
      "+33 6 ** ** ** 34"  → {country_code:"+33", first_digit:"6", last_digits:"34"}
    """
    if not obfu:
        return {}
    clean = re.sub(r"\s+", "", obfu)   # "+33****72"
    # Extract country code: leading + then digits before first *
    cc_m = re.match(r'^(\+\d+)\*', clean)
    country_code = cc_m.group(1) if cc_m else ""

    # All contiguous digit groups (skip * and +)
    digit_groups = re.findall(r'\d+', clean)
    # Last group at end of string
    last_digits = ""
    suffix_m = re.search(r'\d+$', clean)
    if suffix_m:
        last_digits = suffix_m.group(0)

    # First digit after country code (if visible before first *)
    first_digit = ""
    after_cc = clean[len(country_code):]
    fd_m = re.match(r'(\d+)\*', after_cc)
    if fd_m:
        first_digit = fd_m.group(1)

    return {
        "country_code": country_code,
        "first_digit":  first_digit,
        "last_digits":  last_digits,
        "raw":          obfu,
    }


def match_email(candidate: str, pattern: dict) -> tuple[bool, list[str]]:
    """
    Check if an email candidate matches the Instagram obfuscated pattern.
    Returns (matches, list_of_reasons).
    """
    if not pattern or not candidate or "@" not in candidate:
        return False, []
    local, domain = candidate.lower().split("@", 1)
    reasons: list[str] = []
    ok = True

    if pattern.get("local_prefix") and not local.startswith(pattern["local_prefix"].lower()):
        ok = False
    elif pattern.get("local_prefix"):
        reasons.append(f"starts with '{pattern['local_prefix']}'")

    if pattern.get("local_suffix") and not local.endswith(pattern["local_suffix"].lower()):
        ok = False
    elif pattern.get("local_suffix"):
        reasons.append(f"ends with '{pattern['local_suffix']}'")

    tld = pattern.get("tld", "")
    if tld and not domain.endswith("." + tld.lower()) and domain != tld.lower():
        ok = False
    elif tld:
        reasons.append(f"TLD .{tld}")

    dom_prefix = pattern.get("domain_prefix", "")
    if dom_prefix:
        dom_body = domain.split(".")[0]
        if not dom_body.startswith(dom_prefix.lower()):
            ok = False
        else:
            reasons.append(f"domain starts with '{dom_prefix}'")

    return ok, reasons


def match_phone(candidate: str, pattern: dict) -> tuple[bool, list[str]]:
    """
    Check if a phone candidate matches the Instagram obfuscated pattern.
    """
    if not pattern or not candidate:
        return False, []
    digits = re.sub(r"\D", "", candidate)
    reasons: list[str] = []
    ok = True

    if pattern.get("last_digits"):
        if not digits.endswith(pattern["last_digits"]):
            ok = False
        else:
            reasons.append(f"ends in {pattern['last_digits']}")

    if pattern.get("country_code"):
        cc_digits = re.sub(r"\D", "", pattern["country_code"])
        if not digits.startswith(cc_digits):
            ok = False
        else:
            reasons.append(f"country code {pattern['country_code']}")

    return ok, reasons


def scan_report_for_emails(report: dict, email_patterns: list[dict]) -> list[dict]:
    """
    Scan all investigation data for email addresses matching the obfuscated patterns.
    Returns list of {email, source, reasons} for each match found.
    """
    if not email_patterns:
        return []

    _EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    found: list[dict] = []
    seen: set[str] = set()

    def _check(text: str, source: str) -> None:
        for m in _EMAIL_RE.finditer(str(text)):
            email = m.group(0).lower()
            if email in seen:
                continue
            for pat in email_patterns:
                ok, reasons = match_email(email, pat)
                if ok:
                    seen.add(email)
                    found.append({"email": email, "source": source, "reasons": reasons, "pattern": pat["raw"]})

    # HIBP breaches
    for h in report.get("hibp", []):
        _check(h.get("email", ""), "HIBP")

    # GitHub
    gh = report.get("github", {})
    _check(gh.get("email", ""), "GitHub profile")
    for repo in gh.get("repos", []):
        _check(repo.get("email", ""), "GitHub repo")

    # Reddit
    for post in report.get("reddit", {}).get("posts", []):
        _check(post.get("text", ""), "Reddit")

    # Maigret / social profiles — description/bio fields
    for cat in ("social", "location_relevant", "marketplace", "gaming"):
        for p in report.get("social_media", {}).get("maigret", {}).get(cat, []):
            _check(p.get("url", ""), f"maigret/{p.get('site','')}")

    # Enriched Instagram bios
    for ig_p in report.get("social_media", {}).get("instagram", {}).get("found", []):
        _check(ig_p.get("bio", ""), f"Instagram @{ig_p.get('username','')}")
        _check(ig_p.get("external_url", ""), f"Instagram @{ig_p.get('username','')} link")

    # LinkedIn SERP snippets
    for li in report.get("social_media", {}).get("linkedin", {}).get("serp_found", []):
        _check(li.get("snippet", ""), "LinkedIn SERP")

    # Annuaires / phone OSINT raw text
    _check(str(report.get("phone", {})), "phone OSINT")

    # Free-text anywhere in findings
    for fnd in report.get("findings", {}).values():
        _check(str(fnd.get("value", "")), f"finding/{fnd.get('type','')}")

    return found


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
