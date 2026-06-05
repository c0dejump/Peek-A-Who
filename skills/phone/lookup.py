"""
Phone OSINT skill.

Validates a phone number and queries social platform registration via ignorant,
plus generates reverse lookup links.

Usage:
    python -m skills.phone.lookup +33612345678
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


async def run(phone: str) -> dict:
    """
    Analyse a phone number.

    Returns:
        {
            "e164", "valid", "type", "carrier", "region", "country_code",
            "reverse_links", "identity_links", "app_links",
            "ignorant_platforms": [{"site", "status"}, ...]
        }
    """
    from paw_agent.engine.agent import _search_phone_direct
    return await _search_phone_direct(phone)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phone OSINT analysis")
    parser.add_argument("phone", help="Phone number in E.164 format (e.g. +33612345678)")
    args = parser.parse_args()

    result = asyncio.run(run(args.phone))
    print(json.dumps(result, ensure_ascii=False, indent=2))
