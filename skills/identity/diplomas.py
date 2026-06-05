"""
Diplomas / academic records skill.

Searches theses.fr, HAL.science, and linternaute bac/brevet results for an individual.
Requires both firstname AND lastname for precision.

Usage:
    python -m skills.identity.diplomas --firstname Jean --lastname Dupont --birth_year 1990
    python -m skills.identity.diplomas --firstname Jean --lastname Dupont --city Paris Lyon
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


async def run(
    firstname: str,
    lastname: str,
    cities: list[str] | None = None,
    birth_year: str = "",
) -> dict:
    """
    Search academic records for firstname + lastname.

    Returns:
        {
            "total_theses": int,
            "total_pubs": int,
            "theses": [{"title", "year", "institution", "url"}],
            "publications": [{"title", "year", "url"}],
            "bac_results": [{"name", "diploma", "year", "age_at_bac"}],
            "brevet_results": [{"name", "year", "age_at_brevet"}],
        }
    """
    from paw_agent.engine.agent import _search_diplomas_direct
    return await _search_diplomas_direct(firstname, lastname, cities or [], birth_year)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Academic records lookup")
    parser.add_argument("--firstname",  required=True)
    parser.add_argument("--lastname",   required=True)
    parser.add_argument("--birth_year", default="")
    parser.add_argument("--city",       nargs="*", default=[], dest="cities")
    args = parser.parse_args()

    result = asyncio.run(run(args.firstname, args.lastname, args.cities, args.birth_year))
    print(json.dumps(result, ensure_ascii=False, indent=2))
