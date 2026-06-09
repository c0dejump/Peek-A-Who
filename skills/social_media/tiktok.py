"""
TikTok username detection skill.

TikTok is a SPA — og:title is not returned server-side. However, the server
always embeds a JSON blob in the page body containing:
    "uniqueId":"username"    ← existence check (absent on 404-style pages)
    "nickname":"Display"     ← display name

Detection: request https://www.tiktok.com/@{username} with a realistic
Chrome UA; check for "uniqueId":"{username}" in the response body.

Usage:
    python -m skills.social_media.tiktok --firstname Jean --lastname Dupont
    python -m skills.social_media.tiktok --pseudo jdupont --birth_year 1990
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _relevance(display_name: str, username: str, fn: str, ln: str, kws: list[str]) -> int:
    dn = display_name.lower() if display_name else ""
    un = username.lower()
    score = 0
    if ln and ln.lower() in dn:
        score += 5
    if fn and fn.lower() in dn:
        score += 4
    for kw in (kws or [])[:4]:
        kl = kw.lower()
        if kl in un:
            score += 3
        elif kl in dn:
            score += 3
    return min(score, 10)


def _check_tiktok(usernames: list[str], firstname: str, lastname: str, keywords: list[str]) -> dict:
    import requests

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": _UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })

    results: dict = {
        "checked": 0,
        "generated": len(usernames),
        "found": [],
        "errors": 0,
        "blocked": False,
    }
    kws = [k.lower() for k in keywords]

    for i, un in enumerate(usernames):
        try:
            r = sess.get(
                f"https://www.tiktok.com/@{un}",
                timeout=12,
                allow_redirects=True,
            )
            results["checked"] += 1

            if r.status_code not in (200, 301, 302):
                # Non-200 on several consecutive checks → rate limit or block
                results["errors"] += 1
                if results["errors"] >= 5:
                    results["blocked"] = True
                    break
                continue

            body = r.text

            # TikTok embeds JSON with uniqueId matching the real account username
            m_id = re.search(r'"uniqueId"\s*:\s*"([^"]+)"', body)
            if not m_id:
                # 200 but no embedded JSON → page not found (SPA 404 equivalent)
                time.sleep(0.15)
                continue

            # uniqueId must match what we queried (case-insensitive)
            found_id = m_id.group(1)
            if found_id.lower() != un.lower():
                time.sleep(0.15)
                continue

            m_nick = re.search(r'"nickname"\s*:\s*"([^"]+)"', body)
            display_name = m_nick.group(1) if m_nick else ""

            rel = _relevance(display_name, un, firstname, lastname, kws)
            results["found"].append({
                "username": un,
                "display_name": display_name,
                "url": f"https://www.tiktok.com/@{un}",
                "relevance": rel,
            })

            # Slightly longer delay after a hit to avoid rate limiting
            time.sleep(0.4)

        except Exception:
            results["errors"] += 1

    return results


async def run(
    firstname: str = "",
    lastname: str = "",
    keywords: list[str] | None = None,
    pseudo: str = "",
    birth_year: str = "",
    cities: list[str] | None = None,
    max_candidates: int = 60,
) -> dict:
    """
    Generate username candidates and check TikTok.

    Returns:
        {
            "checked": int,
            "generated": int,
            "found": [{"username", "display_name", "url", "relevance"}],
            "errors": int,
            "blocked": bool,
        }
    """
    from paw_agent.engine.agent import _generate_ig_usernames

    usernames = _generate_ig_usernames(
        firstname, lastname, birth_year,
        keywords=keywords or [],
        pseudo=pseudo,
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        _check_tiktok,
        usernames[:max_candidates],
        firstname,
        lastname,
        keywords or [],
    )
    result["generated"] = len(usernames)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TikTok username detection")
    parser.add_argument("--firstname",  default="")
    parser.add_argument("--lastname",   default="")
    parser.add_argument("--keywords",   nargs="*", default=[])
    parser.add_argument("--pseudo",     default="")
    parser.add_argument("--birth_year", default="")
    parser.add_argument("--max",        type=int, default=60)
    args = parser.parse_args()

    result = asyncio.run(run(
        firstname=args.firstname,
        lastname=args.lastname,
        keywords=args.keywords,
        pseudo=args.pseudo,
        birth_year=args.birth_year,
        max_candidates=args.max,
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2))
