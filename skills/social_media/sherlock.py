"""
Sherlock cross-platform username scan skill.

Runs sherlock (CLI) against one or more usernames and returns categorised results:
location/sport platforms, marketplaces, gaming, social.

Requirements:
    pip install sherlock-project
    or: pip install sherlock  (older package)

Usage:
    python -m skills.social_media.sherlock jean.dupont jdupont
    python -m skills.social_media.sherlock --max 3 jean.dupont jdupont j.dupont
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


async def run(usernames: list[str]) -> dict:
    """
    Run sherlock on a list of usernames.

    Returns:
        {
            "checked_usernames": [...],
            "total_found": int,
            "found": {username: [{"site", "url", "tags", "category"}, ...]},
            "location_relevant": [...],
            "marketplace": [...],
            "gaming": [...],
            "social": [...],
            "not_installed": bool,
        }
    """
    from paw_agent.engine.agent import _run_sherlock_direct
    return await _run_sherlock_direct(usernames)


def run_sync(usernames: list[str]) -> dict:
    return asyncio.run(run(usernames))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sherlock cross-platform username scan")
    parser.add_argument("usernames", nargs="+", help="Username candidates")
    args = parser.parse_args()

    result = asyncio.run(run(args.usernames))
    print(json.dumps(result, ensure_ascii=False, indent=2))
