"""
Instagram username detection skill.

Checks username candidates against Instagram using the facebookexternalhit/1.1
User-Agent, which causes Instagram to return og:title with profile data even
behind its login wall (Meta whitelists this UA for link-preview crawlers).

Usage:
    python -m skills.social_media.instagram --firstname Jean --lastname Dupont --keywords jd
    python -m skills.social_media.instagram --pseudo jean.dupont --birth_year 1990
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


async def run(
    firstname: str = "",
    lastname: str = "",
    keywords: list[str] | None = None,
    pseudo: str = "",
    birth_year: str = "",
    cities: list[str] | None = None,
    max_candidates: int = 80,
) -> dict:
    """
    Generate username candidates and check Instagram.

    Returns:
        {
            "checked": int,
            "generated": int,
            "found": [{"username", "display_name", "url", "relevance", "first_seen"}],
            "blocked": bool,
            "errors": int,
        }
    """
    from paw_agent.engine.agent import _generate_ig_usernames, _search_instagram_direct

    usernames = _generate_ig_usernames(
        firstname, lastname, birth_year,
        keywords=keywords or [],
        pseudo=pseudo,
    )

    result = await _search_instagram_direct(
        usernames[:max_candidates],
        firstname=firstname,
        lastname=lastname,
        keywords=keywords or [],
    )
    result["generated"] = len(usernames)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram username detection")
    parser.add_argument("--firstname",   default="")
    parser.add_argument("--lastname",    default="")
    parser.add_argument("--keywords",    nargs="*", default=[])
    parser.add_argument("--pseudo",      default="")
    parser.add_argument("--birth_year",  default="")
    parser.add_argument("--max",         type=int, default=80)
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
