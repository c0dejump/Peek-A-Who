"""
PAW Email OSINT Agent

Connects an LLM (via litellm) to the MCP server via stdio.
Supports two modes:
  - With LLM  : the model decides which tools to call
  - Without   : fixed pipeline (generate → validate_batch → hibp)

Can be driven via CLI or via the web runner (callback-based output).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Callable, Optional

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

_SKILLS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "SKILLS.md"))


def _load_skills() -> str:
    if os.path.exists(_SKILLS_PATH):
        with open(_SKILLS_PATH) as f:
            return f.read()
    return ""


try:
    import litellm
    litellm.suppress_debug_info = True
    from litellm import completion as llm_completion
    USE_LLM = True
except ImportError:
    USE_LLM = False

_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# French department names AND major cities → department code
# Keys are lower-cased, accent-stripped, hyphens normalized to "-"
_LOCATION_TO_DEPT: dict[str, str] = {
    # ── All 95 metropolitan departments (name → code) ───────
    "ain": "01", "aisne": "02", "allier": "03",
    "alpes-de-haute-provence": "04", "basses-alpes": "04",
    "hautes-alpes": "05", "alpes-maritimes": "06",
    "ardeche": "07", "ardennes": "08", "ariege": "09", "aube": "10",
    "aude": "11", "aveyron": "12", "bouches-du-rhone": "13",
    "calvados": "14", "cantal": "15", "charente": "16",
    "charente-maritime": "17", "charente-inferieure": "17",
    "cher": "18", "correze": "19", "corse-du-sud": "2a",
    "haute-corse": "2b", "corse": "20",
    "cote-d-or": "21", "cotes-d-armor": "22", "cotes-du-nord": "22",
    "creuse": "23", "dordogne": "24", "doubs": "25", "drome": "26",
    "eure": "27", "eure-et-loir": "28", "finistere": "29",
    "gard": "30", "haute-garonne": "31", "gers": "32",
    "gironde": "33", "herault": "34", "ille-et-vilaine": "35",
    "indre": "36", "indre-et-loire": "37", "isere": "38",
    "jura": "39", "landes": "40", "loir-et-cher": "41",
    "loire": "42", "haute-loire": "43", "loire-atlantique": "44",
    "loiret": "45", "lot": "46", "lot-et-garonne": "47",
    "lozere": "48", "maine-et-loire": "49", "manche": "50",
    "marne": "51", "haute-marne": "52", "mayenne": "53",
    "meurthe-et-moselle": "54", "meuse": "55", "morbihan": "56",
    "moselle": "57", "nievre": "58", "nord": "59", "oise": "60",
    "orne": "61", "pas-de-calais": "62", "puy-de-dome": "63",
    "pyrenees-atlantiques": "64", "basses-pyrenees": "64",
    "hautes-pyrenees": "65", "pyrenees-orientales": "66",
    "bas-rhin": "67", "haut-rhin": "68", "rhone": "69",
    "haute-saone": "70", "saone-et-loire": "71", "sarthe": "72",
    "savoie": "73", "haute-savoie": "74", "paris": "75",
    "seine-maritime": "76", "seine-inferieure": "76",
    "seine-et-marne": "77", "yvelines": "78", "deux-sevres": "79",
    "somme": "80", "tarn": "81", "tarn-et-garonne": "82",
    "var": "83", "vaucluse": "84", "vendee": "85", "vienne": "86",
    "haute-vienne": "87", "vosges": "88", "yonne": "89",
    "territoire-de-belfort": "90", "essonne": "91",
    "hauts-de-seine": "92", "seine-saint-denis": "93",
    "val-de-marne": "94", "val-d-oise": "95",
    # ── Major cities ────────────────────────────────────────
    "marseille": "13", "lyon": "69", "bordeaux": "33",
    "toulouse": "31", "nantes": "44", "strasbourg": "67",
    "nice": "06", "rennes": "35", "montpellier": "34",
    "reims": "51", "grenoble": "38", "dijon": "21",
    "angers": "49", "nimes": "30", "brest": "29",
    "le havre": "76", "saint-etienne": "42", "toulon": "83",
    "amiens": "80", "limoges": "87", "clermont-ferrand": "63",
    "caen": "14", "metz": "57", "nancy": "54",
    "rouen": "76", "perpignan": "66", "versailles": "78",
    "pau": "64", "orleans": "45", "mulhouse": "68",
    "besancon": "25", "lille": "59", "tours": "37",
    "valenciennes": "59", "dunkerque": "59", "avignon": "84",
    "poitiers": "86", "lorient": "56", "nanterre": "92",
    "boulogne-billancourt": "92", "neuilly-sur-seine": "92",
    "montreuil": "93", "saint-denis": "93",
    "creteil": "94", "argenteuil": "95", "pontoise": "95",
}

# Department code → academy URL slug (linternaute.com)
_DEPT_TO_ACADEMY: dict[str, str] = {
    "01": "academie-lyon",            "02": "academie-amiens",
    "03": "academie-clermont-ferrand","04": "academie-aix-marseille",
    "05": "academie-aix-marseille",   "06": "academie-nice",
    "07": "academie-grenoble",        "08": "academie-reims",
    "09": "academie-toulouse",        "10": "academie-reims",
    "11": "academie-montpellier",     "12": "academie-toulouse",
    "13": "academie-aix-marseille",   "14": "academie-normandie",
    "15": "academie-clermont-ferrand","16": "academie-poitiers",
    "17": "academie-poitiers",        "18": "academie-orleans-tours",
    "19": "academie-limoges",         "20": "academie-corse",
    "2a": "academie-corse",           "2b": "academie-corse",
    "21": "academie-dijon",           "22": "academie-rennes",
    "23": "academie-limoges",         "24": "academie-bordeaux",
    "25": "academie-besancon",        "26": "academie-grenoble",
    "27": "academie-normandie",       "28": "academie-orleans-tours",
    "29": "academie-rennes",          "30": "academie-montpellier",
    "31": "academie-toulouse",        "32": "academie-toulouse",
    "33": "academie-bordeaux",        "34": "academie-montpellier",
    "35": "academie-rennes",          "36": "academie-orleans-tours",
    "37": "academie-orleans-tours",   "38": "academie-grenoble",
    "39": "academie-besancon",        "40": "academie-bordeaux",
    "41": "academie-orleans-tours",   "42": "academie-lyon",
    "43": "academie-clermont-ferrand","44": "academie-nantes",
    "45": "academie-orleans-tours",   "46": "academie-toulouse",
    "47": "academie-bordeaux",        "48": "academie-montpellier",
    "49": "academie-nantes",          "50": "academie-normandie",
    "51": "academie-reims",           "52": "academie-reims",
    "53": "academie-nantes",          "54": "academie-nancy-metz",
    "55": "academie-nancy-metz",      "56": "academie-rennes",
    "57": "academie-nancy-metz",      "58": "academie-dijon",
    "59": "academie-lille",           "60": "academie-amiens",
    "61": "academie-normandie",       "62": "academie-lille",
    "63": "academie-clermont-ferrand","64": "academie-bordeaux",
    "65": "academie-toulouse",        "66": "academie-montpellier",
    "67": "academie-strasbourg",      "68": "academie-strasbourg",
    "69": "academie-lyon",            "70": "academie-besancon",
    "71": "academie-dijon",           "72": "academie-nantes",
    "73": "academie-grenoble",        "74": "academie-grenoble",
    "75": "academie-paris",           "76": "academie-normandie",
    "77": "academie-creteil",         "78": "academie-versailles",
    "79": "academie-poitiers",        "80": "academie-amiens",
    "81": "academie-toulouse",        "82": "academie-toulouse",
    "83": "academie-nice",            "84": "academie-aix-marseille",
    "85": "academie-nantes",          "86": "academie-poitiers",
    "87": "academie-limoges",         "88": "academie-nancy-metz",
    "89": "academie-dijon",           "90": "academie-besancon",
    "91": "academie-versailles",      "92": "academie-versailles",
    "93": "academie-creteil",         "94": "academie-creteil",
    "95": "academie-versailles",
}

_ACCENT_MAP = str.maketrans(
    "éèêëàâäôöùûüîïç",
    "eeeeaaaoouuuiic",
)


def _normalize_location(s: str) -> str:
    """Lowercase, strip accents, replace spaces/apostrophes with hyphens."""
    s = s.lower().translate(_ACCENT_MAP)
    s = re.sub(r"[\s'']+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _cities_to_keywords(cities: list[str]) -> list[str]:
    """Convert city/dept names or codes to email-ready keywords, adding dept codes."""
    extras: list[str] = []
    seen: set[str] = set()

    def _add(k: str):
        if k and k not in seen:
            seen.add(k)
            extras.append(k)

    for city in cities:
        raw = city.strip()
        norm = _normalize_location(raw)

        # Pure number → treat as dept code directly
        if re.match(r'^\d{2,3}$', norm):
            _add(norm)
            continue

        # Cleaned alphanumeric for email use (e.g. "seine-saint-denis" → "seinesaintdenis")
        clean = re.sub(r'[^a-z0-9]', '', norm)
        _add(clean)

        # Dept code lookup (exact, then with/without articles)
        dept = _LOCATION_TO_DEPT.get(norm)
        if not dept:
            # Try dropping common leading articles: "l-oise" → "oise"
            stripped = re.sub(r'^(le?s?|la|les)-', '', norm)
            dept = _LOCATION_TO_DEPT.get(stripped)
        if dept:
            _add(dept)

    return extras


def _diploma_relevance(doc_year: str | None, birth_year: int | None, doc_type: str) -> str:
    """
    Return a human-readable relevance tag based on age at time of academic work.
    Bac ~ age 18, Licence ~ 21, Master ~ 23, PhD ~ 26-30.
    """
    if not doc_year or not birth_year:
        return ""
    try:
        year = int(str(doc_year)[:4])
    except (ValueError, TypeError):
        return ""
    age = year - birth_year
    if age < 0:
        return "⚫ impossible (before birth)"
    if doc_type == "thesis":
        if age < 20:  return "🔴 very unlikely (too young)"
        if age < 23:  return "🟠 unlikely"
        if age <= 35: return "🟢 probable"
        if age <= 45: return "🟡 possible"
        return "🟡 possible (late career)"
    else:  # publication / generic
        if age < 18:  return "🔴 very unlikely (too young)"
        if age < 21:  return "🟠 unlikely"
        if age <= 50: return "🟢 probable"
        return "🟡 possible"


async def _search_diplomas_direct(
    firstname: str, lastname: str, cities: list[str], birth_year: str = ""
) -> dict:
    """
    Direct (non-MCP) diploma search via theses.fr, HAL.science, and resultat-bac.linternaute.com.
    Runs blocking HTTP in a thread so it never blocks the MCP stdio transport.
    """
    import requests as _req

    _UA_D = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

    # Parse birth year
    birth_yr_int: int | None = None
    if birth_year:
        m = re.match(r"(\d{4})", birth_year)
        if m:
            birth_yr_int = int(m.group(1))

    # Derive academy slugs from cities/depts (for bac search narrowing)
    academies: list[str] = []
    for city in cities:
        norm = _normalize_location(city.strip())
        dept = norm if re.match(r"^\d{2,3}$", norm) else _LOCATION_TO_DEPT.get(norm)
        if not dept:
            stripped = re.sub(r"^(le?s?|la|les)-", "", norm)
            dept = _LOCATION_TO_DEPT.get(stripped)
        if dept:
            acad = _DEPT_TO_ACADEMY.get(dept.lower())
            if acad and acad not in academies:
                academies.append(acad)

    fn_norm = firstname.lower().translate(_ACCENT_MAP) if firstname else ""
    ln_norm = lastname.lower().translate(_ACCENT_MAP)  if lastname  else ""

    def _nm(full: str, token: str) -> bool:
        """Whole-word, accent-insensitive match of token inside full name."""
        if not token:
            return False
        f = full.lower().translate(_ACCENT_MAP)
        return bool(re.search(r'(?<![a-z])' + re.escape(token) + r'(?![a-z])', f))

    def _bac_relevance(age: int, fn_match: bool) -> str:
        if age < 16:   tag = "⚫ impossible"
        elif age == 17: tag = "🟠 early"
        elif age == 18: tag = "🟢 exact (standard age)"
        elif age == 19: tag = "🟢 probable (+1 year)"
        elif age == 20: tag = "🟡 possible (+2 years)"
        elif age <= 22: tag = "🟡 possible"
        else:           tag = "🔴 unlikely (late)"
        return tag + (" ✓ firstname confirmed" if fn_match else "")

    def _brevet_relevance(age: int, fn_match: bool) -> str:
        if age < 12:   tag = "⚫ impossible"
        elif age == 13: tag = "🟠 very early"
        elif age == 14: tag = "🟢 early (valid)"
        elif age == 15: tag = "🟢 exact (standard age)"
        elif age == 16: tag = "🟡 possible (+1 year)"
        elif age <= 17: tag = "🟡 possible"
        else:           tag = "🔴 unlikely (late)"
        return tag + (" ✓ firstname confirmed" if fn_match else "")

    def _fetch() -> dict:
        results: dict = {
            "theses": [], "publications": [], "bac_results": [], "brevet_results": [],
            "total_theses": 0, "total_pubs": 0, "total_bac": 0, "total_brevet": 0,
        }
        headers = {"User-Agent": _UA_D, "Accept": "application/json"}
        query   = f"{firstname} {lastname}"

        # ── theses.fr ─────────────────────────────────────────
        try:
            r = _req.get(
                "https://theses.fr/api/v1/theses/recherche",
                params={"q": query, "debut": 0, "nombre": 8},
                headers=headers, timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                results["total_theses"] = data.get("totalHits", 0)
                for th in (data.get("theses") or [])[:8]:
                    auteurs = th.get("auteurs") or []
                    author_names = [
                        f"{a.get('prenom','')} {a.get('nom','')}".strip()
                        for a in auteurs
                    ]
                    # Require that at least one author matches both firstname and lastname
                    def _author_ok(names: list[str]) -> bool:
                        for aname in names:
                            has_ln = _nm(aname, ln_norm)
                            has_fn = _nm(aname, fn_norm) if fn_norm else True
                            if has_ln and has_fn:
                                return True
                        return False
                    if ln_norm and not _author_ok(author_names):
                        continue
                    etablissements = [
                        e.get("libelle", "") for e in (th.get("etablissements_soutenance") or [])
                    ]
                    date_raw = th.get("date_soutenance") or th.get("annee_soutenance") or ""
                    year = date_raw[:4] if date_raw else ""
                    results["theses"].append({
                        "title":       th.get("titre", ""),
                        "authors":     author_names,
                        "institution": ", ".join(filter(None, etablissements)),
                        "year":        year,
                        "status":      th.get("statut", ""),
                        "url":         f"https://theses.fr/{th['id']}" if th.get("id") else "",
                    })
        except Exception as exc:
            results["theses_error"] = str(exc)

        # ── HAL.science ───────────────────────────────────────
        try:
            hal_q = f'authFullName_t:"{query}"'
            r2 = _req.get(
                "https://api.archives-ouvertes.fr/search/",
                params={
                    "q":    hal_q,
                    "rows": 5,
                    "fl":   "title_s,authFullName_s,structName_s,producedDate_s,uri_s,docType_s",
                    "wt":   "json",
                    "sort": "producedDate_s desc",
                },
                headers=headers, timeout=10,
            )
            if r2.status_code == 200:
                hal = r2.json().get("response", {})
                results["total_pubs"] = hal.get("numFound", 0)
                for doc in (hal.get("docs") or [])[:8]:
                    titles = doc.get("title_s") or []
                    # Require at least one author matching both tokens
                    hal_authors = doc.get("authFullName_s") or []
                    if ln_norm and not _author_ok(hal_authors):
                        continue
                    results["publications"].append({
                        "title":       titles[0] if titles else "",
                        "authors":     doc.get("authFullName_s") or [],
                        "institution": ", ".join((doc.get("structName_s") or [])[:2]),
                        "year":        (doc.get("producedDate_s") or "")[:4],
                        "type":        doc.get("docType_s", ""),
                        "url":         doc.get("uri_s", ""),
                    })
        except Exception as exc:
            results["hal_error"] = str(exc)

        # ── resultat-bac.linternaute.com ──────────────────────
        # Only search when birth year is known (to bound the year range).
        if birth_yr_int:
            bac_years = range(birth_yr_int + 17, birth_yr_int + 21)  # +17 to +20
            # Always search all-France (no academy filter) first, then narrow by
            # academy if cities are known.  The all-France pass ensures we never
            # miss a result when the person studied in a different region.
            search_academies = [None] + (academies if academies else [])
            seen_ids: set[int] = set()
            for year in bac_years:
                for acad in search_academies:
                    try:
                        params: dict = {"candidate-name": lastname}
                        if acad:
                            params["education-authority"] = acad
                        r3 = _req.get(
                            f"https://search-candidate.linternaute.com/bac/{year}/1",
                            params=params,
                            headers={**headers, "Referer": "https://resultat-bac.linternaute.com/"},
                            timeout=8,
                        )
                        if r3.status_code == 200:
                            for cand in (r3.json().get("candidates") or []):
                                cid = cand.get("id", 0)
                                if cid in seen_ids:
                                    continue
                                seen_ids.add(cid)
                                cname = cand.get("name", "")
                                ln_match = _nm(cname, ln_norm)
                                fn_match = _nm(cname, fn_norm) if fn_norm else False
                                if not ln_match or (fn_norm and not fn_match):
                                    continue
                                age = year - birth_yr_int
                                link_path = cand.get("link", "")
                                results["bac_results"].append({
                                    "name":        cand.get("name", ""),
                                    "diploma":     cand.get("diplomaSerieLabel", ""),
                                    "year":        str(year),
                                    "age_at_bac":  age,
                                    "academy":     acad or "all",
                                    "firstname_match": fn_match,
                                    "relevance":   _bac_relevance(age, fn_match),
                                    "url": f"https://resultat-bac.linternaute.com{link_path}",
                                })
                    except Exception:
                        pass
            results["total_bac"] = len(results["bac_results"])

        # ── resultat-brevet.linternaute.com ──────────────────
        if birth_yr_int:
            brevet_years = range(birth_yr_int + 13, birth_yr_int + 16)  # +13 to +15 (age 14–15)
            search_academies_b = [None] + (academies if academies else [])
            seen_ids_b: set[int] = set()
            for year in brevet_years:
                for acad in search_academies_b:
                    try:
                        params_b: dict = {"candidate-name": lastname}
                        if acad:
                            params_b["education-authority"] = acad
                        rb = _req.get(
                            f"https://search-candidate.linternaute.com/brevet/{year}/1",
                            params=params_b,
                            headers={**headers, "Referer": "https://resultat-brevet.linternaute.com/"},
                            timeout=8,
                        )
                        if rb.status_code == 200:
                            for cand in (rb.json().get("candidates") or []):
                                cid = cand.get("id", 0)
                                if cid in seen_ids_b:
                                    continue
                                seen_ids_b.add(cid)
                                cname = cand.get("name", "")
                                ln_match = _nm(cname, ln_norm)
                                fn_match = _nm(cname, fn_norm) if fn_norm else False
                                if not ln_match or (fn_norm and not fn_match):
                                    continue
                                age = year - birth_yr_int
                                link_path = cand.get("link", "")
                                results["brevet_results"].append({
                                    "name":          cand.get("name", ""),
                                    "year":          str(year),
                                    "age_at_brevet": age,
                                    "academy":       acad or "all",
                                    "firstname_match": fn_match,
                                    "relevance":     _brevet_relevance(age, fn_match),
                                    "url": f"https://resultat-brevet.linternaute.com{link_path}",
                                })
                    except Exception:
                        pass
            results["total_brevet"] = len(results["brevet_results"])

        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


_FR_DOM_TOM_PREFIXES: dict[str, str] = {
    "0590": "Guadeloupe",       "0690": "Guadeloupe",  "0691": "Guadeloupe",
    "0596": "Martinique",       "0696": "Martinique",  "0697": "Martinique",
    "0594": "Guyane",           "0694": "Guyane",
    "0262": "La Réunion",       "0692": "La Réunion",  "0693": "La Réunion",
    "0269": "Mayotte",          "0639": "Mayotte",
    "0508": "Saint-Pierre-et-Miquelon",
    "0681": "Wallis-et-Futuna",
    "0687": "Polynésie française", "0689": "Polynésie française",
}

_FR_CARRIER_SIRET: dict[str, str] = {
    "free mobile":      "499 247 138 00013",
    "orange":           "380 129 866 00011",
    "sfr":              "343 059 564 00053",
    "bouygues telecom": "397 480 930 00038",
    "bouygues":         "397 480 930 00038",
    "coriolis":         "422 028 442 00029",
    "prixtel":          "480 716 633 00019",
    "syma mobile":      "820 823 670 00012",
    "lebara":           "498 461 534 00014",
    "réglo mobile":     "832 036 551 00024",
}

def _fr_territory(national_clean: str) -> str:
    """Derive ARCEP territory from a cleaned French national number (e.g. '0743555604')."""
    p4 = national_clean[:4]
    if p4 in _FR_DOM_TOM_PREFIXES:
        return f"DOM-TOM ({_FR_DOM_TOM_PREFIXES[p4]})"
    if len(national_clean) >= 2 and national_clean[0] == "0" and national_clean[1] in "1234567":
        return "Métropole"
    return ""


def _fetch_tellows(e164: str) -> dict | None:
    """
    Fetch Tellows spam data. Tries their test API first, falls back to page scrape.
    Returns dict with score (1-10), caller_type, comments, searches, url — or None.
    """
    try:
        import requests as _rq
        # Tellows test API (documented free tier — rate-limited)
        api = _rq.get(
            "https://www.tellows.de/basic/num/" + e164.replace("+", "%2B"),
            params={"json": "1", "partner": "test", "apikey": "test123"},
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if api.status_code == 200:
            entry = (api.json().get("tellows") or [{}])[0]
            if entry.get("score") and int(entry["score"]) > 0:
                return {
                    "score":       int(entry["score"]),
                    "caller_type": entry.get("callertype", ""),
                    "comments":    int(entry.get("comments", 0)),
                    "searches":    int(entry.get("searches", 0)),
                    "url":         f"https://www.tellows.fr/num/{e164}",
                }
    except Exception:
        pass

    # Fallback: scrape the French Tellows page
    try:
        import requests as _rq
        resp = _rq.get(
            f"https://www.tellows.fr/num/{e164}",
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        if resp.status_code != 200:
            return None
        html = resp.text

        score = None
        for pat in [
            r'"score"\s*[=:]\s*["\']?(\d+)',
            r'data-score["\s:=]+(\d+)',
            r'class="[^"]*score[^"]*"[^>]*>\s*(\d+)\s*<',
            r'>(\d)\s*/\s*10<',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                v = int(m.group(1))
                if 1 <= v <= 10:
                    score = v
                    break

        caller_type = ""
        for ct in ["Telemarketer", "Spam", "Arnaque", "Neutre", "Sûr", "Support", "Inconnu", "Neutral", "Safe"]:
            if ct.lower() in html.lower():
                caller_type = ct
                break

        comments = 0
        mc = re.search(r'(\d+)\s*[Cc]ommentaire', html)
        if mc:
            comments = int(mc.group(1))

        if score is not None or comments > 0:
            return {
                "score":       score,
                "caller_type": caller_type,
                "comments":    comments,
                "searches":    0,
                "url":         f"https://www.tellows.fr/num/{e164}",
            }
    except Exception:
        pass
    return None


def _fetch_caller_name(e164: str, e164_no_plus: str, national_clean: str) -> str:
    """
    Try to identify the owner name of a phone number from caller-ID sources.
    Tries (in order): Truecaller SSR page → callerinfo.fr → annuairetel.com.
    Returns best name found, or "" if nothing usable.
    """
    _hdrs = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    _bad  = {"truecaller", "unknown", "private", "search", "numéro", "number",
             "inconnu", "caller", "phone", "mobile", "fixe"}

    def _clean(name: str) -> str:
        name = name.strip().strip('"\'').strip()
        # reject if too short, too long, or matches noise words
        if len(name) < 3 or len(name) > 60:
            return ""
        if any(b in name.lower() for b in _bad):
            return ""
        # reject if it looks like a number or URL
        if re.search(r'\d{3}|\bwww\b|http', name, re.I):
            return ""
        return name

    import requests as _rq

    # 1. Truecaller (often does SSR with name in <title> / JSON-LD for SEO)
    try:
        r = _rq.get(
            f"https://www.truecaller.com/search/fr/{e164_no_plus}",
            timeout=6, headers=_hdrs,
        )
        if r.status_code == 200:
            for pat in [
                r"<title>Truecaller:\s*([^<\-|]{3,60}?)(?:\s*[-|<]|\s*$)",
                r'"name"\s*:\s*"([A-Za-zÀ-ÿ\s\-\.]{3,60})"',
                r'<meta[^>]+name="description"[^>]+content="([A-Za-zÀ-ÿ][^"]{4,80}?)(?:\s+(?:from|de|is|est)\b)',
            ]:
                m = re.search(pat, r.text, re.IGNORECASE)
                if m:
                    n = _clean(m.group(1))
                    if n:
                        return n
    except Exception:
        pass

    # 2. callerinfo.fr
    try:
        r = _rq.get(
            f"https://callerinfo.fr/{national_clean}",
            timeout=5, headers=_hdrs,
        )
        if r.status_code == 200:
            for pat in [
                r"class=\"[^\"]*(?:caller|owner|name|nom)[^\"]*\"[^>]*>([A-Za-zÀ-ÿ][^<]{2,60})<",
                r"[Pp]ropri[eé]taire[^:<]*[:<]\s*([A-Za-zÀ-ÿ][^\n<]{3,60})",
                r'"(?:name|caller|owner)"\s*:\s*"([^"]{3,60})"',
            ]:
                m = re.search(pat, r.text, re.IGNORECASE)
                if m:
                    n = _clean(m.group(1))
                    if n:
                        return n
    except Exception:
        pass

    # 3. annuairetel.com
    try:
        r = _rq.get(
            f"https://www.annuairetel.com/numero/{national_clean}",
            timeout=4, headers=_hdrs,
        )
        if r.status_code == 200:
            for pat in [
                r"class=\"[^\"]*(?:name|nom|owner|caller)[^\"]*\"[^>]*>([A-Za-zÀ-ÿ][^<]{2,60})<",
                r"[Pp]ropri[eé]taire[^:<]*[:<]\s*([A-Za-zÀ-ÿ][^\n<]{3,60})",
            ]:
                m = re.search(pat, r.text, re.IGNORECASE)
                if m:
                    n = _clean(m.group(1))
                    if n:
                        return n
    except Exception:
        pass

    return ""


def _check_dork_hit(query: str) -> tuple[bool, str]:
    """
    Check whether a dork query returns real results, via the resilient
    multi-engine search core (DDG → DDG-lite → Bing, with caching).
    Returns (hit: bool, ddg_url: str) — the URL points to a DDG search for the
    same query so the link shown to the user stays human-clickable.
    """
    from urllib.parse import quote_plus
    ddg_url = "https://duckduckgo.com/?q=" + quote_plus(query) + "&kl=fr-fr"
    try:
        from skills.utils.search import web_search
        res = web_search(query, num_results=5, region="fr-fr", timeout=8)
        return bool(res.get("results")), ddg_url
    except Exception:
        return False, ddg_url


def _build_phone_footprint(
    national_clean: str,
    e164: str,
    firstname: str = "",
) -> dict[str, str]:
    """
    For each phone-number dork variant, check DDG for real results.
    Returns {label: google_search_url} for hits only.
    Runs all checks in parallel (max 8 workers, 25s total timeout).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    digits  = re.sub(r"\D", "", national_clean)
    spaced  = " ".join(digits[i:i+2] for i in range(0, len(digits), 2))
    dashed  = "-".join(digits[i:i+2] for i in range(0, len(digits), 2))
    dotted  = ".".join(digits[i:i+2] for i in range(0, len(digits), 2))

    targets: list[tuple[str, str]] = [
        # (label, dork_query)
        # — Classified ads —
        ("Leboncoin",           f'"{national_clean}" site:leboncoin.fr'),
        ("Leboncoin (espacé)",  f'"{spaced}" site:leboncoin.fr'),
        ("AVendreALouer",       f'"{national_clean}" site:avendrealouer.fr'),
        ("PAP.fr",              f'"{national_clean}" site:pap.fr'),
        ("SeLoger",             f'"{national_clean}" site:seloger.com'),
        ("Logic-Immo",          f'"{national_clean}" site:logic-immo.com'),
        # — Social —
        ("Facebook",            f'"{national_clean}" site:facebook.com'),
        ("Facebook (espacé)",   f'"{spaced}" site:facebook.com'),
        ("Viadeo",              f'"{national_clean}" site:viadeo.com'),
        ("Copains d'avant",     f'"{national_clean}" site:copainsdavant.fr'),
        # — General web —
        ("Web (national)",      f'"{national_clean}"'),
        ("Web (espacé)",        f'"{spaced}"'),
        ("Web (tirets)",        f'"{dashed}"'),
        ("Web (points)",        f'"{dotted}"'),
        ("Web (E.164)",         f'"{e164}"'),
    ]

    if firstname:
        fn = firstname.strip()
        targets += [
            (f"{fn} + national", f'"{fn}" "{national_clean}"'),
            (f"{fn} + E.164",   f'"{fn}" "{e164}"'),
            (f"{fn} + espacé",  f'"{fn}" "{spaced}"'),
        ]

    hits: dict[str, str] = {}

    def _worker(label: str, query: str):
        hit, url = _check_dork_hit(query)
        return (label, url) if hit else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_worker, lbl, q): lbl for lbl, q in targets}
        for fut in as_completed(futures, timeout=25):
            try:
                res = fut.result()
                if res:
                    hits[res[0]] = res[1]
            except Exception:
                pass

    return hits


