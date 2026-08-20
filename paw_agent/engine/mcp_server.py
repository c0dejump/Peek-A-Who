"""
MCP Server — PAW OSINT Tools (thin-wrapper edition)

All business logic lives in skills/. This file is a thin MCP transport layer
kept for external tool-calling integrations (LLM agents, Dify, LangChain, etc.).
The internal pipeline (pipeline.py) calls skills directly without starting this server.

Tools:
  - generate_permutations  : generate all email candidates, returns a session_id
  - validate_all           : validate EVERY candidate from a session
  - validate_batch         : validate a small explicit list (for direct use)
  - validate_email         : validate a single email
  - check_hibp             : check breach history (HaveIBeenPwned)
  - check_google_account   : GHunt — Google account OSINT (profile, Maps, Calendar…)
  - check_etymology        : Etymology + geographic distribution of a French surname (filae.com)
"""
from __future__ import annotations

import logging
import os
import sys
import uuid

logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mcp.server.fastmcp import FastMCP
from paw_agent.engine.permuter import generate as generate_emails

# ── Skill imports (all logic lives here now) ───────────────────
from skills.email.smtp_validate import run_sync as _smtp_run, validate_batch as _smtp_batch, validate_all as _smtp_validate_all
from skills.email.hibp import run_sync as _hibp_run
from skills.email.ghunt import run_sync as _ghunt_run
from skills.identity.etymology import run_sync as _etymology_run

def _smart_validate(email: str) -> dict:
    return _smtp_run(email)

mcp = FastMCP(
    "paw-email-osint",
    instructions="Email OSINT tools: generate candidate addresses, validate existence, check breaches.",
)

# In-memory store: session_id → list of email candidates
_SESSIONS: dict[str, list[str]] = {}


# ── Tool 1 : Generate candidates ──────────────────────────────

@mcp.tool()
def generate_permutations(
    firstname: str,
    lastname: str,
    birth_year: str = "",
    keywords: str = "",
    domains: str = "",
) -> dict:
    """
    Generate all email candidates from the target's identity.
    All candidates are stored server-side and returned as a session_id.
    Pass that session_id to validate_all to check every candidate.

    Args:
        firstname:  First name only — e.g. "Jean"
        lastname:   Last name only — e.g. "Dupont"
        birth_year: Birth year e.g. "1990" — optional
        keywords:   Comma-separated keywords e.g. "paris,football" — optional
        domains:    Comma-separated domains to restrict e.g. "gmail.com,outlook.com"
    """
    firstname = firstname.strip()
    lastname  = lastname.strip()

    # Auto-split if the LLM passed the full name as firstname
    if not lastname and " " in firstname:
        parts     = firstname.split(None, 1)
        firstname = parts[0]
        lastname  = parts[1]

    kws  = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
    doms = [d.strip() for d in domains.split(",") if d.strip()] if domains else None

    if not firstname or not lastname:
        return {"error": "Both firstname and lastname are required."}

    candidates = generate_emails(
        firstname=firstname,
        lastname=lastname,
        birth_year=birth_year or None,
        keywords=kws,
        domains=doms,
    )

    session_id = str(uuid.uuid4())[:8]
    _SESSIONS[session_id] = candidates

    return {
        "session_id": session_id,
        "total": len(candidates),
        "preview": candidates[:5],
        "next_step": f'Call validate_all with session_id="{session_id}" to validate every candidate.',
    }


# ── Tool 2 : Validate ALL candidates from a session ───────────

@mcp.tool()
def validate_all(session_id: str, max_candidates: int = 10_000) -> dict:
    """
    Validate ALL email candidates from a previous generate_permutations call.

    Args:
        session_id:     The session_id returned by generate_permutations
        max_candidates: Safety ceiling (default 10 000 — effectively unlimited)
    """
    candidates = _SESSIONS.get(session_id)
    if candidates is None:
        return {"error": f"Unknown session_id '{session_id}'. Call generate_permutations first."}

    max_candidates = max(1, int(max_candidates))
    to_check = candidates[:max_candidates]

    result = _smtp_validate_all(to_check)
    valid = result.get("valid", [])

    del _SESSIONS[session_id]

    return {
        "checked":           len(to_check),
        "total_in_session":  len(candidates),
        "valid_count":       len(valid),
        "valid":             valid,
        "next_step": "Call check_hibp for each email in the 'valid' list." if valid else "No valid emails found.",
    }


# ── Tool 2b : Get candidates slice from a session ─────────────

@mcp.tool()
def get_candidates(session_id: str, offset: int = 0, limit: int = 30) -> dict:
    """
    Return a slice of email candidates from a previous generate_permutations session.
    Use with validate_batch to validate in chunks and track progress in real time.

    Args:
        session_id: The session_id returned by generate_permutations
        offset:     Start index (0-based)
        limit:      Number of candidates to return (max 100)
    """
    candidates = _SESSIONS.get(session_id)
    if candidates is None:
        return {"error": f"Unknown session_id '{session_id}'. Call generate_permutations first."}

    limit = max(1, int(limit))
    chunk = candidates[offset: offset + limit]
    return {
        "session_id": session_id,
        "offset":     offset,
        "count":      len(chunk),
        "total":      len(candidates),
        "candidates": chunk,
        "has_more":   (offset + len(chunk)) < len(candidates),
    }


