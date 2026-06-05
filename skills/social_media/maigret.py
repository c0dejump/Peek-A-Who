"""
Maigret cross-platform username scan skill.

Runs maigret (CLI) against one or more usernames and returns categorised results:
location/sport platforms, marketplaces, gaming, social.

Usage:
    python -m skills.social_media.maigret jean.dupont jdupont j.dupont
    python -m skills.social_media.maigret --firstname Jean --lastname Dupont --keywords jd
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


async def run(
    usernames: list[str],
    max_usernames: int = 5,
) -> dict:
    """
    Run maigret on a list of usernames.

    Returns:
        {
            "checked_usernames": [...],
            "total_found": int,
            "found": {site_name: {"url", "username", "tags", "category"}},
            "location_relevant": [...],
            "marketplace": [...],
            "gaming": [...],
            "social": [...],
        }
    """
    from paw_agent.engine.agent import _run_maigret_direct
    return await _run_maigret_direct(usernames[:max_usernames])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Maigret cross-platform username scan")
    parser.add_argument("usernames", nargs="+", help="Username candidates")
    parser.add_argument("--max", type=int, default=5, help="Max usernames to scan")
    args = parser.parse_args()

    result = asyncio.run(run(args.usernames, max_usernames=args.max))
    print(json.dumps(result, ensure_ascii=False, indent=2))
