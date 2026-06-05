"""
Email permutation engine — pure logic, no LLM, no network calls.
Generates realistic email address combinations from name, birth year and keywords.
"""
from __future__ import annotations

import re
from itertools import product
from typing import Optional

DEFAULT_DOMAINS = [
    "gmail.com", "hotmail.com", "outlook.com",
    "yahoo.fr", "orange.fr", "sfr.fr",
    "laposte.net", "free.fr", "protonmail.com", "icloud.com",
]

SEPARATORS = ["", ".", "_", "-"]


def _clean(s: str) -> str:
    return s.lower().strip()


def _year_variants(birth_year: Optional[str]) -> list[str]:
    if not birth_year:
        return [""]
    y = birth_year.split("-")[0]
    return ["", y, y[2:]]


def generate(
    firstname: str,
    lastname: str,
    birth_year: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    domains: Optional[list[str]] = None,
) -> list[str]:
    """
    Returns a deduplicated, ordered list of email candidates (most likely first).
    """
    f = _clean(firstname)
    l = _clean(lastname)

    # Guard: split full name if only firstname was provided
    if not l and " " in f:
        parts = f.split(None, 1)
        f, l = parts[0], parts[1].replace(" ", "")

    if not f or not l:
        return []

    fi = f[0]
    li = l[0]
    kws = [_clean(k) for k in (keywords or [])]
    years = _year_variants(birth_year)
    target_domains = domains or DEFAULT_DOMAINS

    bases: list[str] = []

    for sep in SEPARATORS:
        bases += [
            f"{f}{sep}{l}",
            f"{l}{sep}{f}",
            f"{fi}{sep}{l}",
            f"{f}{sep}{li}",
        ]

    for sep, y in product(SEPARATORS, years):
        if not y:
            continue
        bases += [
            f"{f}{sep}{l}{y}",
            f"{fi}{sep}{l}{y}",
            f"{f}{sep}{l}{sep}{y}",
        ]

    for kw in kws:
        for sep in SEPARATORS:
            bases += [
                f"{f}{sep}{l}{sep}{kw}",
                f"{l}{sep}{f}{sep}{kw}",
                f"{f}{sep}{kw}",
                f"{l}{sep}{kw}",
                f"{kw}{sep}{f}{sep}{l}",
                f"{kw}{sep}{l}{sep}{f}",
            ]

    email_re = re.compile(r'^[a-z0-9][a-z0-9._+-]*@[a-z0-9.-]+\.[a-z]{2,}$')
    seen: set[str] = set()
    candidates: list[str] = []

    for base, domain in product(dict.fromkeys(bases), target_domains):
        email = f"{base}@{domain}"
        if email not in seen and email_re.match(email):
            seen.add(email)
            candidates.append(email)

    return candidates