# ── Tool 3 : Validate a small explicit list ───────────────────

@mcp.tool()
def validate_batch(emails: list, max_results: int = 20) -> dict:
    """
    Validate an explicit list of email addresses (MX + SMTP check).
    Use validate_all when working with a full session; use this for ad-hoc lists.

    Args:
        emails:      List of email addresses to validate
        max_results: Maximum number to test (default 20)
    """
    return _smtp_batch(list(emails), max_results)


# ── Tool 4 : Validate a single email ─────────────────────────

@mcp.tool()
def validate_email(email: str) -> dict:
    """
    Check if a single email address exists (MX + SMTP).

    Args:
        email: Email address to validate
    """
    return _smtp_run(email)


# ── Tool 5 : HIBP breach check ────────────────────────────────

@mcp.tool()
def check_hibp(email: str) -> dict:
    """
    Check if an email was exposed in known data breaches (HaveIBeenPwned).

    Args:
        email: Email address to check
    """
    return _hibp_run(email)


# ── Tool 6 : Etymology + geographic distribution (filae.com) ─

@mcp.tool()
def check_etymology(lastname: str, birth_year: str = "") -> dict:
    """
    Retrieve French demographic data for a surname from filae.com:
    bearer count since 1890, births by 25-year period, national rank, geographic distribution.
    If birth_year is provided, highlights how many people with this surname were born in that period,
    giving investigative context (rarity, likely region, generational density).

    Args:
        lastname:   The surname to look up (works best for French surnames)
        birth_year: Optional birth year (e.g. "1990") to contextualise birth period statistics
    """
    return _etymology_run(lastname, birth_year)


# ── Tool 7 : GHunt — Google account OSINT ────────────────────

@mcp.tool()
def check_google_account(email: str) -> dict:
    """
    Run GHunt on a Gmail address to confirm account existence and gather OSINT data:
    profile name, photo, Gaia ID, last profile edit, Maps reviews, Calendar events, Play Games.
    Requires: pip install ghunt && ghunt login (one-time browser authentication).

    Args:
        email: Gmail address to investigate (must end with @gmail.com or @googlemail.com)
    """
    return _ghunt_run(email)


# ── Tool 8 : Reverse image search ────────────────────────────

@mcp.tool()
def reverse_image_search(image_url: str) -> dict:
    """
    Reverse-image-search a photo by URL to find where else it appears online and
    confirm identity. Returns ready-to-open engine links (Yandex — best for faces,
    Google Lens, Bing, TinEye) plus best-effort matched pages. No API key needed.

    Args:
        image_url: Public URL of the image to trace (e.g. a profile picture)
    """
    from skills.image.reverse_search import run_sync as _ris
    return _ris(image_url)


# ── Tool 9 : Breach / leak-data search ───────────────────────

@mcp.tool()
def leak_search(query: str, query_type: str = "auto") -> dict:
    """
    Search breach/leak databases (Dehashed, LeakCheck, IntelX) for an email,
    username, phone, name, IP or domain, returning leaked content (linked
    emails, usernames, passwords/hashes, phones, addresses). Uses whichever of
    DEHASHED_KEY / LEAKCHECK_KEY / INTELX_KEY is configured.

    Args:
        query: identifier to search
        query_type: auto | email | username | phone | name | ip | domain
    """
    from skills.breach.leak_search import run_sync as _leak
    return _leak(query, query_type=query_type)


# ── Tool 10 : Geo-imagery (Street View + nearby photos) ──────

@mcp.tool()
def geo_imagery(location: str = "", lat: float = None, lon: float = None) -> dict:
    """
    Visually verify a place and surface photos taken there. Returns a Google
    Street View link at the exact spot plus geotagged Flickr photos nearby
    (FLICKR_KEY for auto photos; static Street View thumb needs GOOGLE_MAPS_KEY).

    Args:
        location: place/address to geocode (or pass lat+lon directly)
    """
    from skills.geo.imagery import run_sync as _geo
    return _geo(lat=lat, lon=lon, location=location)


# ── Tool 11 : Telegram public profile ────────────────────────

@mcp.tool()
def telegram_lookup(username: str) -> dict:
    """
    Look up a public Telegram @username (no key): existence, display name, bio,
    profile photo, type (user/channel/group) and subscriber count.
    """
    from skills.messaging.telegram import run_sync as _tg
    return _tg(username)


@mcp.tool()
def messaging_by_number(phone: str) -> dict:
    """
    Click-to-chat deep-links (WhatsApp, Signal, Viber, Telegram) for a phone
    number, to check which messaging apps the number is on. No key.
    """
    from skills.messaging.by_number import run_sync as _mbn
    return _mbn(phone)


# ── Tool 12 : French INSEE death records ─────────────────────

@mcp.tool()
def death_records(firstname: str = "", lastname: str = "", birth_year: str = "") -> dict:
    """
    Search the official French INSEE death file (deces.matchid.io, free, no key)
    by name + optional birth year. Returns birth/death dates, places and age —
    to check whether a missing person is recorded as deceased.
    """
    from skills.records.deces import run_sync as _dec
    return _dec(firstname=firstname, lastname=lastname, birth_year=birth_year)


if __name__ == "__main__":
    mcp.run(transport="stdio")
