"""
Email permutation engine — pure logic, no LLM, no network calls.

Generates realistic email address combinations from name, birth year and keywords.
Keywords must be user-provided identifiers (nicknames, aliases).
City names and department codes must NOT be included — they produce useless candidates.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

DEFAULT_DOMAINS = [
    "gmail.com", "hotmail.com", "outlook.com",
    "yahoo.fr", "orange.fr", "sfr.fr",
    "laposte.net", "free.fr", "protonmail.com", "icloud.com",
]

SEPARATORS = [".", "", "_", "-"]   # dot first (most common in French emails)


def _norm(s: str) -> str:
    """Lowercase, remove accents (NFD), keep only [a-z0-9]."""
    s = s.lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def _year_variants(birth_year: Optional[str]) -> tuple[str, str]:
    """Returns (4-digit year, 2-digit suffix) or ('', '')."""
    if not birth_year:
        return "", ""
    m = re.match(r"(\d{4})", birth_year.strip())
    if not m:
        return "", ""
    yr4 = m.group(1)
    return yr4, yr4[2:]


def generate(
    firstname: str,
    lastname: str,
    birth_year: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    domains: Optional[list[str]] = None,
) -> list[str]:
    """
    Returns a deduplicated, ordered list of email candidates (most likely first).

    Priority order:
      1. keyword + name combos  (user alias is strongest signal)
      2. keyword + year
      3. keyword alone
      4. classic name combos (fn.ln, ln.fn, f.ln, fn.l)
      5. name + year
      6. firstname/lastname alone
    """
    fn = _norm(firstname)
    ln = _norm(lastname)

    # Split "firstname lastname" if passed as single string
    if not ln and " " in firstname:
        parts = firstname.strip().split(None, 1)
        fn, ln = _norm(parts[0]), _norm(parts[1])

    if not fn or not ln:
        return []

    fn1 = fn[0]    # first initial
    ln1 = ln[0]    # last initial
    kws = [_norm(k) for k in (keywords or []) if k.strip()]
    kws = [k for k in kws if k]

    yr4, yr2 = _year_variants(birth_year)
    target_domains = domains or DEFAULT_DOMAINS

    seen_bases: set[str] = set()
    bases: list[str] = []

    def _add(*items: str) -> None:
        for b in items:
            if b and b not in seen_bases:
                seen_bases.add(b)
                bases.append(b)

    # ── Priority 1: keyword + name combos ────────────────────────
    for kw in kws:
        for sep in SEPARATORS:
            _add(
                f"{fn}{sep}{kw}",           # jean.mchl
                f"{fn}{sep}{ln}{sep}{kw}",  # jean.dupont.mchl
                f"{kw}{sep}{fn}",           # mchl.jean
                f"{ln}{sep}{kw}",           # dupont.mchl
                f"{kw}{sep}{fn}{sep}{ln}",  # mchl.jean.dupont
            )

    # ── Priority 2: keyword + year ────────────────────────────────
    for kw in kws:
        if len(kw) < 4:   # short keyword = prefix/suffix, skip standalone+year forms
            continue
        if yr2:
            _add(f"{kw}{yr2}", f"{kw}.{yr2}", f"{kw}_{yr2}", f"{kw}-{yr2}")
            for sep in SEPARATORS:
                _add(f"{fn}{sep}{kw}{yr2}", f"{fn}{sep}{kw}{sep}{yr2}")
        if yr4:
            _add(f"{kw}{yr4}")

    # ── Priority 3: keyword alone (only for keywords ≥ 4 chars) ───
    for kw in kws:
        if len(kw) >= 4:
            _add(kw)

    # ── Priority 4: classic name combos ──────────────────────────
    for sep in SEPARATORS:
        _add(
            f"{fn}{sep}{ln}",   # jean.dupont
            f"{ln}{sep}{fn}",   # dupont.jean
            f"{fn1}{sep}{ln}",  # j.dupont
            f"{fn}{sep}{ln1}",  # jean.d
        )

    # ── Priority 5: name + year ───────────────────────────────────
    if yr4:
        # Common patterns: firstname90, lastname90, fn.ln90, fn.ln.1990
        _add(f"{fn}{yr2}", f"{fn}{yr4}")
        _add(f"{ln}{yr2}", f"{ln}{yr4}")
        for sep in SEPARATORS:
            _add(
                f"{fn}{sep}{ln}{yr2}",         # jean.dupont90
                f"{fn}{sep}{ln}{yr4}",         # jean.dupont1990
                f"{fn1}{sep}{ln}{yr2}",        # j.dupont90
                f"{fn}{sep}{ln}{sep}{yr2}",    # jean.dupont.90
                f"{fn}{sep}{ln}{sep}{yr4}",    # jean.dupont.1990
                f"{fn1}{sep}{ln}{sep}{yr2}",   # j.dupont.90
            )

    # ── Priority 6: standalone name (edge cases) ──────────────────
    _add(fn, ln)

    # ── Build emails ──────────────────────────────────────────────
    email_re = re.compile(r"^[a-z0-9][a-z0-9._+-]*@[a-z0-9.-]+\.[a-z]{2,}$")
    result: list[str] = []
    result_seen: set[str] = set()

    for base in bases:
        for domain in target_domains:
            email = f"{base}@{domain}"
            if email not in result_seen and email_re.match(email):
                result_seen.add(email)
                result.append(email)

    return result
