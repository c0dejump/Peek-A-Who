"""
Telegram OSINT — public profile lookup from a @username, no API key needed.

Scrapes the public t.me/<username> preview page for the display name, bio,
profile photo and account type (user / channel / group). For channels/groups it
also grabs the subscriber/member count. This is enough to confirm an account
exists and pull its public metadata; deep data (last seen, phone) would need a
logged-in Telethon session (TELEGRAM_API_ID/HASH already reserved in config).
"""
from __future__ import annotations

import re

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _meta(html: str, prop: str) -> str:
    m = re.search(rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)["\']', html, re.I)
    if not m:
        m = re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']{re.escape(prop)}["\']', html, re.I)
    return m.group(1).strip() if m else ""


def _cls(html: str, cls: str) -> str:
    m = re.search(rf'<[^>]+class=["\'][^"\']*{re.escape(cls)}[^"\']*["\'][^>]*>(.*?)</', html, re.S)
    return re.sub(r"<[^>]+>", " ", m.group(1)).strip() if m else ""


def run_sync(username: str, timeout: int = 12) -> dict:
    username = (username or "").strip().lstrip("@")
    if not username:
        return {"error": "No username."}
    url = f"https://t.me/{username}"
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "en"}, timeout=timeout)
    except Exception as exc:
        return {"username": username, "url": url, "error": str(exc)}

    if r.status_code != 200:
        return {"username": username, "url": url, "exists": False,
                "note": f"t.me returned HTTP {r.status_code}"}

    html = r.text
    title = _meta(html, "og:title")
    photo = _meta(html, "og:image")
    page_title = _cls(html, "tgme_page_title")

    # A non-existent handle shows the generic Telegram landing (no tgme_page_title)
    exists = bool(page_title)

    # Type + counts
    extra = _cls(html, "tgme_page_extra")          # e.g. "12 345 subscribers" / "@username"
    ptype = "user"
    low = (extra + " " + html[:2000]).lower()
    if "subscriber" in low:
        ptype = "channel"
    elif "member" in low:
        ptype = "group"
    subs = ""
    mcount = re.search(r"([\d\s.,]+)\s+(subscribers|members)", extra, re.I) or \
             re.search(r"([\d\s.,]+)\s+(subscribers|members)", html, re.I)
    if mcount:
        subs = mcount.group(1).strip()

    return {
        "username":   username,
        "url":        url,
        "exists":     exists,
        "name":       page_title or (title if title and title.lower() != "telegram" else ""),
        "bio":        _meta(html, "og:description"),
        "photo":      photo if photo and "t.me" not in photo else photo,
        "type":       ptype,
        "subscribers": subs,
        "note":       "" if exists else "No public Telegram profile found for this username (or it's private).",
    }
