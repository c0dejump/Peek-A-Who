"""
Multi-platform social media detection skill.

Checks username candidates across Twitter/X, TikTok, Snapchat, Telegram,
LinkedIn, and BeReal in parallel using title-pattern matching.

Usage:
    python -m skills.social_media.platforms --firstname Jean --lastname Dupont --keywords jd
    python -m skills.social_media.platforms --candidates jean.dupont jdupont j.dupont
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
    candidates: list[str] | None = None,
    max_candidates: int = 10,
) -> dict:
    """
    Run multi-platform detection.

    Returns:
        {
            "twitter":  {"label", "found": [...], "checked": int},
            "tiktok":   {...},
            "snapchat": {...},
            "telegram": {...},
            "linkedin": {...},
            "bereal":   {...},
            "facebook": {"label", "search_url": str},
        }
    """
    from paw_agent.engine.agent import _generate_ig_usernames, _search_social_platforms_direct

    if candidates:
        usernames = candidates
    else:
        usernames = _generate_ig_usernames(
            firstname, lastname, birth_year,
            keywords=keywords or [],
            pseudo=pseudo,
        )

    return await _search_social_platforms_direct(
        usernames[:max_candidates],
        firstname=firstname,
        lastname=lastname,
        keywords=keywords or [],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-platform social media detection")
    parser.add_argument("--firstname",   default="")
    parser.add_argument("--lastname",    default="")
    parser.add_argument("--keywords",    nargs="*", default=[])
    parser.add_argument("--pseudo",      default="")
    parser.add_argument("--birth_year",  default="")
    parser.add_argument("--candidates",  nargs="*", default=[], help="Explicit username list")
    parser.add_argument("--max",         type=int, default=10)
    args = parser.parse_args()

    result = asyncio.run(run(
        firstname=args.firstname,
        lastname=args.lastname,
        keywords=args.keywords,
        pseudo=args.pseudo,
        birth_year=args.birth_year,
        candidates=args.candidates or None,
        max_candidates=args.max,
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2))