async def _search_phone_direct(
    phone: str,
    firstname: str = "",
    lastname: str = "",
) -> dict:
    """
    Phone OSINT: phonenumbers parse/validate, ignorant social check,
    PhoneInfoga scan, Numverify (optional), identity dork URL generation.
    """
    def _fetch() -> dict:
        results: dict = {
            "raw": phone,
            "valid": False,
            "e164": "",
            "national": "",
            "international": "",
            "country_code": "",
            "national_number": "",
            "type": "Unknown",
            "carrier": "",
            "region": "",
            "timezone": "",
            "arcep":          None,   # ARCEP enrichment (France only)
            "tellows":        None,   # Tellows spam score
            "caller_name":    "",    # owner name from caller-ID sources
            "footprint":      {},    # dorks that returned hits (label → google url)
            "reverse_links":  {},  # reverse lookup + generic search
            "identity_links": {},  # targeted social/identity dorks
            "app_links":      {},  # messaging app deeplinks
            "ignorant_platforms": [],
            "phoneinfoga":    None,
            "numverify":      None,
        }

        try:
            import phonenumbers
            from phonenumbers import (
                carrier as ph_carrier,
                geocoder as ph_geo,
                timezone as ph_tz,
                PhoneNumberType,
                PhoneNumberFormat,
            )
        except ImportError:
            results["error"] = "phonenumbers library not installed (pip install phonenumbers)"
            return results

        try:
            if phone.startswith("0") and not phone.startswith("00"):
                number = phonenumbers.parse(phone, "FR")
            else:
                number = phonenumbers.parse(phone, None)
        except phonenumbers.NumberParseException as exc:
            results["error"] = str(exc)
            return results

        results["valid"]           = phonenumbers.is_valid_number(number)
        results["e164"]            = phonenumbers.format_number(number, PhoneNumberFormat.E164)
        results["national"]        = phonenumbers.format_number(number, PhoneNumberFormat.NATIONAL)
        results["international"]   = phonenumbers.format_number(number, PhoneNumberFormat.INTERNATIONAL)
        results["country_code"]    = str(number.country_code)
        results["national_number"] = str(number.national_number)

        _type_map = {
            PhoneNumberType.MOBILE:               "Mobile",
            PhoneNumberType.FIXED_LINE:           "Fixed line",
            PhoneNumberType.FIXED_LINE_OR_MOBILE: "Fixed/Mobile",
            PhoneNumberType.TOLL_FREE:            "Toll-free",
            PhoneNumberType.PREMIUM_RATE:         "Premium rate",
            PhoneNumberType.SHARED_COST:          "Shared cost",
            PhoneNumberType.VOIP:                 "VoIP",
            PhoneNumberType.PERSONAL_NUMBER:      "Personal number",
            PhoneNumberType.PAGER:                "Pager",
            PhoneNumberType.UAN:                  "UAN",
        }
        results["type"]     = _type_map.get(phonenumbers.number_type(number), "Unknown")
        results["carrier"]  = ph_carrier.name_for_number(number, "fr") or ""
        results["region"]   = ph_geo.description_for_number(number, "fr") or ""
        tz_list             = ph_tz.time_zones_for_number(number)
        results["timezone"] = ", ".join(tz_list) if tz_list else ""

        e164_no_plus   = results["e164"].lstrip("+")
        national_clean = re.sub(r"[\s\.\-]", "", results["national"])
        e164_q         = results["e164"].replace("+", "%2B")
        nat_q          = results["national"].replace(" ", "+")

        # ── ARCEP enrichment (France only) ───────────────────
        # phonenumbers carrier db has very incomplete coverage for France.
        # We run a multi-source fallback chain to fill in the carrier before
        # computing the SIRET (which depends on the carrier name).
        if results["valid"] and results["country_code"] == "33":
            _territory        = _fr_territory(national_clean)
            _attribution_date = ""

            # ── Source 1: numerobis.fr (aggregates ARCEP data) ──
            try:
                import requests as _req_arcep
                _ar = _req_arcep.get(
                    f"https://www.numerobis.fr/api/number/{national_clean}",
                    timeout=4,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if _ar.status_code == 200:
                    _ard = _ar.json()
                    # carrier
                    _op = (
                        _ard.get("operator") or _ard.get("operateur") or
                        _ard.get("carrier")  or _ard.get("nom_operateur") or ""
                    ).strip()
                    if _op and not results["carrier"]:
                        results["carrier"] = _op
                    # attribution date
                    _attribution_date = (
                        _ard.get("date_attribution") or
                        _ard.get("attribution_date") or ""
                    )
            except Exception:
                pass

            # ── Source 2: scrape numerobis.fr web page ──────────
            if not results["carrier"]:
                try:
                    import requests as _req2
                    _page = _req2.get(
                        f"https://www.numerobis.fr/{national_clean}",
                        timeout=4,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if _page.status_code == 200:
                        for _pat in [
                            r"[Oo]p[ée]rateur[^:<]*[:<][^>]*>\s*([A-Za-z][^<\n]{2,40})",
                            r'"operator"\s*:\s*"([^"]{2,40})"',
                            r'"operateur"\s*:\s*"([^"]{2,40})"',
                        ]:
                            _m = re.search(_pat, _page.text)
                            if _m:
                                _cn = _m.group(1).strip()
                                if _cn and len(_cn) > 2:
                                    results["carrier"] = _cn
                                    break
                except Exception:
                    pass

            # ── Source 3: scrape annuairetel.com ────────────────
            if not results["carrier"]:
                try:
                    import requests as _req3
                    _at = _req3.get(
                        f"https://www.annuairetel.com/numero/{national_clean}",
                        timeout=4,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if _at.status_code == 200:
                        for _pat in [
                            r"[Oo]p[ée]rateur[^:<]*[:<][^>]*>\s*([A-Za-z][^<\n]{2,40})",
                            r'"carrier"\s*:\s*"([^"]{2,40})"',
                            r'class="[^"]*operator[^"]*"[^>]*>\s*([A-Za-z][^<]{2,30})',
                        ]:
                            _m = re.search(_pat, _at.text)
                            if _m:
                                _cn = _m.group(1).strip()
                                if _cn and len(_cn) > 2:
                                    results["carrier"] = _cn
                                    break
                except Exception:
                    pass

            # ── SIRET lookup (now that carrier is finalised) ─────
            _siret = _FR_CARRIER_SIRET.get(results["carrier"].lower().strip(), "")

            results["arcep"] = {
                "territory":        _territory,
                "siret":            _siret,
                "attribution_date": _attribution_date,
            }

        # ── Build URL helpers ─────────────────────────────────
        _fn_q = firstname.strip().replace(" ", "+") if firstname else ""
        _pb_who = f"?quoiqui={_fn_q}&numtel={national_clean}" if _fn_q else f"?quoiqui=&numtel={national_clean}"

        # ── Reverse lookup + general search ──────────────────
        results["reverse_links"] = {
            "pages_blanches": (
                "https://www.pagesjaunes.fr/pagesblanches/chercherlespersonnes" + _pb_who
            ),
            "118712":          f"https://annuaire.118712.fr/inversee/{national_clean}",
            "118000":          f"https://www.118000.fr/search?phone={national_clean}",
            "annuairetel":     f"https://www.annuairetel.com/numero/{national_clean}",
            "phonebook":       f"https://www.phonebook.fr/numero/{national_clean}",
            "qui_appelle":     f"https://www.qui-appelle.fr/{national_clean}",
            "lesarnaques":     f"https://www.lesarnaques.com/telephone/{national_clean}",
            "spamcalls":       f"https://www.spamcalls.net/fr/search?number={national_clean}",
            "callerinfo":      f"https://callerinfo.fr/{national_clean}",
            "google_e164":     f"https://www.google.com/search?q=%22{e164_q}%22",
            "google_national": f"https://www.google.com/search?q=%22{nat_q}%22",
        }

        # ── Targeted identity dorks ───────────────────────────
        results["identity_links"] = {
            "facebook":  f"https://www.google.com/search?q=%22{nat_q}%22+site%3Afacebook.com",
            "linkedin":  f"https://www.google.com/search?q=%22{nat_q}%22+site%3Alinkedin.com",
            "twitter":   f"https://www.google.com/search?q=%22{nat_q}%22+site%3Atwitter.com",
            "viadeo":    f"https://www.google.com/search?q=%22{nat_q}%22+site%3Aviadeo.com",
            "leboncoin": f"https://www.google.com/search?q=%22{nat_q}%22+site%3Aleboncoin.fr",
        }
        # Add firstname-personalized dorks when we have a name to work with
        if _fn_q:
            results["identity_links"]["google_name_phone"] = (
                f"https://www.google.com/search?q=%22{_fn_q}%22+%22{nat_q}%22"
            )
            results["identity_links"]["google_name_e164"] = (
                f"https://www.google.com/search?q=%22{_fn_q}%22+%22{e164_q}%22"
            )
            results["identity_links"]["facebook_phone"] = (
                f"https://www.facebook.com/search/top/?q={e164_q}"
            )

        # ── Messaging / caller-ID apps ────────────────────────
        results["app_links"] = {
            "whatsapp":   f"https://wa.me/{e164_no_plus}",
            "telegram":   f"https://t.me/+{e164_no_plus}",
            "truecaller": f"https://www.truecaller.com/search/fr/{e164_no_plus}",
            "syncme":     f"https://sync.me/search/?number={e164_no_plus}",
            "viber":      f"viber://chat?number={e164_no_plus}",
        }

        # ── Caller name detection (Truecaller → callerinfo → annuairetel) ─
        if results["valid"]:
            results["caller_name"] = _fetch_caller_name(
                results["e164"], e164_no_plus, national_clean
            )

        # ── Public footprint — verified dorks ──────────────────
        if results["valid"]:
            results["footprint"] = _build_phone_footprint(
                national_clean, results["e164"], firstname
            )

        # ── Tellows spam check (free API + page scrape fallback) ──
        if results["valid"]:
            results["tellows"] = _fetch_tellows(results["e164"])

        import subprocess

        # ── Numverify (optional) ──────────────────────────────
        nv_key = os.environ.get("NUMVERIFY_API_KEY", "").strip()
        if nv_key and results["valid"]:
            try:
                import requests as _req
                nv = _req.get(
                    "http://apilayer.net/api/validate",
                    params={"access_key": nv_key, "number": results["e164"]},
                    timeout=8,
                )
                if nv.status_code == 200:
                    nv_data = nv.json()
                    if nv_data.get("valid"):
                        results["numverify"] = {
                            "carrier":      nv_data.get("carrier", ""),
                            "line_type":    nv_data.get("line_type", ""),
                            "location":     nv_data.get("location", ""),
                            "country_name": nv_data.get("country_name", ""),
                        }
            except Exception:
                pass

        # ── ignorant ──────────────────────────────────────────
        if results["valid"]:
            try:
                ig = subprocess.run(
                    [
                        "ignorant",
                        "--no-color", "--no-clear",
                        "-T", "8",           # 8s per-platform timeout (default 10)
                        results["country_code"],
                        results["national_number"],
                    ],
                    capture_output=True, text=True, timeout=120,
                )
                raw_ig = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", ig.stdout or "")
                if raw_ig.strip():
                    platforms: list[dict] = []
                    for ln in raw_ig.splitlines():
                        ln = ln.strip()
                        for prefix, status in (("[+]", "found"), ("[-]", "not_found"), ("[x]", "rate_limited")):
                            if ln.startswith(prefix):
                                site = ln[len(prefix):].strip()
                                if "." in site and " " not in site:
                                    platforms.append({"site": site, "status": status})
                                break
                    results["ignorant_platforms"] = platforms
            except FileNotFoundError:
                pass
            except Exception:
                pass

        # ── PhoneInfoga ───────────────────────────────────────
        if results["valid"]:
            try:
                pif = subprocess.run(
                    ["phoneinfoga", "scan", "-n", results["e164"]],
                    capture_output=True, text=True, timeout=60,
                )
                raw_pif = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", pif.stdout or "")
                if raw_pif.strip():
                    pif_result: dict = {"raw": raw_pif.strip(), "carrier": "", "urls": []}

                    # Extract carrier if phonenumbers didn't get it
                    m_carrier = re.search(r"Carrier\s*[:=]\s*(.+)", raw_pif, re.IGNORECASE)
                    if m_carrier and not results["carrier"]:
                        results["carrier"] = m_carrier.group(1).strip()
                    if m_carrier:
                        pif_result["carrier"] = m_carrier.group(1).strip()

                    # Extract line type
                    m_type = re.search(r"Line\s*type\s*[:=]\s*(.+)", raw_pif, re.IGNORECASE)
                    if m_type:
                        pif_result["line_type"] = m_type.group(1).strip()

                    # Extract all https:// URLs found in Google footprint section
                    urls_found = re.findall(r"https?://[^\s\)\"'<>]+", raw_pif)
                    # Keep only non-google-api URLs (i.e., real search result URLs if any)
                    pif_result["urls"] = [
                        u for u in urls_found
                        if "google.com/search" not in u and len(u) > 25
                    ][:20]

                    results["phoneinfoga"] = pif_result
            except FileNotFoundError:
                results["phoneinfoga"] = {"not_installed": True}
            except Exception:
                pass

        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


def _generate_ig_usernames(
    firstname: str,
    lastname: str,
    birth_year: str = "",
    keywords: list[str] | None = None,
    pseudo: str = "",
    dept_codes: list[str] | None = None,
) -> list[str]:
    """Generate Instagram-valid username candidates (a-z0-9._, max 30 chars)."""

    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower().translate(_ACCENT_MAP))

    def _ig_valid(u: str) -> bool:
        if not u or len(u) > 30:
            return False
        if not re.match(r"^[a-z0-9._]+$", u):
            return False
        if ".." in u or u.startswith(".") or u.endswith("."):
            return False
        return True

    seen: set[str] = set()
    result: list[str] = []

    def _add(c: str) -> None:
        c = c.lower()
        if c and c not in seen and _ig_valid(c):
            seen.add(c)
            result.append(c)

    fn = _norm(firstname) if firstname else ""
    ln = _norm(lastname) if lastname else ""
    fn1 = fn[0] if fn else ""
    ln2 = ln[:2] if len(ln) >= 2 else ln
    ln3 = ln[:3] if len(ln) >= 3 else ln
    bigram = (ln[0] + ln[-1]) if len(ln) >= 2 else ln

    yr = ""
    if birth_year:
        m = re.match(r"(\d{4})", birth_year)
        if m:
            yr = m.group(1)
    yr2 = yr[2:] if len(yr) == 4 else ""

    kws = [_norm(k) for k in (keywords or []) if k.strip()]
    depts = [d for d in (dept_codes or []) if re.match(r"^\d{2}$", str(d))]

    # ── Priority 1: pseudo (exact match, most reliable) ───────
    if pseudo:
        _add(re.sub(r"[^a-z0-9._]", "", pseudo.lower().translate(_ACCENT_MAP)))

    # ── Priority 2: keyword-centric (user explicitly provided) ─
    # These come BEFORE pure name combos because keywords like "mchl"
    # are often the actual username basis, not the full surname.
    for kw in kws:
        if not kw:
            continue
        # A keyword < 4 chars (e.g. "sen") is almost always a prefix/suffix, not a
        # standalone handle — testing it alone floods results with namesakes. So we
        # only combine it with the name/pseudo below.
        _short_kw = len(kw) < 4
        if not _short_kw:
            _add(kw)                      # keyword alone  e.g. "mchl"
            if yr2:
                _add(f"{kw}{yr2}")        # e.g. "mchl90"
                _add(f"{kw}_{yr2}")
        if fn:
            _add(f"{fn}.{kw}")            # e.g. "tristan.mchl"  ← most likely
            _add(f"{fn}_{kw}")
            _add(f"{fn}{kw}")
            _add(f"{kw}.{fn}")
            _add(f"{kw}_{fn}")
            _add(f"{kw}{fn}")
        if ln:
            _add(f"{ln}.{kw}")
            _add(f"{ln}_{kw}")
            _add(f"{ln}{kw}")
            _add(f"{kw}.{ln}")
            _add(f"{kw}_{ln}")
            _add(f"{kw}{ln}")
        if fn and ln:
            _add(f"{fn}.{ln}.{kw}")
            _add(f"{kw}.{fn}.{ln}")

    # ── Priority 3: pure name combos ───────────────────────────
    if fn and ln:
        for sep in (".", "_", ""):
            _add(f"{fn}{sep}{ln}")
            _add(f"{ln}{sep}{fn}")
        for abbr in (ln3, ln2, bigram):
            if abbr and abbr != ln:
                for sep in (".", "_", ""):
                    _add(f"{fn}{sep}{abbr}")
        if fn1:
            for sep in (".", "_", ""):
                _add(f"{fn1}{sep}{ln}")
    elif fn:
        _add(fn)
    elif ln:
        _add(ln)

    # ── Priority 4: name + year ─────────────────────────────────
    if yr and (fn or ln):
        core_snap = list(result)
        for base in core_snap:
            _add(f"{base}{yr2}")
            _add(f"{base}{yr}")
            _add(f"{base}_{yr2}")
            _add(f"{base}.{yr2}")
        if fn: _add(f"{fn}{yr2}")
        if ln: _add(f"{ln}{yr2}")

    # ── Priority 5: dept codes ──────────────────────────────────
    for dept in depts:
        for base in list(result)[:8]:
            _add(f"{base}{dept}")
            _add(f"{base}_{dept}")

    # ── Priority 6: leet-speak variants ────────────────────────
    # Substitute common chars (o→0, e→3, i→1, a→4, s→5, t→7)
    # Only on the top-priority seeds (pseudo + keywords + core names)
    # to avoid combinatorial explosion.
    _LEET = {'o': '0', 'e': '3', 'i': '1', 'a': '4', 's': '5', 't': '7'}

    def _leet_variants(s: str) -> list[str]:
        pos = [(idx, _LEET[c]) for idx, c in enumerate(s) if c in _LEET]
        if not pos:
            return []
        out = []
        # single substitutions
        for i, sub in pos:
            out.append(s[:i] + sub + s[i + 1:])
        # double substitutions (all pairs)
        for a in range(len(pos)):
            for b in range(a + 1, len(pos)):
                v = list(s)
                v[pos[a][0]] = pos[a][1]
                v[pos[b][0]] = pos[b][1]
                out.append(''.join(v))
        return out

    # Seed from pseudo + keywords + first core names (highest priority slice)
    leet_seeds = []
    if pseudo:
        raw_pseudo = re.sub(r"[^a-z0-9._]", "", pseudo.lower().translate(_ACCENT_MAP))
        if raw_pseudo:
            leet_seeds.append(raw_pseudo)
    for kw in kws:
        if kw and len(kw) >= 4:   # short keywords are prefixes/suffixes — don't leet them alone
            leet_seeds.append(kw)
    for base in result[:15]:
        if base not in leet_seeds:
            leet_seeds.append(base)

    for seed in leet_seeds[:20]:
        for variant in _leet_variants(seed):
            _add(variant)

    return result


async def _prevalidate_usernames(
    candidates: list[str],
    firstname: str = "",
    lastname: str = "",
    keywords: list[str] | None = None,
    birth_year: str = "",
    pseudo: str = "",
) -> dict:
    """
    Pre-validates ALL username candidates using maigret + sherlock on the
    36 targeted sites (_MISSING_PERSONS_SITES). Both tools run in parallel
    per username (ThreadPoolExecutor). Only candidates with ≥1 hit on any
    of the 36 sites are considered validated.

    Returns a dict:
      validated        – [username, ...]  with ≥1 hit, sorted by hit_count desc
      not_found        – [username, ...]  with 0 hits
      hits             – {username: [{"site", "url", "tool", "category"}, ...]}
      location_relevant, marketplace, gaming, social  – categorised hits (for enrichment)
      total_found      – total number of (username, site) pairs found
      maigret_ok       – maigret was installed and ran
      sherlock_ok      – sherlock was installed and ran
    """
    import concurrent.futures as _cf
    import subprocess, tempfile, os as _os, json as _json, shutil

    orig_order = {un: i for i, un in enumerate(candidates)}

    # Sites known to return false positives in sherlock (return "found" for every username)
    _SHERLOCK_FP: frozenset[str] = frozenset({"Reddit", "Spotify"})

    mg_site_flags: list[str] = []
    sh_site_flags: list[str] = []
    for s in _MISSING_PERSONS_SITES:
        mg_site_flags.extend(["--site", s])
        if s not in _SHERLOCK_FP:
            sh_site_flags.extend(["--site", s])

    # ── Per-username maigret scan ────────────────────────────────
    def _maigret_one(username: str) -> tuple[str, list[dict], bool]:
        """Returns (username, hits, installed)."""
        tmpdir = tempfile.mkdtemp(prefix="paw_mg_")
        try:
            subprocess.run(
                ["maigret", username,
                 "--timeout", "10", "--retries", "1", "-n", "20",
                 "--folderoutput", tmpdir, "-J", "simple",
                 *mg_site_flags],
                capture_output=True, text=True, timeout=120,
            )
            # maigret -J simple creates report_{username}_simple.json
            json_path = _os.path.join(tmpdir, f"report_{username}_simple.json")
            if not _os.path.exists(json_path):
                existing = [f for f in _os.listdir(tmpdir) if f.endswith(".json")]
                if not existing:
                    return username, [], True
                json_path = _os.path.join(tmpdir, existing[0])
            data = _json.load(open(json_path, encoding="utf-8"))
            hits: list[dict] = []
            # simple format: {site_key: {status: {status: "Claimed", url: "..."}, url_user: "..."}}
            for site_name, site_info in data.items():
                status = site_info.get("status", {})
                claimed = (
                    status.get("status") == "Claimed"
                    if isinstance(status, dict) else str(status) == "Claimed"
                )
                if claimed:
                    hits.append({"site": site_name, "url": site_info.get("url_user", ""), "tool": "maigret"})
            return username, hits, True
        except FileNotFoundError:
            return username, [], False
        except Exception:
            return username, [], True
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── Per-username sherlock scan ───────────────────────────────
    def _sherlock_one(username: str) -> tuple[str, list[dict], bool]:
        """Returns (username, hits, installed). Reddit + Spotify excluded (permanent false positives)."""
        import tempfile
        _tmp = tempfile.mkdtemp(prefix="paw_sh_")
        try:
            proc = subprocess.run(
                ["sherlock", username, "--print-found", "--no-color", "--timeout", "10",
                 *sh_site_flags],
                capture_output=True, text=True, timeout=120,
                cwd=_tmp,
            )
            hits: list[dict] = []
            for line in proc.stdout.splitlines():
                if not line.startswith("[+]"):
                    continue
                m = re.match(r"\[\+\]\s+(.+?):\s+(https?://\S+)", line)
                if m:
                    hits.append({"site": m.group(1).strip(), "url": m.group(2).strip(), "tool": "sherlock"})
            return username, hits, True
        except FileNotFoundError:
            return username, [], False
        except Exception:
            return username, [], True
        finally:
            import shutil as _sh
            _sh.rmtree(_tmp, ignore_errors=True)

    # ── Check one username via both tools in parallel ────────────
    def _check_one(username: str) -> tuple[str, list[dict], bool, bool]:
        with _cf.ThreadPoolExecutor(max_workers=2) as inner:
            mg_f = inner.submit(_maigret_one, username)
            sh_f = inner.submit(_sherlock_one, username)
            _, mg_hits, mg_ok = mg_f.result()
            _, sh_hits, sh_ok = sh_f.result()
        # Merge hits, deduplicating by site name
        seen_sites: set[str] = set()
        merged: list[dict] = []
        for h in mg_hits + sh_hits:
            if h["site"] not in seen_sites:
                seen_sites.add(h["site"])
                merged.append(h)
        return username, merged, mg_ok, sh_ok

    # ── Run all candidates (20 parallel workers) ─────────────────
    def _run_all() -> dict:
        hits_map: dict[str, list[dict]] = {}
        maigret_ok = True
        sherlock_ok = True

        with _cf.ThreadPoolExecutor(max_workers=20) as ex:
            futs = {ex.submit(_check_one, un): un for un in candidates}
            for fut in _cf.as_completed(futs):
                username, merged, mg_ok, sh_ok = fut.result()
                hits_map[username] = merged
                if not mg_ok: maigret_ok = False
                if not sh_ok: sherlock_ok = False

        # Categorise and sort
        location_relevant: list[dict] = []
        marketplace:       list[dict] = []
        gaming:            list[dict] = []
        social:            list[dict] = []
        total_found = 0

        validated: list[str] = []
        not_found: list[str] = []

        for username in candidates:
            hits = hits_map.get(username, [])
            if hits:
                validated.append(username)
                total_found += len(hits)
                for h in hits:
                    sl = h["site"].lower()
                    entry = {**h, "username": username}
                    if sl in _LOCATION_SITES_LOW:
                        location_relevant.append(entry)
                    elif sl in _MARKETPLACE_SITES_LOW:
                        marketplace.append(entry)
                    elif sl in _GAMING_SITES_LOW:
                        gaming.append(entry)
                    else:
                        social.append(entry)
            else:
                not_found.append(username)

        # Sort validated by hit count desc, then original order
        validated.sort(key=lambda u: (-len(hits_map.get(u, [])), orig_order.get(u, 999)))

        # ── User-provided pseudo → high-confidence identity ──────
        # If the analyst explicitly supplied a pseudo, any validated hit whose
        # username matches it (leet-insensitive: codejump ≡ c0dejump) is a
        # CONFIRMED identity signal, not just one candidate among many.
        pseudo_confirmed: dict[str, list[str]] = {}
        if pseudo:
            def _deleet(s: str) -> str:
                return re.sub(r"[^a-z0-9]", "", s.lower()).translate(
                    str.maketrans("013457", "oieast"))
            target = _deleet(pseudo)
            if target:
                for un in validated:
                    if _deleet(un) == target:
                        sites = sorted({h["site"] for h in hits_map.get(un, [])})
                        if sites:
                            pseudo_confirmed[un] = sites

        return {
            "validated":        validated,
            "not_found":        not_found,
            "hits":             hits_map,
            "location_relevant": location_relevant,
            "marketplace":      marketplace,
            "gaming":           gaming,
            "social":           social,
            "total_found":      total_found,
            "pseudo_confirmed": pseudo_confirmed,
            "maigret_ok":       maigret_ok,
            "sherlock_ok":      sherlock_ok,
        }

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_all)


async def _search_instagram_direct(
    usernames: list[str],
    firstname: str = "",
    lastname: str = "",
    keywords: list[str] | None = None,
) -> dict:
    """Check Instagram username existence via HTML title detection."""

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
                score += 3   # keyword in username → strong signal
            elif kl in dn:
                score += 3   # keyword in display name/bio → strong signal
        return min(score, 10)

    def _fetch() -> dict:
        import time
        import requests as _req

        # Primary: Instagram mobile API — works without auth for public profiles
        _UA_APP = (
            "Instagram 210.0.0.28.71 Android (26/8.0.0; 480dpi; 1080x1920; "
            "OnePlus; 6T Dev; devitron; qcom; en_US; 314665256)"
        )
        # Fallback: Facebook link-preview bot for og:title + embedded JSON detection
        _UA_PREVIEW = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"

        results: dict = {
            "checked": 0,
            "generated": len(usernames),
            "found": [],
            "errors": 0,
            "blocked": False,
        }
        kws = [k.lower() for k in (keywords or [])]

        api_sess = _req.Session()
        api_sess.headers.update({
            "User-Agent": _UA_APP,
            "x-ig-app-id": "936619743392459",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        web_sess = _req.Session()
        web_sess.headers.update({
            "User-Agent": _UA_PREVIEW,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

        use_api = True          # flip to False on 429/403
        consecutive_misses = 0  # confirmed False (not found) only
        wall_hits = 0           # None (inconclusive / login wall)
        PRIORITY_ZONE = 20

        def _via_api(un: str) -> "tuple[bool | None, str]":
            nonlocal use_api
            try:
                r = api_sess.get(
                    "https://i.instagram.com/api/v1/users/web_profile_info/",
                    params={"username": un},
                    timeout=10,
                )
                if r.status_code == 200:
                    user = r.json().get("data", {}).get("user")
                    if user and user.get("username", "").lower() == un.lower():
                        return True, user.get("full_name", "")
                    return False, ""
                if r.status_code == 404:
                    return False, ""
                if r.status_code in (429, 403, 401):
                    use_api = False
                    return None, ""
            except Exception:
                pass
            return None, ""

        def _via_web(un: str) -> "tuple[bool | None, str]":
            try:
                r = web_sess.get(
                    f"https://www.instagram.com/{un}/",
                    timeout=10, allow_redirects=True,
                )
                if r.status_code == 404:
                    return False, ""
                if r.status_code not in (200, 301, 302):
                    return None, ""
                txt = r.text

                # Method A: og:title contains (@username)
                m_og = re.search(
                    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']'
                    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
                    txt, re.IGNORECASE,
                )
                og_title = (m_og.group(1) or m_og.group(2) or "").strip() if m_og else ""
                if f"(@{un.lower()})" in og_title.lower():
                    m = re.match(r"^(.+?)\s*\(@", og_title)
                    return True, m.group(1).strip() if m else ""

                # Method B: username literal appears in embedded JSON payload
                if re.search(
                    rf'"username"\s*:\s*"{re.escape(un)}"',
                    txt, re.IGNORECASE,
                ):
                    m_dn = re.search(r'"full_name"\s*:\s*"([^"]+)"', txt)
                    return True, m_dn.group(1) if m_dn else ""

                # If page is a login wall, we can't tell — return None
                tl = txt.lower()
                if "log in" in tl or "login" in tl or "connexion" in tl:
                    return None, ""
                return False, ""
            except Exception:
                return None, ""

        for idx, un in enumerate(usernames[:80]):
            results["checked"] += 1
            found: "bool | None" = None
            display_name = ""

            if use_api:
                found, display_name = _via_api(un)

            if found is None:
                found, display_name = _via_web(un)

            if found is True:
                consecutive_misses = 0
                first_seen = None
                try:
                    wb = _req.get(
                        "https://web.archive.org/cdx/search/cdx",
                        params={
                            "url": f"instagram.com/{un}",
                            "output": "json", "limit": 1,
                            "from": "2010", "fl": "timestamp",
                            "filter": "statuscode:200",
                        },
                        timeout=5,
                    )
                    if wb.status_code == 200:
                        wb_data = wb.json()
                        if len(wb_data) >= 2:
                            ts = wb_data[1][0]
                            first_seen = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
                except Exception:
                    pass
                score = _relevance(display_name, un, firstname, lastname, kws)
                results["found"].append({
                    "username":     un,
                    "display_name": display_name,
                    "url":          f"https://www.instagram.com/{un}/",
                    "first_seen":   first_seen,
                    "relevance":    score,
                })
            elif found is False:
                consecutive_misses += 1
                # Stop only after priority zone when we have many confirmed misses
                if consecutive_misses >= 15 and idx >= PRIORITY_ZONE:
                    results["blocked"] = True
                    break
            else:
                # None = inconclusive (login wall, timeout) — don't count as miss
                wall_hits += 1
                # If blocked everywhere past priority zone, give up
                if wall_hits >= 20 and idx >= PRIORITY_ZONE and not use_api:
                    results["blocked"] = True
                    break

            time.sleep(0.25)
            if len([p for p in results["found"] if p["relevance"] >= 5]) >= 5:
                break

        results["found"].sort(key=lambda x: x["relevance"], reverse=True)
        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def _search_social_platforms_direct(
    usernames: list[str],
    firstname: str = "",
    lastname: str = "",
    keywords: list[str] | None = None,
) -> dict:
    """
    Check username candidates across Twitter/X, TikTok, Snapchat, BeReal
    and LinkedIn via HTML title detection (parallel, one thread per platform).
    Facebook is included as a manual search URL only (requires auth).
    """
    _UA_DESK = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    _PLAT_CFG = {
        # Twitter/X is a SPA — title requires JS rendering (Playwright fallback)
        "twitter":  {"label": "Twitter/X",  "url": "https://x.com/{}",                  "needs_browser": True},
        "snapchat": {"label": "Snapchat",   "url": "https://www.snapchat.com/add/{}",   "needs_browser": False},
        "telegram": {"label": "Telegram",   "url": "https://t.me/{}",                   "needs_browser": False},
        # BeReal: bere.al/{username} (new format, without @) returns same page for all
        # usernames → unverifiable without auth. Candidates only.
        "bereal":   {"label": "BeReal",     "url": "https://bere.al/{}",                "needs_browser": False, "unverifiable": True},
    }

    fn_l = firstname.lower().translate(_ACCENT_MAP) if firstname else ""
    ln_l = lastname.lower().translate(_ACCENT_MAP)  if lastname  else ""
    kws  = [k.lower() for k in (keywords or [])]

    def _get_title(html: str) -> str:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _detect(plat: str, title: str, status: int, username: str) -> tuple[bool, str]:
        """Return (profile_found, display_name)."""
        tl = title.lower()
        un = username.lower()
        if plat == "twitter":
            if f"(@{un})" in tl:
                m = re.match(r"^(.+?)\s*\(@", title.strip())
                return True, (m.group(1).strip() if m else "")
        elif plat == "tiktok":
            if f"(@{un})" in tl:
                m = re.match(r"^(.+?)\s*\(@", title.strip())
                return True, (m.group(1).strip() if m else "")
            if un in tl and "tiktok" in tl and "make your day" not in tl and "trends" not in tl:
                m = re.match(r"^(.+?)\s*[|]", title.strip())
                dn = m.group(1).strip() if m else ""
                if dn and dn.lower() != "tiktok" and len(dn) > 1:
                    return True, dn
        elif plat == "snapchat":
            # Only the strict "@username | Snapchat" pattern — avoids false positives
            # where Snapchat echoes the username in a generic "not found" page
            if f"@{un}" in tl and "snapchat" in tl:
                return True, ""
        elif plat == "linkedin":
            bad = ("sign in", "log in", "join now", "page not found",
                   "profile not found", "linkedin login", "error")
            if any(b in tl for b in bad):
                return False, ""
            if "linkedin" in tl and len(tl) > 15:
                m = re.match(r"^(.+?)\s*[-–|]", title.strip())
                dn = m.group(1).strip() if m else ""
                if dn and len(dn) > 2 and "linkedin" not in dn.lower():
                    return True, dn
        elif plat == "telegram":
            # "Telegram: View @username" → public account exists
            # "Telegram: Contact @username" → username doesn't exist (generic contact page)
            if f"@{un}" in tl:
                if re.search(r"(?i)telegram\s*:\s*view\b", title):
                    m = re.match(r"(?i)telegram\s*:\s*view\s+@?(.+)", title.strip())
                    raw = m.group(1).strip() if m else ""
                    dn = "" if raw.lower() == un.lower() else raw
                    return True, dn
                # "Contact" page = generic fallback, does NOT confirm existence
                return False, ""
            # Channel/bot without @ in title (e.g. "Channel Name | Telegram")
            if status == 200 and tl and tl != "telegram" and len(tl) > 3:
                skip = ("error", "not found", "404", "join telegram", "sign up",
                        "log in", "contact", "send message")
                if not any(w in tl for w in skip):
                    m2 = re.match(r"^(.+?)\s*(?:[-–—|]\s*telegram)?\s*$", title.strip(), re.I)
                    ch_name = m2.group(1).strip() if m2 else ""
                    if ch_name and ch_name.lower() != "telegram" and len(ch_name) > 2:
                        return True, ch_name
        elif plat == "bereal":
            # BeReal now returns same template for all usernames (real or fake).
            # Cannot verify existence without auth — always return False.
            return False, ""
        return False, ""

    def _score(dn: str, un: str) -> int:
        d = dn.lower().translate(_ACCENT_MAP) if dn else ""
        u = un.lower()
        s = 0
        if ln_l and ln_l in d: s += 5
        if fn_l and fn_l in d: s += 4
        for kw in kws[:4]:
            if kw in u:  s += 3
            elif kw in d: s += 3
        # Penalise when display name is known but name parts don't match
        # — avoids surfacing accounts with only partial name coincidence
        if fn_l and len(fn_l) > 1 and d and fn_l not in d:
            s -= 4   # firstname mismatch (e.g. "Corentin" for target "Chloé")
        if ln_l and len(ln_l) > 2 and d and ln_l not in d:
            s -= 3   # lastname mismatch (e.g. "Nelson" for target "Gernigon")
        return max(0, min(s, 10))

    def _fetch_title_browser(url: str) -> tuple[int, str]:
        """Render url with Playwright and return (status, title)."""
        try:
            from skills.utils.browser import BrowserSession
            with BrowserSession() as b:
                status, html = b.fetch(url, networkidle_timeout=6000)
                return status, _get_title(html)
        except Exception:
            return 0, ""

    def _check_platform(plat: str, cfg: dict, candidates: list[str]) -> tuple[str, dict]:
        import requests as _req
        import time

        # BeReal: unverifiable — return candidates only (no actual HTTP check)
        if cfg.get("unverifiable"):
            cands = [
                {"slug": un, "url": cfg["url"].format(un), "note": "unverified"}
                for un in candidates
            ]
            return plat, {"label": cfg["label"], "found": [], "candidates": cands,
                          "checked": 0, "unverifiable": True}

        out: dict = {"label": cfg["label"], "found": [], "checked": 0}
        needs_browser = cfg.get("needs_browser", False)

        sess = _req.Session()
        sess.headers.update({
            "User-Agent": _UA_DESK,
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })

        for username in candidates:
            out["checked"] += 1
            try:
                url = cfg["url"].format(username)
                if needs_browser:
                    status_code, title = _fetch_title_browser(url)
                else:
                    r = sess.get(url, timeout=8, allow_redirects=True)
                    status_code = r.status_code
                    title = _get_title(r.text)

                found, dn = _detect(plat, title, status_code, username)
                if found:
                    rel = _score(dn, username)
                    # Drop accounts where display name is known but first name
                    # clearly doesn't match — wrong person, not just low confidence
                    d_low = dn.lower().translate(_ACCENT_MAP) if dn else ""
                    # If display name is known but score is very low, the account
                    # is almost certainly a different person — drop it
                    if d_low and rel < 3:
                        continue
                    out["found"].append({
                        "username":     username,
                        "display_name": dn,
                        "url":          url,
                        "relevance":    rel,
                    })
            except Exception:
                pass
            time.sleep(0.3)

        out["found"].sort(key=lambda x: x["relevance"], reverse=True)
        return plat, out

    def _fetch() -> dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        candidates = usernames[:10]
        result: dict = {}
        with ThreadPoolExecutor(max_workers=len(_PLAT_CFG)) as pool:
            futures = {
                pool.submit(_check_platform, plat, cfg, candidates): plat
                for plat, cfg in _PLAT_CFG.items()
            }
            for fut in as_completed(futures):
                pk, pr = fut.result()
                result[pk] = pr
        # Facebook: direct check unreliable without auth → manual search URL
        fb_q = " ".join(filter(None, [firstname, lastname]))
        result["facebook"] = {
            "label":      "Facebook",
            "found":      [],
            "checked":    0,
            "search_url": f"https://www.facebook.com/search/people/?q={fb_q.replace(' ', '+')}" if fb_q else "",
        }
        return result

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


# Sites most relevant for missing persons OSINT.
# Used by both maigret and sherlock to avoid scanning 500+ irrelevant sites.
_MISSING_PERSONS_SITES: list[str] = [
    # Location / Sport — GPS routes, check-ins, last known location
    "Strava", "Komoot", "AllTrails", "Wikiloc", "Geocaching",
    "Garmin", "Foursquare", "Swarm", "Runkeeper",
    # Marketplace — city in listings, last activity date
    "LeBonCoin", "Vinted", "BlaBlaCar", "Airbnb", "Etsy", "eBay",
    # Social — last post date, location clues in posts
    "Reddit", "Twitter", "Instagram", "TikTok", "Snapchat",
    "Telegram", "Discord", "Pinterest", "Tumblr", "Flickr", "Mastodon",
    # Gaming — last online timestamp
    "Steam", "Twitch", "Xbox", "PlayStation",
    # Professional / other
    "GitHub", "LinkedIn", "Spotify", "SoundCloud",
]

_LOCATION_SITES_LOW = {
    "strava", "komoot", "garmin", "alltrails", "geocaching", "wikiloc",
    "runkeeper", "foursquare", "swarm",
}
_MARKETPLACE_SITES_LOW = {
    "leboncoin", "vinted", "blablacar", "airbnb", "etsy", "ebay",
}
_GAMING_SITES_LOW = {
    "steam", "twitch", "xbox", "playstation",
}
_LOCATION_TAGS = {"sport", "fitness", "geolocation", "travel", "outdoors", "running", "cycling"}
_GAMING_TAGS   = {"gaming", "game", "games"}


async def _run_maigret_direct(usernames: list[str]) -> dict:
    """
    Targeted maigret scan on missing-person-relevant sites only.
    No username cap — pre-validation already filtered to real candidates.
    """
    def _fetch() -> dict:
        import subprocess, tempfile, os, json as _json, shutil

        results: dict = {
            "checked_usernames": [],
            "found": {},
            "location_relevant": [],
            "marketplace":       [],
            "gaming":            [],
            "social":            [],
            "total_found":       0,
            "not_installed":     False,
        }

        site_flags: list[str] = []
        for s in _MISSING_PERSONS_SITES:
            site_flags.extend(["--site", s])

        tmpdir = tempfile.mkdtemp(prefix="paw_maigret_")
        try:
            for username in usernames:
                results["checked_usernames"].append(username)
                try:
                    subprocess.run(
                        [
                            "maigret", username,
                            "--timeout", "10",
                            "--retries", "1",
                            "--workers",  "20",
                            "--folderoutput", tmpdir,
                            *site_flags,
                        ],
                        capture_output=True, text=True, timeout=180,
                    )

                    json_path = os.path.join(tmpdir, f"{username}.json")
                    if not os.path.exists(json_path):
                        existing = [f for f in os.listdir(tmpdir) if f.endswith(".json")]
                        if not existing:
                            continue
                        json_path = os.path.join(tmpdir, existing[-1])

                    with open(json_path, encoding="utf-8") as f:
                        data = _json.load(f)

                    found_profiles: list[dict] = []
                    for site_name, site_info in data.get("sites", {}).items():
                        status = site_info.get("status", {})
                        claimed = (
                            status.get("status") == "Claimed"
                            if isinstance(status, dict)
                            else str(status) == "Claimed"
                        )
                        if not claimed:
                            continue

                        tags      = site_info.get("tags", [])
                        category  = str(site_info.get("category", "")).lower()
                        url       = site_info.get("url_user", "")
                        tags_low  = {t.lower() for t in tags}
                        site_low  = site_name.lower()

                        entry = {"site": site_name, "url": url, "tags": tags, "category": category}
                        found_profiles.append(entry)
                        results["total_found"] += 1

                        if site_low in _LOCATION_SITES_LOW or tags_low & _LOCATION_TAGS:
                            results["location_relevant"].append({**entry, "username": username})
                        elif site_low in _MARKETPLACE_SITES_LOW or "marketplace" in tags_low or "shopping" in tags_low:
                            results["marketplace"].append({**entry, "username": username})
                        elif site_low in _GAMING_SITES_LOW or tags_low & _GAMING_TAGS or "gaming" in category:
                            results["gaming"].append({**entry, "username": username})
                        else:
                            results["social"].append({**entry, "username": username})

                    results["found"][username] = found_profiles

                except FileNotFoundError:
                    results["not_installed"] = True
                    break
                except subprocess.TimeoutExpired:
                    # Replace the last entry with a timeout marker
                    if results["checked_usernames"] and results["checked_usernames"][-1] == username:
                        results["checked_usernames"][-1] = f"{username}(timeout)"
                except Exception as exc:
                    results.setdefault("errors", []).append(f"{username}: {exc}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def _run_sherlock_direct(usernames: list[str]) -> dict:
    """
    Targeted sherlock scan on missing-person-relevant sites only.
    Uses the shared _MISSING_PERSONS_SITES list via --site flags.
    """
    def _fetch() -> dict:
        import subprocess

        results: dict = {
            "checked_usernames": [],
            "found": {},
            "location_relevant": [],
            "marketplace": [],
            "gaming": [],
            "social": [],
            "total_found": 0,
            "not_installed": False,
        }

        site_flags: list[str] = []
        for s in _MISSING_PERSONS_SITES:
            site_flags.extend(["--site", s])

        import tempfile, shutil as _sh
        for username in usernames:
            results["checked_usernames"].append(username)
            _tmp = tempfile.mkdtemp(prefix="paw_sh_")
            try:
                proc = subprocess.run(
                    [
                        "sherlock", username,
                        "--print-found",
                        "--no-color",
                        "--timeout", "10",
                        *site_flags,
                    ],
                    capture_output=True, text=True, timeout=180,
                    cwd=_tmp,
                )
                found_profiles: list[dict] = []
                for line in proc.stdout.splitlines():
                    if not line.startswith("[+]"):
                        continue
                    m = re.match(r"\[\+\]\s+(.+?):\s+(https?://\S+)", line)
                    if not m:
                        continue
                    site = m.group(1).strip()
                    url  = m.group(2).strip()
                    site_low = site.lower()
                    entry = {"site": site, "url": url, "tags": [], "category": "social"}
                    found_profiles.append(entry)
                    results["total_found"] += 1
                    if site_low in _LOCATION_SITES_LOW:
                        results["location_relevant"].append({**entry, "username": username})
                    elif site_low in _MARKETPLACE_SITES_LOW:
                        results["marketplace"].append({**entry, "username": username})
                    elif site_low in _GAMING_SITES_LOW:
                        results["gaming"].append({**entry, "username": username})
                    else:
                        results["social"].append({**entry, "username": username})
                results["found"][username] = found_profiles

            except FileNotFoundError:
                results["not_installed"] = True
                break
            except subprocess.TimeoutExpired:
                if results["checked_usernames"] and results["checked_usernames"][-1] == username:
                    results["checked_usernames"][-1] = f"{username}(timeout)"
            except Exception as exc:
                results.setdefault("errors", []).append(f"{username}: {exc}")
            finally:
                _sh.rmtree(_tmp, ignore_errors=True)

        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def _ig_lookup_by_email(email: str, phone: str = "") -> dict:
    """
    Instagram private API: given an email, returns obfuscated email/phone of the
    Instagram account registered with it. No auth required (may rate-limit at 429).

    Based on: POST https://i.instagram.com/api/v1/users/lookup/
    Returns: {status, obfuscated_email, obfuscated_phone, phone_match}
    """
    def _lookup() -> dict:
        import requests as _req
        import warnings
        warnings.filterwarnings("ignore", message="Unverified HTTPS")
        url = "https://i.instagram.com/api/v1/users/lookup/"
        headers = {
            "User-Agent":   "Instagram 101.0.0.15.120",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        signed_body = (
            f'.[{{"login_attempt_count":"0","directly_sign_in":"true",'
            f'"source":"default","q":"{email}","ig_sig_key_version":"4"}}]'
        )
        data = {"ig_sig_key_version": "4", "signed_body": signed_body}
        try:
            r = _req.post(url, headers=headers, data=data, verify=False, timeout=20)
            if r.status_code == 200:
                res = r.json()
                obfu_email = res.get("obfuscated_email", "")
                obfu_phone = res.get("obfuscated_phone", "")
                phone_match = False
                if phone and obfu_phone:
                    cp = phone.lstrip("+")
                    co = obfu_phone.lstrip("+")
                    if (len(cp) >= 3 and len(co) >= 3
                            and cp[1:3] == co[1:3] and cp[-2:] == co[-2:]):
                        phone_match = True
                return {
                    "status":           "found",
                    "obfuscated_email": obfu_email,
                    "obfuscated_phone": obfu_phone,
                    "phone_match":      phone_match,
                    "email":            email,
                }
            elif r.status_code == 429:
                return {"status": "rate_limited", "email": email}
            else:
                return {"status": "not_found", "email": email}
        except Exception as exc:
            return {"status": "error", "error": str(exc), "email": email}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _lookup)


async def _enrich_activity_signals(maigret_found: dict) -> dict:
    """
    Fetch last-activity date + location hints from key found profiles.
    Covers Reddit (public JSON API) and GitHub (public REST API).
    """
    def _fetch() -> dict:
        import requests as _req
        from datetime import datetime, timezone

        _UA = "Mozilla/5.0 (compatible; PAW-OSINT/1.0; +https://github.com/c0dejump)"
        enriched: dict = {}

        # Build a site→username lookup from all checked usernames
        site_map: dict[str, str] = {}
        for uname, profiles in maigret_found.get("found", {}).items():
            for p in profiles:
                key = p["site"].lower()
                if key not in site_map:
                    site_map[key] = uname

        # ── Reddit ────────────────────────────────────────────
        if "reddit" in site_map:
            reddit_user = site_map["reddit"]
            try:
                r = _req.get(
                    f"https://www.reddit.com/user/{reddit_user}/overview.json",
                    params={"limit": 10, "sort": "new"},
                    headers={"User-Agent": _UA, "Accept": "application/json"},
                    timeout=10,
                )
                if r.status_code == 200:
                    children = r.json().get("data", {}).get("children", [])
                    if children:
                        ts = children[0]["data"].get("created_utc", 0)
                        last_dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                        subs = list(dict.fromkeys(
                            c["data"].get("subreddit", "") for c in children
                            if c["data"].get("subreddit")
                        ))[:8]
                        enriched["reddit"] = {
                            "username":    reddit_user,
                            "last_ts":     int(ts),
                            "last_active": last_dt,
                            "subreddits":  subs,
                            "url": f"https://www.reddit.com/user/{reddit_user}",
                        }
            except Exception:
                pass

        # ── GitHub ────────────────────────────────────────────
        if "github" in site_map:
            gh_user = site_map["github"]
            try:
                r = _req.get(
                    f"https://api.github.com/users/{gh_user}",
                    headers={"User-Agent": _UA, "Accept": "application/vnd.github.v3+json"},
                    timeout=8,
                )
                if r.status_code == 200:
                    d = r.json()
                    enriched["github"] = {
                        "username":    gh_user,
                        "name":        d.get("name", ""),
                        "location":    d.get("location", ""),
                        "bio":         d.get("bio", ""),
                        "last_active": (d.get("updated_at") or "")[:10],
                        "public_repos": d.get("public_repos", 0),
                        "url":         d.get("html_url", ""),
                    }
            except Exception:
                pass

        # ── Steam (gaming — last online timestamp) ─────────────
        # The exact `lastlogoff` is the single most valuable signal for a
        # missing-person case. Uses the official Web API when STEAM_API_KEY
        # is set, otherwise falls back to the public community XML endpoint.
        def _steam_summary(vanity: str) -> dict | None:
            api_key = os.environ.get("STEAM_API_KEY", "").strip()
            _STATE = {0: "offline", 1: "online", 2: "busy", 3: "away",
                      4: "snooze", 5: "looking to trade", 6: "looking to play"}
            steamid: str | None = None
            profile_url = f"https://steamcommunity.com/id/{vanity}"

            # A 17-digit vanity is already a SteamID64 (/profiles/ URL).
            if vanity.isdigit() and len(vanity) == 17:
                steamid = vanity
                profile_url = f"https://steamcommunity.com/profiles/{vanity}"
            elif api_key:
                try:
                    rv = _req.get(
                        "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/",
                        params={"key": api_key, "vanityurl": vanity},
                        timeout=8,
                    )
                    if rv.ok:
                        jr = rv.json().get("response", {})
                        if jr.get("success") == 1:
                            steamid = jr.get("steamid")
                except Exception:
                    pass

            # ── API path — exact lastlogoff ──
            if api_key and steamid:
                try:
                    rs = _req.get(
                        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
                        params={"key": api_key, "steamids": steamid},
                        timeout=8,
                    )
                    if rs.ok:
                        players = rs.json().get("response", {}).get("players", [])
                        if players:
                            p = players[0]
                            out = {
                                "username": vanity,
                                "steamid":  steamid,
                                "persona":  p.get("personaname", ""),
                                "status":   _STATE.get(p.get("personastate", 0), "offline"),
                                "url":      p.get("profileurl", profile_url),
                                "source":   "api",
                            }
                            if p.get("lastlogoff"):
                                ts = int(p["lastlogoff"])
                                out["last_ts"]     = ts
                                out["last_active"] = datetime.fromtimestamp(
                                    ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                            if p.get("loccountrycode"):
                                out["country"] = p["loccountrycode"]
                            if p.get("timecreated"):
                                out["member_since"] = datetime.fromtimestamp(
                                    int(p["timecreated"]), tz=timezone.utc).strftime("%Y-%m-%d")
                            if p.get("gameextrainfo"):
                                out["in_game"] = p["gameextrainfo"]
                            return out
                except Exception:
                    pass

            # ── Fallback — public community XML (no key needed) ──
            try:
                rx = _req.get(profile_url, params={"xml": 1},
                              headers={"User-Agent": _UA}, timeout=8)
                if rx.ok and "<profile>" in rx.text:
                    def _x(tag: str) -> str:
                        m = re.search(
                            rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>",
                            rx.text, re.S,
                        )
                        return re.sub(r"<[^>]+>", " ", m.group(1)).strip() if m else ""
                    sid       = _x("steamID64")
                    persona   = _x("steamID")
                    state     = _x("onlineState")     # online / offline / in-game
                    state_msg = _x("stateMessage")    # e.g. "Last Online 5 days ago"
                    location  = _x("location")
                    member    = _x("memberSince")
                    if sid or persona:
                        out = {
                            "username": vanity,
                            "steamid":  sid,
                            "persona":  persona,
                            "status":   state or "offline",
                            "url":      profile_url,
                            "source":   "scrape",
                        }
                        if state_msg:
                            out["status_message"] = state_msg
                        if location:
                            out["country"] = location
                        if member:
                            out["member_since"] = member
                        return out
            except Exception:
                pass
            return None

        if "steam" in site_map:
            steam_data = _steam_summary(site_map["steam"])
            if steam_data:
                enriched["steam"] = steam_data

        # ── Twitter/X quick existence + bio location ──────────
        if "twitter" in site_map:
            tw_user = site_map["twitter"]
            try:
                r = _req.get(
                    f"https://twitter.com/{tw_user}",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"},
                    timeout=8, allow_redirects=True,
                )
                m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', r.text)
                if m:
                    enriched["twitter"] = {
                        "username": tw_user,
                        "bio_snippet": m.group(1)[:200],
                        "url": f"https://twitter.com/{tw_user}",
                    }
            except Exception:
                pass

        # ── Location/Sport & Marketplace profile enrichment ────
        # Scrape publicly accessible profiles for city + last activity date.
        # Uses JSON-LD (most reliable) then og:description fallback.
        import json as _json2

        def _extract_jsonld_city(html: str) -> str | None:
            for raw in re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                html, re.S | re.I,
            ):
                try:
                    obj = _json2.loads(raw)
                    items = obj if isinstance(obj, list) else [obj]
                    for item in items:
                        addr = item.get("address") or item.get("location") or {}
                        if isinstance(addr, dict):
                            city = addr.get("addressLocality") or addr.get("name")
                            if city:
                                return str(city).strip()
                        city = item.get("addressLocality")
                        if city:
                            return str(city).strip()
                except Exception:
                    pass
            return None

        def _extract_og_desc(html: str) -> str:
            m = re.search(
                r'<meta[^>]+(?:name=["\']description["\']|property=["\']og:description["\'])[^>]+content=["\']([^"\']{10,})["\']',
                html, re.I,
            )
            return m.group(1).strip() if m else ""

        ENRICH_SITES = {
            "vinted":    {"icon": "👗", "label": "Vinted"},
            "strava":    {"icon": "🏃", "label": "Strava"},
            "komoot":    {"icon": "🚴", "label": "Komoot"},
            "leboncoin": {"icon": "🛒", "label": "Leboncoin"},
        }

        # Collect all profiles from location_relevant + marketplace lists
        all_enrichable: list[dict] = (
            maigret_found.get("location_relevant", []) +
            maigret_found.get("marketplace", [])
        )

        for profile in all_enrichable:
            site_l = profile.get("site", "").lower()
            url    = profile.get("url", "")
            uname  = profile.get("username", "")
            if not url or not uname:
                continue
            for site_key, meta in ENRICH_SITES.items():
                if site_key in site_l and site_key not in enriched:
                    try:
                        r = _req.get(
                            url,
                            headers={"User-Agent": _UA, "Accept-Language": "fr-FR,fr;q=0.9"},
                            timeout=8,
                            allow_redirects=True,
                        )
                        if r.status_code != 200:
                            continue
                        # Skip login walls (Strava, etc.)
                        if any(w in r.text[:3000].lower() for w in ("log in", "sign in", "connexion requise")):
                            continue
                        city = _extract_jsonld_city(r.text)
                        if not city:
                            # Vinted og:description: "...à Toulouse..."
                            desc = _extract_og_desc(r.text)
                            if desc:
                                cm = re.search(r'[àa]\s+([A-ZÀ-Ÿ][a-zA-ZÀ-ÿ\- ]{2,30}?)(?:[,.\)]|$)', desc)
                                if cm:
                                    city = cm.group(1).strip()
                        if city:
                            enriched[site_key] = {
                                "username": uname,
                                "url":      url,
                                "city":     city,
                                "icon":     meta["icon"],
                                "label":    meta["label"],
                            }
                    except Exception:
                        pass

        return enriched

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def _search_sirene_pappers_direct(
    firstname: str, lastname: str, cities: list[str]
) -> dict:
    """
    Search French business registries:
    - SIRENE (opendatasoft, free, no key) — finds natural persons registered as businesses
    - Pappers (requires PAPPERS_API_KEY) — finds company directors by name
    """
    import requests as _req

    _UA_D = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

    def _fetch() -> dict:
        results: dict = {
            "sirene": [], "pappers": [],
            "total_sirene": 0, "total_pappers": 0,
        }
        headers = {"User-Agent": _UA_D, "Accept": "application/json"}

        # ── SIRENE via opendatasoft (free, no key) ────────────
        try:
            where_parts = [f"nomunitelegale='{lastname.upper()}'"]
            if firstname:
                where_parts.append(f"prenom1unitelegale='{firstname.upper()}'")
            r = _req.get(
                "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets"
                "/economicref-france-sirene-v3/records",
                params={
                    "where": " AND ".join(where_parts),
                    "limit": 10,
                    "fields": ",".join([
                        "siren", "nomunitelegale", "prenom1unitelegale",
                        "denominationunitelegale", "etatadministratifunitelegale",
                        "activiteprincipaleunitelegale", "datecreationunitelegale",
                        "libellecommuneetablissement", "codedepartementetablissement",
                        "adresseetablissement", "categoriejuridiqueunitelegale",
                    ]),
                },
                headers=headers, timeout=12,
            )
            if r.status_code == 200:
                data = r.json()
                results["total_sirene"] = data.get("total_count", 0)
                seen: set = set()
                for item in (data.get("results") or [])[:10]:
                    siren = item.get("siren", "")
                    if siren in seen:
                        continue
                    seen.add(siren)
                    nom    = item.get("nomunitelegale", "")
                    prenom = item.get("prenom1unitelegale", "")
                    denom  = item.get("denominationunitelegale") or ""
                    name   = f"{prenom} {nom}".strip() if nom else denom
                    results["sirene"].append({
                        "siren":    siren,
                        "name":     name,
                        "company":  denom or None,
                        "status":   item.get("etatadministratifunitelegale", ""),
                        "activity": item.get("activiteprincipaleunitelegale", ""),
                        "created":  (item.get("datecreationunitelegale") or "")[:4],
                        "city":     item.get("libellecommuneetablissement", ""),
                        "dept":     item.get("codedepartementetablissement", ""),
                        "address":  item.get("adresseetablissement", ""),
                    })
        except Exception as exc:
            results["sirene_error"] = str(exc)

        # ── Pappers dirigeants (requires PAPPERS_API_KEY) ─────
        pappers_key = os.environ.get("PAPPERS_API_KEY", "").strip()
        if pappers_key:
            try:
                r2 = _req.get(
                    "https://api.pappers.fr/v2/recherche-dirigeants",
                    params={
                        "q":         f"{firstname} {lastname}".strip(),
                        "api_token": pappers_key,
                        "par_page":  10,
                    },
                    headers=headers, timeout=12,
                )
                if r2.status_code == 200:
                    data2 = r2.json()
                    results["total_pappers"] = data2.get("total", 0)
                    for d in (data2.get("dirigeants") or [])[:10]:
                        companies = [
                            {
                                "name":   c.get("nom_entreprise", ""),
                                "siren":  c.get("siren", ""),
                                "role":   c.get("qualite", ""),
                                "form":   c.get("forme_juridique", ""),
                                "status": c.get("statut_rcs", ""),
                            }
                            for c in (d.get("entreprises") or [])[:5]
                        ]
                        results["pappers"].append({
                            "name":      f"{d.get('prenom','')} {d.get('nom','')}".strip(),
                            "companies": companies,
                        })
                elif r2.status_code == 401:
                    results["pappers_error"] = "invalid_api_key"
            except Exception as exc:
                results["pappers_error"] = str(exc)
        else:
            results["pappers_note"] = "PAPPERS_API_KEY not configured — add it in Configuration"

        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


def _get_backend() -> str:
    """Read LLM_BACKEND fresh from .env each time — picks up config changes without restart."""
    load_dotenv(dotenv_path=_ENV_PATH, override=True)
    return os.environ.get("LLM_BACKEND", "ollama/llama3.1")

# ANSI colours (used when printing to terminal)
R   = "\033[0m"
B   = "\033[36m"
Y   = "\033[33m"
G   = "\033[32m"
Rd  = "\033[31m"
Mg  = "\033[35m"
Bl  = "\033[34m"
Bld = "\033[1m"


def _make_emit(cb: Optional[Callable[[str], None]]):
    """Return a function that either calls the callback or prints."""
    if cb is None:
        def emit(text: str): print(text)
    else:
        def emit(text: str): cb(text)
    return emit


ALL_MODULES = ["demographics", "diplomas", "email", "phone", "social_media"]


async def run_agent(
    firstname: str,
    lastname: str,
    birth_year: str,
    keywords: list[str],
    cities: list[str] | None = None,
    phone: str = "",
    pseudo: str = "",
    modules: list[str] | None = None,
    callback: Optional[Callable[[str], None]] = None,
    report_callback: Optional[Callable[[dict], None]] = None,
    event_callback: Optional[Callable[[dict], None]] = None,
    confirmation_wait: Optional[Callable[[], str]] = None,
) -> None:
    """
    Main entry point. callback(line) is called for every output line.
    report_callback(report_dict) is called once at the end with structured findings.
    modules: list of module names to run (default: all). Supported: demographics, diplomas, email
    If callback is None, output goes to stdout (CLI mode).
    """
    emit = _make_emit(callback)
    backend = _get_backend() if USE_LLM else None

    server_script = os.path.join(os.path.dirname(__file__), "mcp_server.py")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_script],
        env=os.environ.copy(),
    )

    emit(f"{'━' * 54}")
    emit(f"  EMAIL OSINT AGENT  [MCP + {backend if USE_LLM else 'direct pipeline'}]")
    emit(f"{'━' * 54}")

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools_response = await session.list_tools()
                tools = tools_response.tools
                emit(f"  ✓  {len(tools)} MCP tools available: {', '.join(t.name for t in tools)}")
                emit("")

                active_modules = list(modules) if modules else list(ALL_MODULES)
                if USE_LLM:
                    await _run_with_llm(session, tools, firstname, lastname, birth_year, keywords, cities or [], phone, pseudo, active_modules, emit, backend, report_callback, event_callback, confirmation_wait)
                else:
                    await _run_pipeline(session, firstname, lastname, birth_year, keywords, cities or [], phone, pseudo, active_modules, emit, report_callback, event_callback, confirmation_wait)
    except BaseException as exc:
        # Unwrap anyio ExceptionGroup so the real error is visible
        inner = getattr(exc, "exceptions", None)
        if inner:
            for sub in inner:
                emit(f"  ✗  MCP error: {type(sub).__name__}: {sub}")
        else:
            emit(f"  ✗  MCP error: {type(exc).__name__}: {exc}")


async def _run_with_llm(session, tools, firstname, lastname, birth_year, keywords, cities, phone, pseudo, modules, emit, backend, report_callback=None, event_callback=None, confirmation_wait=None):
    """
    Hybrid mode:
      Step 1 — LLM calls generate_permutations (forced tool_choice, up to 3 tries)
      Step 2 — Code calls validate_all deterministically
      Step 3 — Code calls check_hibp for each valid email
      Step 4 — LLM writes the final summary
    """
    # ── Enrich keywords with city/dept codes ─────────────────
    city_extras = _cities_to_keywords(cities)
    all_keywords = list(keywords)
    for k in city_extras:
        if k not in all_keywords:
            all_keywords.append(k)
    if city_extras:
        emit(f"  🏙️  Cities → extra keywords: {', '.join(city_extras)}")

    kw_str = ", ".join(all_keywords) if all_keywords else "none"

    # ── Report accumulator ────────────────────────────────────
    report: dict = {
        "target":       {"firstname": firstname, "lastname": lastname,
                         "birth_year": birth_year, "keywords": all_keywords,
                         "cities": cities},
        "demographics": {},
        "diplomas":     {"theses": [], "publications": [], "bac_results": [], "brevet_results": [], "total_theses": 0, "total_pubs": 0, "total_bac": 0, "total_brevet": 0},
        "business":     {"sirene": [], "pappers": [], "total_sirene": 0, "total_pappers": 0},
        "phone":        {},
        "social_media": {},
        "timeline":     {},
        "emails":       {"smtp_valid": [], "ghunt_confirmed": [], "breached": []},
        "ghunt_details": [],
        "hibp_details":  [],
        "llm_summary":  "",
        "risk_level":   "none",
    }

    # ── Step 0: Etymology (lastname context, best-effort) ─────
    if "demographics" in modules and lastname:
        emit(f"  💭 [Step 0] Surname demographics — {lastname}…")
        try:
            ety_args: dict = {"lastname": lastname}
            if birth_year:
                ety_args["birth_year"] = birth_year
            raw = await session.call_tool("check_etymology", ety_args)
            raw_text = raw.content[0].text if raw.content else "{}"
            ety = json.loads(raw_text)
            if ety.get("bearers_since_1890"):
                n_dept = ety.get("departments_count", "?")
                rank   = ety.get("national_rank", "?")
                emit(f"  👥  {ety['bearers_since_1890']} bearers since 1890 — {n_dept} department(s) — national rank: {rank}")
            if ety.get("birth_year_context"):
                emit(f"  📅  Birth year {birth_year}: {ety['birth_year_context']}")
            dist = ety.get("geographic_distribution", [])
            if dist:
                top = ", ".join(f"{d['department']} ({d['count']})" for d in dist[:5])
                emit(f"  🗺️  Top departments: {top}")
            elif ety.get("note"):
                emit(f"  ℹ  {ety['note']}")
            report["demographics"] = {
                "bearers_since_1890": ety.get("bearers_since_1890"),
                "birth_year_context": ety.get("birth_year_context"),
                "national_rank":      ety.get("national_rank"),
                "top_departments":    dist[:5],
            }
        except Exception as exc:
            emit(f"  ℹ  Surname lookup unavailable: {exc}")
        emit("")

    # ── Step 0.5: Diploma / publication search ────────────────
    birth_yr_int: int | None = None
    if birth_year:
        m = re.match(r"(\d{4})", birth_year)
        if m:
            birth_yr_int = int(m.group(1))

    if "diplomas" in modules and firstname and lastname:
        emit(f"  💭 [Step 0.5] Searching diplomas — {firstname} {lastname}…")
        try:
            dip = await _search_diplomas_direct(firstname, lastname, cities, birth_year)
            n_theses = dip.get("total_theses", 0)
            n_pubs   = dip.get("total_pubs", 0)
            bac      = dip.get("bac_results", [])

            if n_theses or n_pubs:
                emit(f"  🎓  {n_theses} thesis/theses on theses.fr — {n_pubs} publication(s) on HAL")
                for th in dip.get("theses", []):
                    yr   = f" ({th['year']})" if th.get("year") else ""
                    inst = f" — {th['institution']}" if th.get("institution") else ""
                    rel  = _diploma_relevance(th.get("year"), birth_yr_int, "thesis")
                    th["relevance"] = rel
                    rel_tag = f" [{rel}]" if rel else ""
                    emit(f"  📄  {th['title'][:80]}{yr}{inst}{rel_tag}")
                for pub in dip.get("publications", []):
                    yr  = f" ({pub['year']})" if pub.get("year") else ""
                    rel = _diploma_relevance(pub.get("year"), birth_yr_int, "publication")
                    pub["relevance"] = rel
                    rel_tag = f" [{rel}]" if rel else ""
                    emit(f"  📰  {pub['title'][:80]}{yr}{rel_tag}")

            if bac:
                emit(f"  🎓  {len(bac)} bac result(s) — linternaute.com:")
                for b in bac:
                    rel_tag = f"  [{b['relevance']}]" if b.get("relevance") else ""
                    emit(f"  📜  {b['name']} — {b.get('diploma','?')} ({b['year']}, age {b['age_at_bac']}){rel_tag}")
            elif birth_yr_int:
                emit(f"  ℹ  No bac result (years {birth_yr_int+17}–{birth_yr_int+20})")

            brevet = dip.get("brevet_results", [])
            if brevet:
                emit(f"  🎓  {len(brevet)} brevet result(s) — linternaute.com:")
                for b in brevet:
                    rel_tag = f"  [{b['relevance']}]" if b.get("relevance") else ""
                    emit(f"  📜  {b['name']} (brevet {b['year']}, age {b['age_at_brevet']}){rel_tag}")
            elif birth_yr_int:
                emit(f"  ℹ  No brevet result (years {birth_yr_int+13}–{birth_yr_int+15})")

            if not n_theses and not n_pubs and not bac and not brevet:
                emit(f"  ℹ  No academic records found (theses.fr / HAL / bac / brevet)")

            report["diplomas"] = dip
        except Exception as exc:
            emit(f"  ℹ  Diploma search unavailable: {exc}")
        emit("")

    # ── Step 0.7: Business registries (SIRENE + Pappers) ─────
    if lastname:
        emit(f"  💭 [Step 0.7] Business registries — SIRENE / Pappers…")
        try:
            biz = await _search_sirene_pappers_direct(firstname, lastname, cities)

            # SIRENE
            sirene = biz.get("sirene", [])
            n_sirene = biz.get("total_sirene", 0)
            if sirene:
                emit(f"  🏢  {n_sirene} SIRENE record(s) for {lastname}:")
                for s in sirene:
                    active = "✓" if s.get("status", "").lower().startswith("a") else "✗ closed"
                    city   = f" — {s['city']}" if s.get("city") else ""
                    yr     = f" (created {s['created']})" if s.get("created") else ""
                    emit(f"  📋  [{active}] SIREN {s['siren']} — {s.get('name','?')}{city}{yr}")
            else:
                emit(f"  ℹ  No SIRENE record found for {firstname} {lastname}")

            # Pappers
            pappers = biz.get("pappers", [])
            if pappers:
                emit(f"  🔍  Pappers — {biz.get('total_pappers',0)} director match(es):")
                for p in pappers:
                    for c in p.get("companies", []):
                        role   = f" [{c.get('role','')}]" if c.get("role") else ""
                        status = f" ({c.get('status','')})" if c.get("status") else ""
                        emit(f"  🏛️  {p['name']}{role} → {c.get('name','?')}{status} (SIREN {c.get('siren','')})")
            elif biz.get("pappers_note"):
                emit(f"  ℹ  {biz['pappers_note']}")
            elif biz.get("pappers_error"):
                emit(f"  ⚠  Pappers: {biz['pappers_error']}")

            report["business"] = biz
        except Exception as exc:
            emit(f"  ℹ  Business registry search unavailable: {exc}")
        emit("")

    # ── Step 0.8: Annuaires — pre-filled search URLs ──────────
    # Pages Blanches and Pages Jaunes are behind Cloudflare and cannot be
    # scraped without a real browser. We generate precise search links instead.
    if firstname or lastname or cities:
        full_name  = f"{firstname} {lastname}".strip()
        city_hint  = cities[0] if cities else ""
        from urllib.parse import quote_plus as _qp

        pb_url = (
            "https://www.pagesjaunes.fr/pagesblanches/chercherlespersonnes"
            f"?quoiqui={_qp(full_name)}&ou={_qp(city_hint)}"
        )
        pj_url = (
            "https://www.pagesjaunes.fr/annuaire/chercherlespros"
            f"?quoiqui={_qp(full_name)}&ou={_qp(city_hint)}"
        )

        emit("  🔗 [Step 0.8] Phone Directories (manual verification — Cloudflare protected):")
        emit(f"  📋  Pages Blanches : {pb_url}")
        emit(f"  📋  Pages Jaunes   : {pj_url}")
        emit("")

        report["annuaires"] = {
            "pages_blanches": pb_url,
            "pages_jaunes":   pj_url,
            "note": "Cloudflare-protected — open links manually in a browser",
        }

    # ── Step 0.9: Phone OSINT ────────────────────────────────
    if "phone" in modules and phone:
        emit(f"  💭 [Step 0.9] Phone OSINT — {phone}…")
        try:
            ph = await _search_phone_direct(phone, firstname, lastname)

            if ph.get("error"):
                emit(f"  ✗  Phone parse error: {ph['error']}")
            else:
                validity = "✓ valid" if ph.get("valid") else "✗ invalid"
                emit(f"  📱  {ph['international'] or ph['e164']}  [{ph['type']}]  {validity}")
                if ph.get("carrier"):
                    emit(f"  📡  Carrier : {ph['carrier']}")
                if ph.get("region"):
                    emit(f"  🌍  Region  : {ph['region']}")
                if ph.get("timezone"):
                    emit(f"  🕐  Timezone: {ph['timezone']}")

                nv = ph.get("numverify") or {}
                if nv.get("line_type") and nv["line_type"] != ph["type"]:
                    emit(f"  🔍  Numverify → line_type: {nv['line_type']}, carrier: {nv.get('carrier','')}, location: {nv.get('location','')}")

                rev_links = ph.get("reverse_links", {})
                id_links  = ph.get("identity_links", {})
                app_links = ph.get("app_links", {})
                if rev_links:
                    emit("  🔗  Reverse lookup (open manually):")
                    for name, url in rev_links.items():
                        emit(f"  📋    {name}: {url}")
                if id_links:
                    emit("  🔗  Identity dorks:")
                    for name, url in id_links.items():
                        emit(f"  📋    {name}: {url}")
                if app_links:
                    emit("  🔗  Messaging apps:")
                    for name, url in app_links.items():
                        emit(f"  📋    {name}: {url}")

                platforms = ph.get("ignorant_platforms", [])
                if platforms:
                    found     = [p["site"] for p in platforms if p["status"] == "found"]
                    limited   = [p["site"] for p in platforms if p["status"] == "rate_limited"]
                    not_found = [p["site"] for p in platforms if p["status"] == "not_found"]
                    emit(f"  🔍  ignorant — {len(platforms)} platforms checked:")
                    if found:
                        emit(f"  ✅    Registered on : {', '.join(found)}")
                    if limited:
                        emit(f"  ⚠    Rate-limited  : {', '.join(limited)}")
                    if not_found:
                        emit(f"  ➖    Not found     : {', '.join(not_found)}")
                    if not found and not limited and not not_found:
                        emit(f"  ℹ    Not found on any checked platform")
                elif ph.get("valid"):
                    emit("  ℹ  ignorant not installed — social checks skipped (pip install ignorant)")

                pif = ph.get("phoneinfoga") or {}
                if pif.get("not_installed"):
                    emit("  ℹ  PhoneInfoga not installed — run: https://github.com/sundowndev/phoneinfoga")
                elif pif.get("carrier") or pif.get("urls"):
                    emit(f"  🔭  PhoneInfoga:")
                    if pif.get("carrier"):
                        emit(f"  📡    Carrier: {pif['carrier']}")
                    if pif.get("line_type"):
                        emit(f"  📶    Line type: {pif['line_type']}")
                    for u in (pif.get("urls") or [])[:5]:
                        emit(f"  🔗    {u}")

            report["phone"] = ph
        except Exception as exc:
            emit(f"  ℹ  Phone OSINT unavailable: {exc}")
        emit("")

    # ── Step 0.95: Social media (Instagram) ──────────────────
    if "social_media" in modules and (firstname or lastname):
        emit(f"  💭 [Step 0.95] Instagram username search…")
        try:
            dept_codes = [k for k in city_extras if re.match(r"^\d{2}$", k)]
            ig_usernames = _generate_ig_usernames(
                firstname, lastname, birth_year,
                keywords=all_keywords,
                pseudo=pseudo,
                dept_codes=dept_codes,
            )
            emit(f"  📱  {len(ig_usernames)} username candidates — first: {', '.join(ig_usernames[:5])}")

            ig = await _search_instagram_direct(
                ig_usernames, firstname, lastname, keywords=all_keywords,
            )
            found = ig.get("found", [])
            emit(f"  🔍  Checked {ig['checked']}/{ig['generated']} — {len(found)} profile(s) found")
            for p in found[:5]:
                stars = "★" * max(1, round(p["relevance"] / 2))
                age_note = f" (first seen {p['first_seen']})" if p.get("first_seen") else ""
                dn = f' — "{p["display_name"]}"' if p.get("display_name") else ""
                emit(f"  ✅  @{p['username']}{dn}{age_note} [{stars} {p['relevance']}/10]")
            if not found:
                if ig.get("blocked"):
                    emit(f"  ⚠  Instagram: rate-limited or login wall — only checked {ig['checked']} candidates")
                else:
                    emit(f"  ℹ  No Instagram profiles found among checked candidates")

            report["social_media"] = {"instagram": ig}
        except Exception as exc:
            emit(f"  ℹ  Instagram search unavailable: {exc}")
        emit("")

    # ── Step 0.96: Multi-platform social search ───────────────
    if "social_media" in modules and (pseudo or firstname or lastname or all_keywords):
        dept_codes_sm = [k for k in city_extras if re.match(r"^\d{2}$", k)]
        sm_usernames = _generate_ig_usernames(
            firstname, lastname, birth_year,
            keywords=all_keywords, pseudo=pseudo, dept_codes=dept_codes_sm,
        )
        emit("  💭 [Step 0.96] Multi-platform search (Twitter/X, TikTok, Snapchat, BeReal, LinkedIn)…")
        try:
            plat_results = await _search_social_platforms_direct(
                sm_usernames[:10], firstname, lastname, keywords=all_keywords,
            )
            total_plat = sum(len(v.get("found", [])) for v in plat_results.values() if isinstance(v, dict))
            emit(f"  🌐  {total_plat} profile(s) found across social platforms")
            for pk, pd in plat_results.items():
                fnd = pd.get("found", [])
                if fnd:
                    for prof in fnd[:5]:
                        dn = f' — "{prof["display_name"]}"' if prof.get("display_name") else ""
                        emit(f"  ✅  {pd['label']}: @{prof['username']}{dn} [{prof['relevance']}/10]")
                elif pk == "facebook" and pd.get("search_url"):
                    emit(f"  🔗  Facebook search: {pd['search_url']}")
            report["social_media"]["platforms"] = plat_results
        except Exception as exc:
            emit(f"  ℹ  Multi-platform search unavailable: {exc}")
        emit("")

    # ── Step 0.97: Cross-platform search (maigret) ───────────
    if "social_media" in modules and (pseudo or firstname or lastname or all_keywords):
        maigret_names: list[str] = []
        if pseudo:
            import re as _re
            p_clean = _re.sub(r"[^a-z0-9._]", "", pseudo.lower().translate(_ACCENT_MAP))
            if p_clean:
                maigret_names.append(p_clean)
        # User-provided keywords only — city extras (from all_keywords) are location
        # names, not username components, so they pollute maigret targets.
        for kw in (keywords or []):
            kw_c = re.sub(r"[^a-z0-9._-]", "", kw.lower().translate(_ACCENT_MAP))
            if kw_c and len(kw_c) > 2 and kw_c not in maigret_names:
                maigret_names.append(kw_c)
        for n in _generate_ig_usernames(firstname, lastname, birth_year, pseudo=pseudo)[:5]:
            if n not in maigret_names:
                maigret_names.append(n)
        maigret_names = maigret_names[:5]

        emit(f"  💭 [Step 0.97] Cross-platform search (maigret) — {', '.join(maigret_names)}…")
        try:
            mg = await _run_maigret_direct(maigret_names)

            if mg.get("not_installed"):
                emit("  ℹ  maigret not installed — skip (pip install maigret)")
            else:
                n_found = mg.get("total_found", 0)
                loc = mg.get("location_relevant", [])
                mkt = mg.get("marketplace", [])
                gam = mg.get("gaming", [])
                soc = mg.get("social", [])
                emit(f"  🌐  {n_found} profile(s) found across {len(mg.get('checked_usernames', []))} username(s)")
                if loc: emit(f"  📍  Location/Sport ({len(loc)}): {', '.join(p['site'] for p in loc[:6])}")
                if mkt: emit(f"  🛒  Marketplace ({len(mkt)}): {', '.join(p['site'] for p in mkt[:6])}")
                if gam: emit(f"  🎮  Gaming ({len(gam)}): {', '.join(p['site'] for p in gam[:6])}")
                if soc: emit(f"  💬  Social ({len(soc)}): {', '.join(p['site'] for p in soc[:8])}")

                if n_found > 0:
                    emit("  💭  Enriching activity signals…")
                    activity = await _enrich_activity_signals(mg)
                    if activity.get("reddit"):
                        rd = activity["reddit"]
                        emit(f"  📅  Reddit @{rd['username']}: last active {rd['last_active']}")
                        if rd.get("subreddits"):
                            emit(f"  🗂️   Subreddits: {', '.join(rd['subreddits'][:6])}")
                    if activity.get("github"):
                        gh = activity["github"]
                        loc_s = f" — {gh['location']}" if gh.get("location") else ""
                        emit(f"  💻  GitHub @{gh['username']}: last activity {gh['last_active']}{loc_s}")
                    for _sk in ("vinted", "strava", "komoot", "leboncoin"):
                        if activity.get(_sk):
                            _s = activity[_sk]
                            city_s = f" — 📍 {_s['city']}" if _s.get("city") else ""
                            emit(f"  {_s.get('icon','📌')}  {_s['label']} @{_s['username']}{city_s}")
                    mg["activity_signals"] = activity

                report.setdefault("social_media", {})["maigret"] = mg
        except Exception as exc:
            emit(f"  ℹ  Cross-platform search unavailable: {exc}")
        emit("")

    # ── Confirmation checkpoint ───────────────────────────────
    # Pause before deep OSINT: LLM synthesises passive intel into an
    # identity profile + last-known-locations timeline for the operator.
    if "email" in modules and confirmation_wait is not None and (firstname or lastname):
        emit("  💭 [Checkpoint] Synthesising passive intelligence into timeline…")

        _sm        = report.get("social_media", {})
        _mg        = _sm.get("maigret", {})
        _activity  = _mg.get("activity_signals", {})
        _ig_found  = _sm.get("instagram", {}).get("found", [])

        evidence: dict = {
            "target": {"firstname": firstname, "lastname": lastname, "birth_year": birth_year},
            "demographics": report.get("demographics", {}),
            "diplomas_count": sum(
                len(report.get("diplomas", {}).get(k, []))
                for k in ("theses", "bac_results", "brevet_results", "publications")
            ),
            "business_count": (
                len(report.get("business", {}).get("sirene", []))
                + len(report.get("business", {}).get("pappers", []))
            ),
            "phone": {
                "valid":     report["phone"].get("valid"),
                "type":      report["phone"].get("type"),
                "carrier":   report["phone"].get("carrier"),
                "region":    report["phone"].get("region"),
                "territory": (report["phone"].get("arcep") or {}).get("territory", ""),
                "siret":     (report["phone"].get("arcep") or {}).get("siret", ""),
                "social":    [p["site"] for p in report["phone"].get("ignorant_platforms", []) if p["status"] == "found"],
            } if report.get("phone") else None,
            "instagram": [
                {"username": p["username"], "display_name": p.get("display_name",""),
                 "relevance": p["relevance"], "first_seen": p.get("first_seen")}
                for p in _ig_found[:5]
            ],
            "maigret": {
                "total_found":       _mg.get("total_found", 0),
                "location_relevant": [{"site": p["site"], "url": p["url"]} for p in _mg.get("location_relevant", [])[:6]],
                "marketplace":       [{"site": p["site"], "url": p["url"]} for p in _mg.get("marketplace", [])[:4]],
                "gaming":            [{"site": p["site"]} for p in _mg.get("gaming", [])[:4]],
                "social_count":      len(_mg.get("social", [])),
            },
            "activity_signals": {
                "reddit": {
                    "username":    _activity.get("reddit", {}).get("username"),
                    "last_active": _activity.get("reddit", {}).get("last_active"),
                    "subreddits":  _activity.get("reddit", {}).get("subreddits", []),
                } if _activity.get("reddit") else None,
                "github": {
                    "username":    _activity.get("github", {}).get("username"),
                    "location":    _activity.get("github", {}).get("location"),
                    "last_active": _activity.get("github", {}).get("last_active"),
                } if _activity.get("github") else None,
            },
        }

        identity_text  = ""
        timeline_text  = ""
        locations_text = ""

        if USE_LLM:
            try:
                synth_resp = llm_completion(
                    model=backend,
                    messages=[{
                        "role": "user",
                        "content": (
                            f"You are an OSINT analyst helping locate a missing person.\n\n"
                            f"Target: {firstname} {lastname}"
                            + (f"  (born ~{birth_year})" if birth_year else "") + "\n\n"
                            f"Passive intelligence gathered so far:\n"
                            f"{json.dumps(evidence, indent=2, ensure_ascii=False)}\n\n"
                            f"Based on this data, provide three sections:\n"
                            f"IDENTITY: 2-3 sentences describing who this person appears to be.\n"
                            f"TIMELINE: Chronological list of last known online activities and locations (most recent first). "
                            f"Use format '• <date/period>: <platform> — <what was found/location hint>'. "
                            f"Include ALL signals: Reddit subreddits (location clues), GitHub location, "
                            f"Instagram first seen, phone region, diploma cities, etc.\n"
                            f"LOCATIONS: Comma-separated list of cities/regions that appear in the data.\n\n"
                            f"Be specific and factual. If a subreddit is r/paris, that is a location clue."
                        ),
                    }],
                    max_tokens=600,
                    timeout=90,
                )
                raw = synth_resp.choices[0].message.content or ""

                # Parse the three sections
                import re as _re2
                parts = _re2.split(r'\n(?=IDENTITY:|TIMELINE:|LOCATIONS:)', raw.strip())
                for part in parts:
                    if part.startswith("IDENTITY:"):
                        identity_text = part[9:].strip()
                    elif part.startswith("TIMELINE:"):
                        timeline_text = part[9:].strip()
                    elif part.startswith("LOCATIONS:"):
                        locations_text = part[10:].strip()

                if identity_text or timeline_text:
                    emit(f"\n  ┌─ 🤖 Synthesis {'─'*42}┐")
                    if identity_text:
                        emit(f"  │  IDENTITY  : {identity_text[:120]}")
                    if locations_text:
                        emit(f"  │  LOCATIONS : {locations_text[:120]}")
                    if timeline_text:
                        for tl in timeline_text.splitlines()[:6]:
                            emit(f"  │  {tl}")
                    emit(f"  └{'─'*49}┘\n")
            except Exception as exc:
                emit(f"  ⚠  Synthesis failed: {exc}")

        # Store in report for the final display
        report["timeline"] = {
            "llm_identity":  identity_text,
            "llm_timeline":  timeline_text,
            "llm_locations": locations_text,
            "activity_signals": evidence["activity_signals"],
        }

        if event_callback:
            event_callback({
                "type": "confirmation",
                "data": {
                    "candidate_summary": identity_text,
                    "timeline_text":     timeline_text,
                    "locations_text":    locations_text,
                    "evidence":          evidence,
                },
            })

        emit("  ⏸  Waiting for user confirmation before deep OSINT…")
        action = confirmation_wait()

        if action != "continue":
            emit("  ⛔  Investigation stopped by user.")
            emit(f"\n{'─' * 54}")
            emit("  Investigation terminated at confirmation checkpoint.")
            emit(f"{'─' * 54}\n")
            if report_callback:
                report_callback(report)
            return

        emit("  ✓  User confirmed — continuing with deep OSINT…")
        emit("")

    # ── Email module guard ────────────────────────────────────
    if "email" not in modules:
        emit("  ℹ  Email module disabled — investigation complete.")
        if report_callback:
            report_callback(report)
        return

    gen_tool = next((t for t in tools if t.name == "generate_permutations"), None)
    if not gen_tool:
        emit("  ✗  generate_permutations tool not found in MCP server")
        return

    llm_tools_step1 = [
        {
            "type": "function",
            "function": {
                "name": gen_tool.name,
                "description": gen_tool.description or "",
                "parameters": gen_tool.inputSchema if isinstance(gen_tool.inputSchema, dict) else {},
            },
        }
    ]

    extra_args = f', birth_year="{birth_year}"' if birth_year else ""
    extra_args += f', keywords="{kw_str}"' if all_keywords else ""
    user_msg = (
        f"Target: {firstname} {lastname}\n"
        f"Birth year: {birth_year or 'unknown'}\n"
        f"Keywords: {kw_str}\n\n"
        f"Call generate_permutations with firstname=\"{firstname}\", lastname=\"{lastname}\"{extra_args}."
    )

    # ── Step 1: LLM → generate_permutations ───────────────────
    emit("  💭 [Step 1/4] Generating email candidates…")
    session_id = None

    llm_hard_fail = False
    for attempt in range(1, 4):
        emit(f"  💭  LLM attempt {attempt}/3 — calling generate_permutations")
        try:
            response = llm_completion(
                model=backend,
                messages=[{"role": "user", "content": user_msg}],
                tools=llm_tools_step1,
                tool_choice={"type": "function", "function": {"name": "generate_permutations"}},
                max_tokens=512,
                timeout=60,
            )
        except Exception as exc:
            emit(f"  ✗  LLM error: {exc}")
            llm_hard_fail = True
            break

        msg = response.choices[0].message
        if not msg.tool_calls:
            emit(f"  ⚠  No tool call in response (attempt {attempt}). Retrying…")
            continue

        tc = msg.tool_calls[0]
        try:
            args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
        except Exception:
            args = {}

        # Fallback: if LLM didn't split the name properly
        if not args.get("lastname") and " " in args.get("firstname", ""):
            parts = args["firstname"].split(None, 1)
            args["firstname"], args["lastname"] = parts[0], parts[1]

        # Always force the correct values — LLMs frequently invert name order
        args["firstname"] = firstname
        args["lastname"]  = lastname
        if not args.get("birth_year") and birth_year:
            args["birth_year"] = birth_year
        if all_keywords:
            args["keywords"] = ", ".join(all_keywords)

        _emit_tool_call(tc.function.name, args, emit)
        raw = await session.call_tool("generate_permutations", args)
        raw_text = raw.content[0].text if raw.content else "{}"
        try:
            gen_result = json.loads(raw_text)
        except Exception:
            gen_result = {"raw": raw_text}

        _emit_tool_result("generate_permutations", gen_result, emit)

        if "error" in gen_result:
            emit(f"  ✗  Error: {gen_result['error']}")
            return

        session_id = gen_result.get("session_id")
        if session_id:
            break
        emit(f"  ⚠  No session_id returned (attempt {attempt}). Retrying…")

    if not session_id:
        emit("  ✗  Failed to generate candidates after 3 attempts — falling back to direct pipeline.")
        await _run_pipeline(session, firstname, lastname, birth_year, all_keywords, cities, phone, pseudo, modules, emit, report_callback, event_callback, confirmation_wait)
        return

    # ── Step 2: chunked validation with live progress ─────────
    total      = gen_result.get("total", 0)
    CHUNK_SIZE = 30
    to_check   = total

    emit(f"  💭 [Step 2/4] Validating {total} candidates…")
    emit(f"  ℹ  Custom/corporate domains → SMTP  |  Gmail/Hotmail/Yahoo → HIBP direct (SMTP blocked by provider)")

    all_valid:        list[str] = []
    all_unverifiable: list[str] = []
    checked = 0

    while checked < to_check:
        this_chunk = min(CHUNK_SIZE, to_check - checked)

        raw = await session.call_tool("get_candidates", {
            "session_id": session_id,
            "offset":     checked,
            "limit":      this_chunk,
        })
        raw_text = raw.content[0].text if raw.content else "{}"
        try:
            chunk_data = json.loads(raw_text)
        except Exception:
            chunk_data = {}

        if "error" in chunk_data:
            emit(f"  ✗  {chunk_data['error']}")
            break

        chunk_emails = chunk_data.get("candidates", [])
        if not chunk_emails:
            break

        emit(f"  🔍  {checked + 1}–{checked + len(chunk_emails)} / {to_check}  validating…")

        raw = await session.call_tool("validate_batch", {
            "emails":      chunk_emails,
            "max_results": len(chunk_emails),
        })
        raw_text = raw.content[0].text if raw.content else "{}"
        try:
            val_data = json.loads(raw_text)
        except Exception:
            val_data = {}

        new_valid        = val_data.get("valid", [])
        new_unverifiable = val_data.get("unverifiable", [])
        all_valid.extend(new_valid)
        all_unverifiable.extend(new_unverifiable)
        checked += len(chunk_emails)


        parts = [f"  ✓  {checked}/{to_check}"]
        if new_valid:
            parts.append(f"SMTP valid: {', '.join(new_valid)}")
        if new_unverifiable:
            parts.append(f"{len(new_unverifiable)} provider-blocked")
        emit("  ".join(parts))

    emit(f"  📦  {checked} checked — {len(all_valid)} SMTP-valid, {len(all_unverifiable)} unverifiable (→ HIBP)")
    valid_emails = all_valid
    report["emails"]["smtp_valid"] = list(all_valid)

    # ── Step 3a: GHunt — Gmail candidates only ────────────────
    GHUNT_MAX   = 15  # top Gmail patterns to probe with GHunt
    gmail_candidates = [e for e in all_unverifiable if e.split("@")[-1].lower() in {"gmail.com", "googlemail.com"}]
    ghunt_results: list[dict] = []
    ghunt_confirmed: list[str] = []

    if gmail_candidates:
        # Probe GHunt to see if it's available (1 quick test)
        raw = await session.call_tool("check_google_account", {"email": gmail_candidates[0]})
        raw_text = raw.content[0].text if raw.content else "{}"
        try:
            probe = json.loads(raw_text)
        except Exception:
            probe = {}

        if probe.get("error") == "ghunt_unavailable":
            emit(f"  ⚠  GHunt unavailable: {probe.get('hint', '')}")
        else:
            emit(f"  💭 [Step 3a/4] GHunt — probing {min(GHUNT_MAX, len(gmail_candidates))} Gmail candidates…")
            for email in gmail_candidates[:GHUNT_MAX]:
                _emit_tool_call("check_google_account", {"email": email}, emit)
                raw = await session.call_tool("check_google_account", {"email": email})
                raw_text = raw.content[0].text if raw.content else "{}"
                try:
                    g = json.loads(raw_text)
                except Exception:
                    g = {"email": email, "error": raw_text}
                _emit_tool_result("check_google_account", g, emit)
                ghunt_results.append(g)
                if g.get("found"):
                    ghunt_confirmed.append(email)

    if ghunt_confirmed:
        emit(f"  ✅  GHunt — {len(ghunt_confirmed)} Google account(s) confirmed: {', '.join(ghunt_confirmed)}")
    report["emails"]["ghunt_confirmed"] = list(ghunt_confirmed)
    report["ghunt_details"] = [g for g in ghunt_results if g.get("found")]

    # ── Step 3a-bis: Instagram lookup by email (obfuscated info) ────
    # For each confirmed/valid email, query Instagram's private endpoint to get
    # the obfuscated email/phone of the registered Instagram account (no auth needed).
    ig_lookup_results: list[dict] = []
    ig_lookup_targets = (list(ghunt_confirmed) + list(valid_emails))[:5]
    if ig_lookup_targets:
        emit(f"  💭 [Step 3a-bis/4] Instagram email lookup — {len(ig_lookup_targets)} candidate(s)…")
        for em in ig_lookup_targets:
            res = await _ig_lookup_by_email(em, phone)
            ig_lookup_results.append(res)
            st = res.get("status", "")
            if st == "found":
                obfu_e = res.get("obfuscated_email", "")
                obfu_p = res.get("obfuscated_phone", "")
                parts = []
                if obfu_e:
                    parts.append(f"email: {obfu_e}")
                if obfu_p:
                    parts.append(f"phone: {obfu_p}")
                    if res.get("phone_match"):
                        parts.append("⚠ phone digits match!")
                emit(f"  📸  Instagram ({em}): {' | '.join(parts) if parts else 'account found, no public obfuscated info'}")
            elif st == "rate_limited":
                emit(f"  ⚠  Instagram lookup rate-limited for {em}")
            else:
                emit(f"  ℹ  Instagram: no account found for {em}")
        report["ig_email_lookup"] = ig_lookup_results

    # ── Step 3b: HIBP — valides SMTP + top non-vérifiables ────
    # For unverifiable (major provider) addresses, HIBP is the only reliable signal.
    # Check the most likely patterns first (top 30 unverifiable candidates).
    HIBP_UNVERIFIABLE_MAX = 30
    hibp_targets = list(valid_emails) + list(ghunt_confirmed) + [
        e for e in all_unverifiable[:HIBP_UNVERIFIABLE_MAX] if e not in ghunt_confirmed
    ]

    hibp_results: list[dict] = []
    if not os.environ.get("HIBP_API_KEY", "").strip():
        emit("  ⚠  HIBP_API_KEY not configured — breach check skipped.")
        emit("  ℹ  Add your key in Configuration (https://haveibeenpwned.com/API/Key)")
    elif hibp_targets:
        n_unv = min(len(all_unverifiable), HIBP_UNVERIFIABLE_MAX)
        emit(f"  💭 [Step 3b/4] HIBP breach check — {len(valid_emails)} SMTP-valid + {n_unv} unverifiable candidates…")
        for email in hibp_targets:
            _emit_tool_call("check_hibp", {"email": email}, emit)
            raw = await session.call_tool("check_hibp", {"email": email})
            raw_text = raw.content[0].text if raw.content else "{}"
            try:
                h = json.loads(raw_text)
            except Exception:
                h = {"email": email, "error": raw_text}
            _emit_tool_result("check_hibp", h, emit)
            hibp_results.append(h)
    else:
        emit("  ℹ  No emails to check on HIBP.")

    # ── Collect HIBP data into report ─────────────────────────
    breached_emails = [h["email"] for h in hibp_results if h.get("breached")]
    report["emails"]["breached"] = breached_emails
    report["hibp_details"] = hibp_results

    # ── Risk level ────────────────────────────────────────────
    if breached_emails or ghunt_confirmed:
        report["risk_level"] = "high"
    elif valid_emails:
        report["risk_level"] = "medium"
    elif report["demographics"].get("bearers_since_1890"):
        report["risk_level"] = "low"

    # ── Step 4: LLM summary ────────────────────────────────────
    emit("  💭 [Step 4/4] Generating summary…")
    skills = _load_skills()
    summary_system = f"{skills}\n\n---\n\nYou are an OSINT analyst. Write a concise investigation summary."
    ghunt_summary = [
        f"{g['email']}: name={g.get('name')} gaia={g.get('gaia_id')} "
        f"reviews={g.get('maps_reviews',0)} photo={'yes' if g.get('photo_url') else 'no'}"
        for g in ghunt_results if g.get("found")
    ]
    # Build timeline/location context from confirmation checkpoint data
    tl_data = report.get("timeline", {})
    timeline_ctx = ""
    if tl_data.get("llm_identity"):
        timeline_ctx += f"\nProfile (from passive phase): {tl_data['llm_identity']}"
    if tl_data.get("llm_locations"):
        timeline_ctx += f"\nLikely locations: {tl_data['llm_locations']}"
    if tl_data.get("llm_timeline"):
        timeline_ctx += f"\nActivity timeline:\n{tl_data['llm_timeline']}"
    mg_data = report.get("social_media", {}).get("maigret", {})
    if mg_data.get("total_found", 0) > 0:
        loc_sites = [p["site"] for p in mg_data.get("location_relevant", [])]
        if loc_sites:
            timeline_ctx += f"\nLocation/sport platforms found: {', '.join(loc_sites)}"
    ig_found = report.get("social_media", {}).get("instagram", {}).get("found", [])
    if ig_found:
        timeline_ctx += f"\nInstagram: {', '.join('@'+p['username'] for p in ig_found[:3])}"

    summary_user = (
        f"Target: {firstname} {lastname}  |  Birth year: {birth_year or 'unknown'}  |  Keywords: {kw_str}\n\n"
        f"SMTP-validated emails ({len(valid_emails)}): {', '.join(valid_emails) or 'none'}\n"
        f"GHunt-confirmed Google accounts ({len(ghunt_confirmed)}): {', '.join(ghunt_confirmed) or 'none'}\n"
        + (f"GHunt details: {chr(10).join(ghunt_summary)}\n" if ghunt_summary else "")
        + f"Found in breaches ({len(breached_emails)}): {', '.join(breached_emails) or 'none'}\n\n"
        f"Breach details:\n{json.dumps(hibp_results, indent=2, ensure_ascii=False)}\n\n"
        + (f"Additional intel:{timeline_ctx}\n\n" if timeline_ctx else "")
        + "Write a short investigation report: confirmed/breached emails, risk level, last known locations/activity if available, recommended next OSINT steps."
    )
    summary_text = ""
    try:
        summary_resp = llm_completion(
            model=backend,
            messages=[
                {"role": "system", "content": summary_system},
                {"role": "user",   "content": summary_user},
            ],
            max_tokens=1024,
            timeout=120,
        )
        summary_text = summary_resp.choices[0].message.content or ""
        if summary_text.strip():
            emit(f"\n  ┌─ 📋 Summary {'─'*42}┐")
            for line in summary_text.strip().splitlines():
                emit(f"  │  {line}")
            emit(f"  └{'─'*49}┘\n")
    except Exception as exc:
        emit(f"  ⚠  Summary generation failed: {exc}")

    report["llm_summary"] = summary_text.strip()

    emit(f"\n{'─' * 54}")
    emit("  Investigation complete.")
    emit(f"{'─' * 54}\n")

    if report_callback:
        report_callback(report)


async def _run_pipeline(session, firstname, lastname, birth_year, keywords, cities, phone, pseudo, modules, emit, report_callback=None, event_callback=None, confirmation_wait=None):
    """Fixed pipeline without LLM."""
    emit("  ℹ  No LLM — running direct pipeline\n")
    city_extras  = _cities_to_keywords(cities)
    all_keywords = list(keywords)
    for k in city_extras:
        if k not in all_keywords:
            all_keywords.append(k)

    report: dict = {
        "target":       {"firstname": firstname, "lastname": lastname,
                         "birth_year": birth_year, "keywords": all_keywords,
                         "cities": cities},
        "demographics": {},
        "diplomas":     {"theses": [], "publications": [], "bac_results": [], "brevet_results": [], "total_theses": 0, "total_pubs": 0, "total_bac": 0, "total_brevet": 0},
        "business":     {"sirene": [], "pappers": [], "total_sirene": 0, "total_pappers": 0},
        "phone":        {},
        "social_media": {},
        "timeline":     {},
        "emails":       {"smtp_valid": [], "ghunt_confirmed": [], "breached": []},
        "ghunt_details": [],
        "hibp_details":  [],
        "llm_summary":  "",
        "risk_level":   "none",
    }

    city_extras_pl = _cities_to_keywords(cities)

    # Phone step (pipeline mode)
    if "phone" in modules and phone:
        emit(f"  💭 Phone OSINT — {phone}…")
        try:
            ph = await _search_phone_direct(phone, firstname, lastname)
            if ph.get("error"):
                emit(f"  ✗  {ph['error']}")
            else:
                emit(f"  📱  {ph['international'] or ph['e164']}  [{ph['type']}]  {'✓ valid' if ph.get('valid') else '✗ invalid'}")
                if ph.get("carrier"): emit(f"  📡  {ph['carrier']}")
                if ph.get("region"):  emit(f"  🌍  {ph['region']}")
            report["phone"] = ph
        except Exception as exc:
            emit(f"  ℹ  Phone OSINT unavailable: {exc}")
        emit("")

    # Social media step (pipeline mode)
    if "social_media" in modules and (firstname or lastname):
        emit("  💭 Instagram username search…")
        try:
            dept_codes_pl = [k for k in city_extras_pl if re.match(r"^\d{2}$", k)]
            ig_usernames = _generate_ig_usernames(
                firstname, lastname, birth_year,
                keywords=list(keywords),
                pseudo=pseudo,
                dept_codes=dept_codes_pl,
            )
            emit(f"  📱  {len(ig_usernames)} candidates — first: {', '.join(ig_usernames[:5])}")
            ig = await _search_instagram_direct(
                ig_usernames, firstname, lastname, keywords=list(keywords),
            )
            found = ig.get("found", [])
            emit(f"  🔍  Checked {ig['checked']}/{ig['generated']} — {len(found)} found")
            for p in found[:5]:
                dn = f' — "{p["display_name"]}"' if p.get("display_name") else ""
                emit(f"  ✅  @{p['username']}{dn} [{p['relevance']}/10]")
            report["social_media"] = {"instagram": ig}
        except Exception as exc:
            emit(f"  ℹ  Instagram search unavailable: {exc}")
        emit("")

    # Multi-platform step (pipeline mode)
    if "social_media" in modules and (pseudo or firstname or lastname or all_keywords):
        dept_codes_sm_pl = [k for k in city_extras_pl if re.match(r"^\d{2}$", k)]
        sm_un_pl = _generate_ig_usernames(
            firstname, lastname, birth_year,
            keywords=all_keywords, pseudo=pseudo, dept_codes=dept_codes_sm_pl,
        )
        emit("  💭 Multi-platform search (Twitter/X, TikTok, Snapchat, BeReal, LinkedIn)…")
        try:
            plat_pl = await _search_social_platforms_direct(
                sm_un_pl[:10], firstname, lastname, keywords=all_keywords,
            )
            total_pl = sum(len(v.get("found", [])) for v in plat_pl.values() if isinstance(v, dict))
            emit(f"  🌐  {total_pl} profile(s) found")
            for pk, pd in plat_pl.items():
                fnd = pd.get("found", [])
                if fnd:
                    for prof in fnd[:5]:
                        dn = f' — "{prof["display_name"]}"' if prof.get("display_name") else ""
                        emit(f"  ✅  {pd['label']}: @{prof['username']}{dn} [{prof['relevance']}/10]")
                elif pk == "facebook" and pd.get("search_url"):
                    emit(f"  🔗  Facebook search: {pd['search_url']}")
            report["social_media"]["platforms"] = plat_pl
        except Exception as exc:
            emit(f"  ℹ  Multi-platform search unavailable: {exc}")
        emit("")

    # Maigret step (pipeline mode)
    if "social_media" in modules and (pseudo or firstname or lastname or all_keywords):
        mg_names_pl: list[str] = []
        if pseudo:
            p_c = re.sub(r"[^a-z0-9._]", "", pseudo.lower().translate(_ACCENT_MAP))
            if p_c:
                mg_names_pl.append(p_c)
        # User-provided keywords only — city extras are location names, not usernames
        for kw in (keywords or []):
            kw_c = re.sub(r"[^a-z0-9._-]", "", kw.lower().translate(_ACCENT_MAP))
            if kw_c and len(kw_c) > 2 and kw_c not in mg_names_pl:
                mg_names_pl.append(kw_c)
        for n in _generate_ig_usernames(firstname, lastname, birth_year, pseudo=pseudo)[:5]:
            if n not in mg_names_pl:
                mg_names_pl.append(n)
        mg_names_pl = mg_names_pl[:5]

        emit(f"  💭 Cross-platform search (maigret) — {', '.join(mg_names_pl)}…")
        try:
            mg_pl = await _run_maigret_direct(mg_names_pl)
            if mg_pl.get("not_installed"):
                emit("  ℹ  maigret not installed — skip (pip install maigret)")
            else:
                n_pl = mg_pl.get("total_found", 0)
                emit(f"  🌐  {n_pl} profile(s) found")
                loc_pl = mg_pl.get("location_relevant", [])
                if loc_pl:
                    emit(f"  📍  Location/Sport: {', '.join(p['site'] for p in loc_pl[:6])}")
                if n_pl > 0:
                    act_pl = await _enrich_activity_signals(mg_pl)
                    if act_pl.get("reddit"):
                        rd = act_pl["reddit"]
                        emit(f"  📅  Reddit: last active {rd['last_active']}")
                        if rd.get("subreddits"):
                            emit(f"  🗂️   Subreddits: {', '.join(rd['subreddits'][:5])}")
                    if act_pl.get("github"):
                        gh = act_pl["github"]
                        loc_s = f" — {gh['location']}" if gh.get("location") else ""
                        emit(f"  💻  GitHub @{gh['username']}: last activity {gh['last_active']}{loc_s}")
                    for _sk in ("vinted", "strava", "komoot", "leboncoin"):
                        if act_pl.get(_sk):
                            _s = act_pl[_sk]
                            city_s = f" — 📍 {_s['city']}" if _s.get("city") else ""
                            emit(f"  {_s.get('icon','📌')}  {_s['label']} @{_s['username']}{city_s}")
                    mg_pl["activity_signals"] = act_pl
                report.setdefault("social_media", {})["maigret"] = mg_pl
        except Exception as exc:
            emit(f"  ℹ  Cross-platform search unavailable: {exc}")
        emit("")

    # Confirmation checkpoint (pipeline mode)
    if "email" in modules and confirmation_wait is not None and (firstname or lastname):
        _sm_pl   = report.get("social_media", {})
        _mg_pl   = _sm_pl.get("maigret", {})
        _act_pl  = _mg_pl.get("activity_signals", {})
        evidence: dict = {
            "target": {"firstname": firstname, "lastname": lastname, "birth_year": birth_year},
            "phone": {
                "valid":   report["phone"].get("valid"),
                "type":    report["phone"].get("type"),
                "carrier": report["phone"].get("carrier"),
                "region":  report["phone"].get("region"),
                "social":  [p["site"] for p in report["phone"].get("ignorant_platforms", []) if p["status"] == "found"],
            } if report.get("phone") else None,
            "instagram": [
                {"username": p["username"], "display_name": p.get("display_name",""), "relevance": p["relevance"]}
                for p in _sm_pl.get("instagram", {}).get("found", [])[:5]
            ],
            "maigret": {
                "total_found":       _mg_pl.get("total_found", 0),
                "location_relevant": [{"site": p["site"], "url": p["url"]} for p in _mg_pl.get("location_relevant", [])[:6]],
            },
            "activity_signals": {
                "reddit": {"last_active": _act_pl.get("reddit", {}).get("last_active"), "subreddits": _act_pl.get("reddit", {}).get("subreddits", [])} if _act_pl.get("reddit") else None,
                "github": {"location": _act_pl.get("github", {}).get("location"), "last_active": _act_pl.get("github", {}).get("last_active")} if _act_pl.get("github") else None,
            },
        }
        report["timeline"] = {"llm_identity": "", "llm_timeline": "", "llm_locations": "", "activity_signals": evidence["activity_signals"]}
        if event_callback:
            event_callback({"type": "confirmation", "data": {"candidate_summary": "", "timeline_text": "", "locations_text": "", "evidence": evidence}})
        emit("  ⏸  Waiting for user confirmation…")
        action = confirmation_wait()
        if action != "continue":
            emit("  ⛔  Investigation stopped by user.")
            if report_callback:
                report_callback(report)
            return
        emit("  ✓  User confirmed — continuing…")
        emit("")

    # Step 1: generate (all candidates stored server-side)
    emit(f"  🔧 generate_permutations({firstname}, {lastname}, {birth_year})")
    result = await session.call_tool("generate_permutations", {
        "firstname": firstname,
        "lastname": lastname,
        "birth_year": birth_year or "",
        "keywords": ", ".join(all_keywords),
    })
    data = json.loads(result.content[0].text)
    if "error" in data:
        emit(f"  ✗  Error: {data['error']}")
        return
    session_id = data["session_id"]
    total      = data["total"]
    emit(f"  📦 {total} candidates generated (session: {session_id})")
    emit("")

    # Step 2: validate all candidates server-side
    emit(f"  🔧 validate_all(session_id={session_id}) — checking all {total} candidates…")
    res = await session.call_tool("validate_all", {"session_id": session_id})
    d = json.loads(res.content[0].text)
    if "error" in d:
        emit(f"  ✗  Error: {d['error']}")
        return
    valid_emails = d.get("valid", [])
    emit(f"  📦 Checked {d.get('checked', total)} — {len(valid_emails)} valid found")
    emit("")
    for email in valid_emails:
        emit(f"  ✓  {email}")
    report["emails"]["smtp_valid"] = list(valid_emails)

    emit("")

    # Step 3: HIBP
    hibp_results: list[dict] = []
    if valid_emails:
        emit("  Checking breach history...\n")
        for email in valid_emails:
            emit(f"  🔧 check_hibp({email})")
            res = await session.call_tool("check_hibp", {"email": email})
            d = json.loads(res.content[0].text)
            hibp_results.append(d)
            if d.get("breached"):
                names = [b["name"] for b in d.get("breaches", [])]
                emit(f"  ⚠  {email}  →  BREACHED × {d.get('count')}  :  {', '.join(names)}")
            elif d.get("breached") is False:
                emit(f"  ✓  {email}  →  not breached")
            else:
                emit(f"  ?  {email}  →  {d.get('error', '?')}")
    else:
        emit("  ℹ  No valid emails found in the first 15 candidates.")

    breached = [h["email"] for h in hibp_results if h.get("breached")]
    report["emails"]["breached"] = breached
    report["hibp_details"] = hibp_results
    report["risk_level"] = "high" if breached else ("medium" if valid_emails else "none")

    emit(f"\n{'─' * 54}")
    emit("  ✓  Pipeline complete.")
    emit(f"{'─' * 54}\n")

    if report_callback:
        report_callback(report)


def _emit_tool_call(name: str, args: dict, emit) -> None:
    emit(f"  ┌─ 🔧 {name} {'─'*40}┐")
    for k, v in args.items():
        val = f'"{v}"' if isinstance(v, str) else repr(v)
        if len(val) > 50:
            val = val[:47] + "..."
        emit(f"  │  {k} = {val}")
    emit(f"  └{'─'*49}┘\n")


def _emit_tool_result(name: str, result: dict, emit) -> None:
    emit(f"  ┌─ 📦 Result: {name} {'─'*36}┐")
    if name == "generate_permutations":
        total = result.get("total", 0)
        sid   = result.get("session_id", "?")
        shown = result.get("preview", [])[:3]
        emit(f"  │  {total} candidates  •  session: {sid}  •  e.g. {', '.join(shown)}")
    elif name == "validate_all":
        valids  = result.get("valid", [])
        checked = result.get("checked", "?")
        emit(f"  │  checked {checked}  →  {len(valids)} valid: {', '.join(valids[:5]) or 'none'}")
    elif name in ("validate_batch",):
        valids = result.get("valid", [])
        emit(f"  │  {len(valids)} valid  :  {', '.join(valids[:5]) or 'none'}")
    elif name == "validate_email":
        icon = "✓ VALID" if result.get("valid") else f"✗ {result.get('status', '?')}"
        emit(f"  │  {icon}")
    elif name == "check_hibp":
        if result.get("breached"):
            names = [b["name"] for b in result.get("breaches", [])]
            emit(f"  │  ⚠ BREACHED × {result.get('count')}  :  {', '.join(names[:5])}")
        elif result.get("breached") is False:
            emit(f"  │  ✓ Not breached")
        else:
            emit(f"  │  ? {result.get('error', '')}")
    else:
        raw = json.dumps(result, ensure_ascii=False)
        emit(f"  │  {raw[:80]}")
    emit(f"  └{'─'*49}┘\n")


if __name__ == "__main__":
    firstname  = input("First name  : ").strip()
    lastname   = input("Last name   : ").strip()
    birth_year = input("Birth year  : ").strip()
    kw_raw     = input("Keywords    : ").strip()
    city_raw   = input("Cities/depts: ").strip()
    keywords   = [k.strip() for k in kw_raw.split(",") if k.strip()]
    cities_cli = [c.strip() for c in city_raw.split(",") if c.strip()]
    asyncio.run(run_agent(firstname, lastname, birth_year, keywords, cities=cities_cli))
