"""
French surname etymology & demographic distribution skill.

Scrapes forebears.io to retrieve:
- Total worldwide bearers, world rank
- France-specific count, frequency, rank
- Most prevalent country
- Name origin / meaning
- Top countries by incidence

Usage:
    python -m skills.identity.etymology Dupont
    python -m skills.identity.etymology Dupont --birth-year 1990

Returns JSON:
    {
        "lastname":           "dupont",
        "bearers_since_1890": 77740,          # France count (backward-compat key)
        "total_worldwide":    130131,
        "national_rank":      "23",            # Rank in France
        "france_frequency":   "1:854",
        "world_rank":         "4,327",
        "most_prevalent_in":  "France",
        "name_origin":        "Le Pont, seigneuries en Bretagne...",
        "geographic_distribution": [
            {"department": "France",   "count": "77,740"},
            {"department": "Belgique", "count": "14,956"},
            ...
        ]
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
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def run_sync(lastname: str, birth_year: str = "") -> dict:
    """Fetch etymology and geographic data for a surname from forebears.io."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"error": "beautifulsoup4 not installed — run: pip install beautifulsoup4"}

    import requests

    lastname_clean = lastname.strip().lower()
    if not lastname_clean:
        return {"error": "lastname is required"}

    headers = {
        "User-Agent": _UA,
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    result: dict = {"lastname": lastname_clean}

    try:
        url = f"https://forebears.io/fr/surnames/{lastname_clean}"
        try:
            from skills.utils.browser import smart_get
            status_code, html_body = smart_get(url, headers=headers, timeout=12)
        except ImportError:
            r = requests.get(url, headers=headers, timeout=12)
            status_code, html_body = r.status_code, r.text

        if status_code != 200:
            result["note"] = f"forebears.io returned {status_code}"
            return result

        soup = BeautifulSoup(html_body, "html.parser")
        full_text = soup.get_text()

        # ── World rank ────────────────────────────────────────────
        m_rank = re.search(r"([\d,]+)e?\s+Le plus commun\s*nom de famille dans le monde", full_text)
        if m_rank:
            result["world_rank"] = m_rank.group(1).strip()

        # ── Total worldwide ───────────────────────────────────────
        m_total = re.search(r"Environ\s+([\d,\s]+)\s+les gens portent ce nom", full_text)
        if m_total:
            raw = m_total.group(1).replace(",", "").replace("\xa0", "").replace(" ", "")
            try:
                result["total_worldwide"] = int(raw)
            except ValueError:
                pass

        # ── Most prevalent in ─────────────────────────────────────
        m_prev = re.search(r"Le plus répandu dans:\s*([^\nD]+?)(?:Densité|$)", full_text)
        if m_prev:
            result["most_prevalent_in"] = m_prev.group(1).strip()

        # ── Name origin ───────────────────────────────────────────
        m_def = re.search(r"Définition du Nom de Famille:\s*(.+?)(?:En savoir plus|$)", full_text, re.DOTALL)
        if m_def:
            result["name_origin"] = re.sub(r"\s+", " ", m_def.group(1)).strip()

        # ── France-specific row from table ────────────────────────
        france_count = None
        for row in soup.find_all("tr"):
            cells = [td.get_text().strip() for td in row.find_all("td")]
            if cells and cells[0] == "France" and len(cells) >= 4:
                raw_count = cells[1].replace(",", "").replace("\xa0", "").replace(" ", "")
                try:
                    france_count = int(raw_count)
                    result["bearers_since_1890"] = france_count   # backward-compat key
                    result["france_frequency"]   = cells[2]
                    result["national_rank"]       = cells[3]
                except ValueError:
                    pass
                break

        # ── Top countries distribution (max 15) ───────────────────
        distribution: list[dict] = []
        seen: set[str] = set()
        for row in soup.find_all("tr"):
            cells = [td.get_text().strip() for td in row.find_all("td")]
            if len(cells) >= 2 and cells[0] and cells[0] not in seen:
                raw = cells[1].replace(",", "").replace("\xa0", "").replace(" ", "")
                if raw.isdigit() and int(raw) > 0:
                    seen.add(cells[0])
                    distribution.append({"department": cells[0], "count": cells[1]})
            if len(distribution) >= 15:
                break
        result["geographic_distribution"] = distribution

        if not result.get("bearers_since_1890") and not result.get("world_rank"):
            result["note"] = "Surname not found on forebears.io"

    except Exception as exc:
        result["etymology_error"] = str(exc)

    return result


async def run(lastname: str, birth_year: str = "") -> dict:
    """Async wrapper — usable from async pipeline."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_sync, lastname, birth_year)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Surname etymology & demographics (forebears.io)")
    parser.add_argument("lastname", help="Surname to look up")
    parser.add_argument("--birth-year", default="", help="Birth year (unused — kept for CLI compat)")
    args = parser.parse_args()
    print(json.dumps(run_sync(args.lastname, args.birth_year), ensure_ascii=False, indent=2))
