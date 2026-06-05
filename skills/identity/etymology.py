"""
French surname etymology & demographic distribution skill.

Scrapes filae.com to retrieve:
- Total bearers since 1890, number of departments
- National rank among most common surnames
- Birth count by 25-year periods (1890–1990)
- Top 15 French departments by bearer count

If birth_year is provided, highlights the bearer density for that generation,
giving context on rarity and likely geographic region.

Usage:
    python -m skills.identity.etymology Dupont
    python -m skills.identity.etymology Dupont --birth-year 1990

Returns JSON:
    {
        "lastname":           "dupont",
        "bearers_since_1890": 12500,
        "departments_count":  87,
        "national_rank":      "42",
        "birth_periods":      [{"from": 1890, "to": 1915, "count": 340}, ...],
        "birth_year_context": "450 bearers born in period 1966–1990 (out of 12500 since 1890)",
        "geographic_distribution": [{"department": "Nord", "count": "820"}, ...]
    }
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

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def run_sync(lastname: str, birth_year: str = "") -> dict:
    """
    Fetch etymology and geographic data for a French surname.
    birth_year may be a 4-digit year string or a range like "1985-1999".
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"error": "beautifulsoup4 not installed — run: pip install beautifulsoup4"}

    import requests

    lastname_clean = lastname.strip().lower()
    if not lastname_clean:
        return {"error": "lastname is required"}

    birth_yr: int | None = None
    if birth_year:
        m_by = re.match(r"(\d{4})", birth_year.strip())
        if m_by:
            birth_yr = int(m_by.group(1))

    headers = {"User-Agent": _UA, "Accept-Language": "fr-FR,fr;q=0.9"}
    session = requests.Session()
    result: dict = {"lastname": lastname_clean}

    # ── Patronyme statistics ─────────────────────────────────────
    try:
        url_ety = f"https://www.filae.com/nom-de-famille/{lastname_clean}.html"
        r = session.get(url_ety, headers=headers, timeout=10, verify=False)

        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            patro = soup.find("ul", {"class": "patronyme"})
            raw_patro = patro.get_text() if patro else ""

            m_prt = re.search(
                r"(\d+)\s+personnes?\s+nées?\s+en\s+France\s+depuis\s+1890,?\s+dans\s+(\d+)\s+département",
                raw_patro,
            )
            if m_prt:
                result["bearers_since_1890"] = int(m_prt.group(1))
                result["departments_count"]  = int(m_prt.group(2))

            m_rank = re.search(r"([\d\s]{2,12})\s+rang\s+des\s+noms\s+les\s+plus\s+portés", raw_patro)
            if m_rank:
                result["national_rank"] = m_rank.group(1).strip().replace(" ", "")

            periods = [
                {"from": int(a), "to": int(b), "count": int(c)}
                for a, b, c in re.findall(r"(\d{4})\s*-\s*(\d{4})\s*:\s*(\d+)", raw_patro)
            ]
            if periods:
                result["birth_periods"] = periods

            if birth_yr and periods:
                matched = next(
                    (p for p in periods if p["from"] <= birth_yr <= p["to"]), None
                )
                if not matched and birth_yr > periods[-1]["to"]:
                    matched = periods[-1]
                if matched:
                    period_label = (
                        f"{matched['from']}–{matched['to']}"
                        if birth_yr <= matched["to"]
                        else f"{matched['from']}–{matched['to']} (most recent available)"
                    )
                    total_b = result.get("bearers_since_1890", "?")
                    result["birth_year_context"] = (
                        f"{matched['count']} bearers born in period {period_label} "
                        f"(out of {total_b} total since 1890)"
                    )

            if not m_prt:
                result["note"] = "Surname not found or too rare on filae.com"
        else:
            result["note"] = f"filae.com returned {r.status_code}"
    except Exception as exc:
        result["etymology_error"] = str(exc)

    # ── Geographic distribution ──────────────────────────────────
    try:
        url_geo = f"https://www.filae.com/nom-de-famille/nom-{lastname_clean}-par-departement"
        r2 = session.get(url_geo, headers=headers, timeout=10, verify=False)

        if r2.status_code == 200:
            soup2 = BeautifulSoup(r2.text, "html.parser")
            distribution: list[dict] = []
            for row in soup2.find_all("tr"):
                dept_cell  = row.find("td", {"class": "nameCellDepRank"})
                count_cell = row.find("td", {"class": "numberCell"})
                if dept_cell and dept_cell.find("a") and count_cell:
                    dept_name = re.sub(r"\s+", " ", dept_cell.find("a").text.strip())
                    distribution.append({"department": dept_name, "count": count_cell.text.strip()})
            result["geographic_distribution"] = distribution[:15]
        else:
            result["geographic_distribution"] = []
    except Exception as exc:
        result["geo_error"] = str(exc)

    return result


async def run(lastname: str, birth_year: str = "") -> dict:
    """Async wrapper — usable from async pipeline."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_sync, lastname, birth_year)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="French surname etymology (filae.com)")
    parser.add_argument("lastname", help="Surname to look up")
    parser.add_argument("--birth-year", default="", help="Birth year for generational context (e.g. 1990)")
    args = parser.parse_args()
    print(json.dumps(run_sync(args.lastname, args.birth_year), ensure_ascii=False, indent=2))
