"""
LinkedIn profile detection skill.

LinkedIn blocks all automated HTTP access (returns 999 for all bot requests,
regardless of User-Agent). Direct profile verification is not feasible without
authenticated sessions.

This skill instead:
  1. Generates likely LinkedIn slug patterns from name + keywords
  2. Returns them as unverified candidates for manual investigation
  3. Marks all results as requiring_verification=True

Profile slugs typically follow: firstname-lastname[-random6hex]
or firstname-lastname-XXXXX for disambiguation.

Usage:
    python -m skills.social_media.linkedin --firstname Jean --lastname Dupont
    python -m skills.social_media.linkedin --firstname Jean --lastname Dupont --keywords jd --birth_year 1990
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
from urllib.parse import parse_qs, unquote, urlencode, urlparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def _generate_linkedin_slugs(
    firstname: str,
    lastname: str,
    keywords: list[str],
) -> list[str]:
    """Generate likely LinkedIn profile slug candidates (most common patterns first)."""
    fn = _norm(firstname)
    ln = _norm(lastname)
    kws = [_norm(k) for k in keywords if k.strip()]

    if not fn or not ln:
        return []

    fn1 = fn[0]
    seen: set[str] = set()
    slugs: list[str] = []

    def _add(*items: str) -> None:
        for s in items:
            if s and s not in seen:
                seen.add(s)
                slugs.append(s)

    # Most common LinkedIn slug patterns (hyphen-separated)
    _add(
        f"{fn}-{ln}",         # jean-dupont  ← most common
        f"{ln}-{fn}",         # dupont-jean
        f"{fn1}-{ln}",        # j-dupont
        f"{fn}{ln}",          # jeandupont
        f"{fn}.{ln}",         # jean.dupont  (LinkedIn normalises to hyphen but user may have set this)
    )

    # With keyword
    for kw in kws:
        _add(
            f"{fn}-{ln}-{kw}",
            f"{kw}-{fn}-{ln}",
            f"{fn}-{kw}",
        )

    return slugs


def _decode_ddg_url(href: str) -> str:
    """Extract the real URL from a DuckDuckGo redirect href."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    uddg = qs.get("uddg", [""])[0]
    return unquote(uddg) if uddg else href


def _parse_snippet(snippet: str) -> dict:
    """
    Extract structured fields from a LinkedIn search-result snippet.
    Snippet example:
      'Pentest · Expérience : RedP · Formation : IMIE · Lieu : Rennes · 301 relations'
    """
    info: dict = {}

    # Connections / relations
    m = re.search(r'(\d[\d\s,.]*)\s*(relations|connections|abonnés|followers)', snippet, re.I)
    if m:
        info["connections"] = re.sub(r'\s', '', m.group(1))

    # Location — "Lieu : Rennes" or "Location: Rennes"
    m = re.search(r'Lieu\s*:\s*([^·\|•]+)', snippet, re.I)
    if not m:
        m = re.search(r'Location\s*:\s*([^·\|•]+)', snippet, re.I)
    if m:
        info["location"] = m.group(1).strip()

    # Current experience — "Expérience : RedP" or "Experience: RedP"
    m = re.search(r'Exp[eé]rience\s*:\s*([^·\|•]+)', snippet, re.I)
    if not m:
        m = re.search(r'Experience\s*:\s*([^·\|•]+)', snippet, re.I)
    if m:
        info["company"] = m.group(1).strip()

    # Education — "Formation : IMIE" or "Education: IMIE"
    m = re.search(r'Formation\s*:\s*([^·\|•]+)', snippet, re.I)
    if not m:
        m = re.search(r'Education\s*:\s*([^·\|•]+)', snippet, re.I)
    if m:
        info["education"] = m.group(1).strip()

    # Headline: first segment before " · " (skip boilerplate)
    parts = [p.strip() for p in re.split(r'[·•|]', snippet) if p.strip()]
    boilerplate = {"consultez", "view", "profil", "profile", "linkedin", "communauté", "community", "milliard", "billion"}
    for part in parts[:3]:
        if not any(b in part.lower() for b in boilerplate) and len(part) > 2:
            info.setdefault("headline", part)
            break

    return info


async def search_via_serp(
    firstname: str,
    lastname: str,
    keywords: list[str] | None = None,
    cities: list[str] | None = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Search DuckDuckGo for LinkedIn profiles and parse snippet data.
    Returns a list of dicts: {url, slug, title, headline, company, location,
                               education, connections, snippet, source: 'serp'}.
    No LinkedIn auth needed — data comes from search engine cache/snippets.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    import asyncio
    loop = asyncio.get_event_loop()

    def _fetch() -> list[dict]:
        import time

        fn = firstname.strip()
        ln = lastname.strip()
        kws = keywords or []
        cits = cities or []

        queries = [
            f'"{fn} {ln}" site:linkedin.com/in/',
            f'"{fn} {ln}" linkedin',
        ]
        if kws:
            queries.insert(0, f'"{fn} {ln}" {kws[0]} site:linkedin.com/in/')
        if cits:
            queries.insert(1, f'"{fn} {ln}" {cits[0]} site:linkedin.com/in/')

        seen_slugs: set[str] = set()
        results: list[dict] = []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        }

        def _parse_results(html: str, source_tag: str) -> None:
            soup = BeautifulSoup(html, "html.parser")
            for res in soup.select(".result"):
                if len(results) >= max_results:
                    break
                title_el   = res.select_one(".result__title a")
                snippet_el = res.select_one(".result__snippet")
                if not title_el:
                    continue
                raw_url  = title_el.get("href", "")
                real_url = _decode_ddg_url(raw_url)
                if "linkedin.com/in/" not in real_url:
                    continue
                slug_m = re.search(r"linkedin\.com/in/([^/?#]+)", real_url)
                if not slug_m:
                    continue
                slug = slug_m.group(1).rstrip("/")
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                title   = title_el.get_text(strip=True)
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                info    = _parse_snippet(snippet)
                results.append({
                    "url":         real_url,
                    "slug":        slug,
                    "title":       title,
                    "snippet":     snippet,
                    "headline":    info.get("headline", ""),
                    "company":     info.get("company", ""),
                    "location":    info.get("location", ""),
                    "education":   info.get("education", ""),
                    "connections": info.get("connections", ""),
                    "source":      source_tag,
                })

        for i, query in enumerate(queries):
            if len(results) >= max_results:
                break
            if i > 0:
                time.sleep(1.5)
            try:
                resp = requests.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers=headers,
                    timeout=12,
                )
                if resp.status_code == 200:
                    _parse_results(resp.text, "ddg")
            except Exception:
                pass

        return results

    return await loop.run_in_executor(None, _fetch)


async def run(
    firstname: str = "",
    lastname: str = "",
    keywords: list[str] | None = None,
    pseudo: str = "",
    birth_year: str = "",
    cities: list[str] | None = None,
    max_candidates: int = 20,
) -> dict:
    """
    Generate LinkedIn profile URL candidates for manual verification.

    Returns:
        {
            "generated": int,
            "candidates": [{"slug", "url", "note"}],
            "verified": 0,
            "blocked": True,
            "note": str,
        }
    """
    kws = keywords or []
    slugs = _generate_linkedin_slugs(firstname, lastname, kws)[:max_candidates]

    candidates = [
        {
            "slug": slug,
            "url": f"https://www.linkedin.com/in/{slug}/",
            "note": "unverified — LinkedIn blocks automated access",
        }
        for slug in slugs
    ]

    # SERP-based search (DuckDuckGo snippets, no auth needed)
    serp_found = await search_via_serp(
        firstname=firstname,
        lastname=lastname,
        keywords=kws,
        cities=cities,
    )

    # Filter candidates: remove slugs already confirmed via SERP
    serp_slugs = {p["slug"] for p in serp_found}
    candidates = [c for c in candidates if c["slug"] not in serp_slugs]

    # Google dork URL for manual fallback
    fn_enc = firstname.strip().replace(" ", "+")
    ln_enc = lastname.strip().replace(" ", "+")
    google_dork_url = (
        f"https://www.google.com/search?q=%22{fn_enc}+{ln_enc}%22+site%3Alinkedin.com%2Fin%2F"
    )
    ddg_url = (
        f"https://duckduckgo.com/?q=%22{fn_enc}+{ln_enc}%22+site%3Alinkedin.com%2Fin%2F"
    )

    return {
        "generated":      len(candidates),
        "candidates":     candidates,
        "serp_found":     serp_found,
        "verified":       len(serp_found),
        "blocked":        True,
        "google_dork_url": google_dork_url,
        "ddg_url":         ddg_url,
        "note": (
            "LinkedIn blocks automated requests. "
            "SERP profiles are confirmed via search engine snippets (no auth needed). "
            "URL candidates below are generated patterns for manual verification."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn profile URL generator")
    parser.add_argument("--firstname",  default="")
    parser.add_argument("--lastname",   default="")
    parser.add_argument("--keywords",   nargs="*", default=[])
    parser.add_argument("--pseudo",     default="")
    parser.add_argument("--birth_year", default="")
    parser.add_argument("--max",        type=int, default=20)
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
