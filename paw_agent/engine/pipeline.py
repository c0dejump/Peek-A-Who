"""
Clean investigation pipeline — no MCP subprocess.

Replaces the MCP-based agent.py entry point with a direct skill-calling
orchestrator:
  Phase 1 (passive):   imports helpers from agent.py (transitional)
  Phase 2 (active):    calls skills directly (smtp_validate, ghunt, hibp, etymology)
  LLM synthesis:       calls litellm directly at checkpoint + final summary

Signature matches run_agent() in agent.py so runner.py can swap imports
without any other changes.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Callable, Optional

# ── Phase 1 helpers (transitional — will move to skills/ later) ────────────
from paw_agent.engine.agent import (
    _ACCENT_MAP,
    USE_LLM,
    _get_backend,
    _make_emit,
    _cities_to_keywords,
    _generate_ig_usernames,
    _prevalidate_usernames,
    _search_diplomas_direct,
    _search_phone_direct,
    _search_instagram_direct,
    _search_social_platforms_direct,
    _enrich_activity_signals,
    _search_sirene_pappers_direct,
    _diploma_relevance,
)

# ── Social media skills ────────────────────────────────────────────────────
from skills.social_media.ig_lookup import run_sync as _ig_lookup
from skills.social_media.tiktok import run as _tiktok_run
from skills.social_media.linkedin import run as _linkedin_run

# ── Email permutation (direct, no MCP) ─────────────────────────────────────
from paw_agent.engine.permuter import generate as _generate_emails

# ── Skills (Phase 2, no MCP) ───────────────────────────────────────────────
from skills.identity.etymology import run_sync as _etymology
from skills.email.smtp_validate import validate_all as _smtp_validate_all
from skills.email.ghunt import run_sync as _ghunt
from skills.email.hibp import run_sync as _hibp

# ── LLM (direct litellm, no MCP) ──────────────────────────────────────────
try:
    from litellm import completion as llm_completion
    _HAS_LLM = True
except ImportError:
    _HAS_LLM = False


def _get_llm_timeout() -> int:
    """Return LLM request timeout in seconds.
    LLM_TIMEOUT env var overrides; otherwise 300s for Ollama (large local models
    are slow), 90s for remote API providers."""
    import os
    raw = os.environ.get("LLM_TIMEOUT", "").strip()
    if raw.isdigit():
        return int(raw)
    backend = os.environ.get("LLM_BACKEND", "")
    return 300 if backend.startswith("ollama/") else 90


def _check_ollama() -> tuple[bool, str]:
    """Quick health check — returns (ok, error_msg).
    Only called when the backend is an Ollama model."""
    import os, requests as _req
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        r = _req.get(f"{host}/api/tags", timeout=3)
        if r.status_code == 200:
            return True, ""
        return False, f"Ollama returned HTTP {r.status_code}"
    except Exception as exc:
        return False, f"Ollama unreachable at {host} — is it running? ({exc})"


def _blank_report(firstname, lastname, birth_year, all_keywords, cities) -> dict:
    return {
        "target":        {"firstname": firstname, "lastname": lastname,
                          "birth_year": birth_year, "keywords": all_keywords,
                          "cities": cities},
        "demographics":  {},
        "diplomas":      {"theses": [], "publications": [], "bac_results": [],
                          "brevet_results": [], "total_theses": 0, "total_pubs": 0,
                          "total_bac": 0, "total_brevet": 0},
        "business":      {"sirene": [], "pappers": [], "total_sirene": 0, "total_pappers": 0},
        "phone":         {},
        "social_media":  {},
        "timeline":      {},
        "emails":        {"smtp_valid": [], "ghunt_confirmed": [], "breached": []},
        "ghunt_details": [],
        "hibp_details":  [],
        "llm_summary":   "",
        "analysis":      {},
        "risk_level":    "none",
    }


async def run_investigation(
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
    Main entry point — same signature as agent.run_agent().
    Runs all phases with direct skill calls (no MCP subprocess).
    """
    emit    = _make_emit(callback)
    backend = _get_backend() if USE_LLM and _HAS_LLM else None

    # Pre-flight Ollama health check
    if backend and backend.startswith("ollama/"):
        ok, err = _check_ollama()
        if not ok:
            emit(f"  ⚠  {err}")
            emit("  ℹ  LLM steps will be skipped — start Ollama and re-run.")
            backend = None

    llm_timeout = _get_llm_timeout()

    _tok = {"prompt": 0, "completion": 0}

    def _emit_tokens(resp) -> None:
        u = getattr(resp, "usage", None)
        if not u:
            return
        _tok["prompt"]     += getattr(u, "prompt_tokens", 0)
        _tok["completion"] += getattr(u, "completion_tokens", 0)
        total = _tok["prompt"] + _tok["completion"]
        if event_callback:
            event_callback({
                "type":       "token_usage",
                "prompt":     _tok["prompt"],
                "completion": _tok["completion"],
                "total":      total,
            })
        emit(f"  🪙  Tokens — prompt: {_tok['prompt']:,}  completion: {_tok['completion']:,}  total: {total:,}")

    city_extras  = _cities_to_keywords(cities or [])
    all_keywords = list(keywords)
    for k in city_extras:
        if k not in all_keywords:
            all_keywords.append(k)

    if city_extras:
        emit(f"  🏙️  Cities → extra keywords: {', '.join(city_extras)}")

    active_modules = list(modules) if modules else ["demographics", "diplomas", "email", "phone", "social_media"]
    report = _blank_report(firstname, lastname, birth_year, all_keywords, cities or [])

    model_label = backend if backend else "no LLM configured"
    emit(f"{'━' * 54}")
    emit(f"  PEEK-A-WHO  [{model_label}]")
    emit(f"{'━' * 54}")
    emit("")

    # ── Step 0: Etymology (filae.com) ──────────────────────────
    if "demographics" in active_modules and lastname:
        emit(f"  💭 [Step 0] Surname demographics — {lastname}…")
        try:
            loop = asyncio.get_event_loop()
            ety = await loop.run_in_executor(None, _etymology, lastname, birth_year)
            if ety.get("bearers_since_1890"):
                freq_str = f" (freq. {ety['france_frequency']})" if ety.get("france_frequency") else ""
                emit(f"  👥  {ety['bearers_since_1890']:,} bearers in France — rank: {ety.get('national_rank','?')}{freq_str}")
            elif ety.get("total_worldwide"):
                emit(f"  🌍  {ety['total_worldwide']:,} bearers worldwide — most prevalent: {ety.get('most_prevalent_in','?')} — world rank: {ety.get('world_rank','?')}")
            if ety.get("name_origin"):
                emit(f"  📖  Origin: {ety['name_origin'][:120]}")
            dist = ety.get("geographic_distribution", [])
            if dist:
                top = ", ".join(f"{d['department']} ({d['count']})" for d in dist[:5])
                emit(f"  🗺️   Top countries: {top}")
            elif ety.get("note"):
                emit(f"  ℹ  {ety['note']}")
            report["demographics"] = {
                "bearers_since_1890": ety.get("bearers_since_1890"),
                "total_worldwide":    ety.get("total_worldwide"),
                "national_rank":      ety.get("national_rank"),
                "france_frequency":   ety.get("france_frequency"),
                "world_rank":         ety.get("world_rank"),
                "most_prevalent_in":  ety.get("most_prevalent_in"),
                "name_origin":        ety.get("name_origin"),
                "top_departments":    dist[:5],
            }
        except Exception as exc:
            emit(f"  ℹ  Surname lookup unavailable: {exc}")
        emit("")

    # ── Step 0.5: Diplomas (theses.fr / HAL / bac / brevet) ────
    birth_yr_int: int | None = None
    if birth_year:
        m = re.match(r"(\d{4})", birth_year)
        if m:
            birth_yr_int = int(m.group(1))

    if "diplomas" in active_modules and firstname and lastname:
        emit(f"  💭 [Step 0.5] Diplomas — {firstname} {lastname}…")
        try:
            dip = await _search_diplomas_direct(firstname, lastname, cities or [], birth_year)
            n_theses = dip.get("total_theses", 0)
            n_pubs   = dip.get("total_pubs", 0)
            bac      = dip.get("bac_results", [])
            brevet   = dip.get("brevet_results", [])

            if n_theses or n_pubs:
                emit(f"  🎓  {n_theses} thesis/theses — {n_pubs} publication(s)")
                for th in dip.get("theses", []):
                    yr   = f" ({th['year']})" if th.get("year") else ""
                    inst = f" — {th['institution']}" if th.get("institution") else ""
                    th["relevance"] = _diploma_relevance(th.get("year"), birth_yr_int, "thesis")
                    emit(f"  📄  {th['title'][:80]}{yr}{inst} [{th['relevance']}]")
            if bac:
                emit(f"  🎓  {len(bac)} bac result(s):")
                for b in bac:
                    emit(f"  📜  {b['name']} — {b.get('diploma','?')} ({b['year']}, age {b['age_at_bac']})")
            elif birth_yr_int:
                emit(f"  ℹ  No bac result (years {birth_yr_int+17}–{birth_yr_int+20})")
            if brevet:
                emit(f"  🎓  {len(brevet)} brevet result(s):")
                for b in brevet:
                    emit(f"  📜  {b['name']} (brevet {b['year']}, age {b['age_at_brevet']})")

            if not n_theses and not n_pubs and not bac and not brevet:
                emit("  ℹ  No academic records found")
            report["diplomas"] = dip
        except Exception as exc:
            emit(f"  ℹ  Diploma search unavailable: {exc}")
        emit("")

    # ── Step 0.7: Business registries ──────────────────────────
    if lastname:
        emit("  💭 [Step 0.7] Business registries — SIRENE / Pappers…")
        try:
            biz     = await _search_sirene_pappers_direct(firstname, lastname, cities or [])
            sirene  = biz.get("sirene", [])
            pappers = biz.get("pappers", [])
            if sirene:
                emit(f"  🏢  {biz.get('total_sirene',0)} SIRENE record(s):")
                for s in sirene:
                    active = "✓" if s.get("status","").lower().startswith("a") else "✗ closed"
                    city   = f" — {s['city']}" if s.get("city") else ""
                    emit(f"  📋  [{active}] SIREN {s['siren']} — {s.get('name','?')}{city}")
            else:
                emit(f"  ℹ  No SIRENE record for {firstname} {lastname}")
            if pappers:
                emit(f"  🔍  Pappers — {biz.get('total_pappers',0)} match(es):")
                for p in pappers:
                    for c in p.get("companies", []):
                        role = f" [{c.get('role','')}]" if c.get("role") else ""
                        emit(f"  🏛️  {p['name']}{role} → {c.get('name','?')} (SIREN {c.get('siren','')})")
            report["business"] = biz
        except Exception as exc:
            emit(f"  ℹ  Business registry unavailable: {exc}")
        emit("")

    # ── Step 0.8: Annuaires (search links) ─────────────────────
    if firstname or lastname or cities:
        from urllib.parse import quote_plus as _qp
        full_name = f"{firstname} {lastname}".strip()
        city_hint = (cities or [""])[0]
        pb_url = (f"https://www.pagesjaunes.fr/pagesblanches/chercherlespersonnes"
                  f"?quoiqui={_qp(full_name)}&ou={_qp(city_hint)}")
        pj_url = (f"https://www.pagesjaunes.fr/annuaire/chercherlespros"
                  f"?quoiqui={_qp(full_name)}&ou={_qp(city_hint)}")
        emit("  🔗 [Step 0.8] Phone Directories (Cloudflare-protected — open manually):")
        emit(f"  📋  Pages Blanches : {pb_url}")
        emit(f"  📋  Pages Jaunes   : {pj_url}")
        emit("")
        report["annuaires"] = {
            "pages_blanches": pb_url,
            "pages_jaunes":   pj_url,
            "note": "Cloudflare-protected — open links manually in a browser",
        }

    # ── Step 0.9: Phone OSINT ────────────────────────────────────
    if "phone" in active_modules and phone:
        emit(f"  💭 [Step 0.9] Phone OSINT — {phone}…")
        try:
            ph = await _search_phone_direct(phone, firstname, lastname)
            if ph.get("error"):
                emit(f"  ✗  Phone parse error: {ph['error']}")
            else:
                validity = "✓ valid" if ph.get("valid") else "✗ invalid"
                emit(f"  📱  {ph['international'] or ph['e164']}  [{ph['type']}]  {validity}")
                if ph.get("carrier"):  emit(f"  📡  Carrier : {ph['carrier']}")
                if ph.get("region"):   emit(f"  🌍  Region  : {ph['region']}")
                platforms = ph.get("ignorant_platforms", [])
                if platforms:
                    found     = [p["site"] for p in platforms if p["status"] == "found"]
                    limited   = [p["site"] for p in platforms if p["status"] == "rate_limited"]
                    not_found = [p["site"] for p in platforms if p["status"] == "not_found"]
                    emit(f"  🔍  ignorant — {len(platforms)} platforms:")
                    if found:     emit(f"  ✅    Registered on : {', '.join(found)}")
                    if limited:   emit(f"  ⚠    Rate-limited  : {', '.join(limited)}")
                    if not_found: emit(f"  ➖    Not found     : {', '.join(not_found)}")
            report["phone"] = ph
        except Exception as exc:
            emit(f"  ℹ  Phone OSINT unavailable: {exc}")
        emit("")

    # ── Generate username candidates once (shared by steps 0.93–0.97) ──────
    _ig_candidates: list[str] = []
    _validated_usernames: list[str] = []  # confirmed on at least 1 platform

    # Social media search requires enough context to produce non-trivial candidates.
    # firstname alone generates hyper-generic usernames (e.g. "thomas") that flood
    # every platform and produce useless noise.
    _social_has_context = bool(
        pseudo                          # pseudo is always specific enough
        or (firstname and lastname)     # firstname + lastname → real combos
        or (firstname and keywords)     # firstname + keyword
        or (firstname and cities)       # firstname + city
        or (firstname and birth_year)   # firstname + year
        or (lastname and not firstname) # lastname alone → acceptable
    )

    if "social_media" in active_modules and _social_has_context:
        dept_codes = [k for k in city_extras if re.match(r"^\d{2}$", k)]
        _ig_candidates = _generate_ig_usernames(
            firstname, lastname, birth_year,
            keywords=keywords, pseudo=pseudo, dept_codes=dept_codes,
        )
    elif "social_media" in active_modules and not _social_has_context:
        emit("  ⏭  [Step 0.93–0.97] Social media skipped — need last name, pseudo, keyword or city alongside first name")

    # ── Step 0.93: Username pre-validation (maigret + sherlock, 36 sites) ──
    _prevalidation: dict = {}
    if _ig_candidates:
        emit(f"  💭 [Step 0.93] Pre-validating {len(_ig_candidates)} candidates (maigret + sherlock, 36 sites)…")
        try:
            prevalidated = await _prevalidate_usernames(
                _ig_candidates,
                firstname=firstname,
                lastname=lastname,
                keywords=all_keywords,
                birth_year=birth_year,
                pseudo=pseudo,
            )

            _validated_usernames = prevalidated["validated"]
            hits = prevalidated["hits"]

            if not prevalidated.get("maigret_ok", True):
                emit("  ℹ  maigret not installed (pip install maigret)")
            if not prevalidated.get("sherlock_ok", True):
                emit("  ℹ  sherlock not installed (pip install sherlock-project)")

            if _validated_usernames:
                emit(f"  ✅  {len(_validated_usernames)} candidate(s) found on ≥1 targeted site:")
                show_urls = len(_validated_usernames) <= 20
                for un in _validated_usernames[:20]:
                    un_hits = hits.get(un, [])
                    sites_str = ", ".join(h["site"] for h in un_hits[:5])
                    extra = f" (+{len(un_hits)-5} more)" if len(un_hits) > 5 else ""
                    emit(f"  🎯  @{un} → {sites_str}{extra}")
                    if show_urls:
                        for h in un_hits:
                            if h.get("url"):
                                emit(f"       🔗 {h['site']}: {h['url']}")
                if len(_validated_usernames) > 20:
                    emit(f"  … and {len(_validated_usernames) - 20} more")
            else:
                emit("  ℹ  No candidates found on any of the 36 targeted sites")

            emit(f"  📊  {len(prevalidated.get('not_found', []))} candidates excluded — not found on any site")

            if prevalidated.get("location_relevant"):
                emit(f"  📍  Location/Sport: {', '.join(p['site'] for p in prevalidated['location_relevant'][:8])}")
            if prevalidated.get("marketplace"):
                emit(f"  🛒  Marketplace: {', '.join(p['site'] for p in prevalidated['marketplace'][:6])}")
            if prevalidated.get("gaming"):
                emit(f"  🎮  Gaming: {', '.join(p['site'] for p in prevalidated['gaming'][:6])}")
            if prevalidated.get("social"):
                emit(f"  💬  Social: {', '.join(p['site'] for p in prevalidated['social'][:8])}")

            # Only validated usernames go to Instagram and subsequent steps
            _ig_candidates = _validated_usernames
            if not _ig_candidates:
                emit("  ⚠  No candidates confirmed — nothing to pass to next steps")

            # Activity enrichment on pre-validation hits
            if prevalidated.get("total_found", 0) > 0:
                act = await _enrich_activity_signals(prevalidated)
                if act.get("reddit"):
                    rd = act["reddit"]
                    emit(f"  📅  Reddit: last active {rd['last_active']}")
                    if rd.get("subreddits"):
                        emit(f"  🗂️   Subreddits: {', '.join(rd['subreddits'][:5])}")
                if act.get("github"):
                    gh = act["github"]
                    loc_s = f" — {gh['location']}" if gh.get("location") else ""
                    emit(f"  💻  GitHub @{gh['username']}: last activity {gh['last_active']}{loc_s}")
                for _sk in ("vinted", "strava", "komoot", "leboncoin"):
                    if act.get(_sk):
                        _s = act[_sk]
                        city_s = f" — 📍 {_s['city']}" if _s.get("city") else ""
                        emit(f"  {_s.get('icon','📌')}  {_s['label']} @{_s['username']}{city_s}")
                prevalidated["activity_signals"] = act

            # Build validated_profiles list for the report panel
            prevalidated["validated_profiles"] = [
                {
                    "username": un,
                    "hit_count": len(hits.get(un, [])),
                    "sites": [{"site": h["site"], "url": h.get("url", ""), "tool": h.get("tool", "")}
                              for h in hits.get(un, [])],
                }
                for un in _validated_usernames
            ]

            _prevalidation = prevalidated
            report.setdefault("social_media", {})["maigret"] = prevalidated

        except Exception as exc:
            emit(f"  ℹ  Pre-validation unavailable: {exc}")
        emit("")

    # ── Step 0.95: Instagram ─────────────────────────────────────
    if "social_media" in active_modules and _social_has_context:
        emit(f"  💭 [Step 0.95] Instagram username search — {len(_ig_candidates)} candidates…")
        emit(f"  📱  First: {', '.join(_ig_candidates[:5])}")
        try:
            ig = await _search_instagram_direct(_ig_candidates, firstname, lastname, keywords=all_keywords)
            found = ig.get("found", [])
            emit(f"  🔍  Checked {ig['checked']}/{ig['generated']} — {len(found)} profile(s) found")
            for p in found:
                dn       = f' — "{p["display_name"]}"' if p.get("display_name") else ""
                age_note = f" (first seen {p['first_seen']})" if p.get("first_seen") else ""
                emit(f"  ✅  @{p['username']}{dn}{age_note} [{p['relevance']}/10]")
            if not found:
                if ig.get("blocked"):
                    emit("  ⚠  Instagram: rate-limited or login wall — checked fewer candidates")
                else:
                    emit("  ℹ  No Instagram profiles found")
            report["social_media"] = {"instagram": ig}

            # ── Step 0.95b: ig_lookup — obfuscated email + phone ─────
            if found:
                emit(f"  💭 [Step 0.95b] ig_lookup — {len(found)} profile(s)…")
                loop = asyncio.get_event_loop()
                ig_lookups: list[dict] = []
                for prof in found:
                    try:
                        lk = await loop.run_in_executor(None, _ig_lookup, prof["username"], phone)
                        if lk.get("status") == "found":
                            parts: list[str] = []
                            if lk.get("obfuscated_email"):
                                parts.append(f"email: {lk['obfuscated_email']}")
                            if lk.get("obfuscated_phone"):
                                parts.append(f"phone: {lk['obfuscated_phone']}")
                            if lk.get("phone_match"):
                                parts.append("⚡ PHONE MATCH")
                            emit(f"  🔍  @{prof['username']} → {' | '.join(parts) if parts else '(no data)'}")
                        elif lk.get("status") == "rate_limited":
                            emit(f"  ⚠  ig_lookup rate-limited for @{prof['username']}")
                        else:
                            emit(f"  ℹ  ig_lookup: @{prof['username']} → {lk.get('status','?')}")
                        ig_lookups.append(lk)
                    except Exception as exc:
                        emit(f"  ℹ  ig_lookup failed for @{prof['username']}: {exc}")
                if ig_lookups:
                    report["social_media"]["ig_lookups"] = ig_lookups

        except Exception as exc:
            emit(f"  ℹ  Instagram search unavailable: {exc}")
        emit("")

    # ── Step 0.95c: TikTok ──────────────────────────────────────
    if "social_media" in active_modules and _social_has_context:
        emit(f"  💭 [Step 0.95c] TikTok username search — {len(_ig_candidates)} candidates…")
        try:
            tt = await _tiktok_run(
                firstname=firstname,
                lastname=lastname,
                keywords=keywords,
                pseudo=pseudo,
                birth_year=birth_year,
                max_candidates=60,
            )
            tt_found = tt.get("found", [])
            emit(f"  🔍  Checked {tt['checked']}/{tt['generated']} — {len(tt_found)} profile(s) found")
            for p in tt_found:
                dn = f' — "{p["display_name"]}"' if p.get("display_name") else ""
                emit(f"  ✅  @{p['username']}{dn} [{p['relevance']}/10] {p['url']}")
            if not tt_found:
                emit("  ℹ  No TikTok profiles found")
            report["social_media"]["tiktok"] = tt
        except Exception as exc:
            emit(f"  ℹ  TikTok search unavailable: {exc}")
        emit("")

    # ── Step 0.95d: LinkedIn (URL candidates — not verifiable) ───
    if "social_media" in active_modules and _social_has_context:
        emit(f"  💭 [Step 0.95d] LinkedIn profile candidates…")
        try:
            li = await _linkedin_run(
                firstname=firstname,
                lastname=lastname,
                keywords=keywords,
                pseudo=pseudo,
                birth_year=birth_year,
            )
            serp = li.get("serp_found", [])
            candidates = li.get("candidates", [])
            if serp:
                emit(f"  ✅  LinkedIn SERP — {len(serp)} profile(s) found via search engine:")
                for p in serp:
                    parts = [p["title"]]
                    if p.get("company"):   parts.append(p["company"])
                    if p.get("location"):  parts.append(p["location"])
                    if p.get("connections"): parts.append(f"{p['connections']} connections")
                    emit(f"  🔗  {p['url']}")
                    emit(f"       {' · '.join(parts[1:])}" if len(parts) > 1 else "")
                    if p.get("education"):
                        emit(f"       🎓 {p['education']}")
            else:
                emit(f"  ℹ  LinkedIn SERP — no profiles found via search engine")
            if candidates:
                emit(f"  📋  {len(candidates)} URL candidate(s) generated for manual verification")
            report["social_media"]["linkedin"] = li
        except Exception as exc:
            emit(f"  ℹ  LinkedIn unavailable: {exc}")
        emit("")

    # ── Step 0.96: Twitter/X, Snapchat, BeReal, Telegram, Facebook ──
    if "social_media" in active_modules and _ig_candidates:
        _plat_candidates = _validated_usernames[:10] if _validated_usernames else _ig_candidates[:10]
        emit(f"  💭 [Step 0.96] Twitter/X · Snapchat · BeReal · Telegram · Facebook — {len(_plat_candidates)} candidates…")
        try:
            plat_results = await _search_social_platforms_direct(
                _plat_candidates,
                firstname=firstname,
                lastname=lastname,
                keywords=keywords,
            )
            found_summary: list[str] = []
            for pk in ("twitter", "snapchat", "telegram"):
                pr = plat_results.get(pk, {})
                found = pr.get("found", [])
                if found:
                    label = pr.get("label", pk)
                    found_summary.append(f"{label}: {len(found)}")
                    for p in found:
                        dn = f' — "{p["display_name"]}"' if p.get("display_name") else ""
                        emit(f"  ✅  [{label}] @{p['username']}{dn} [{p['relevance']}/10]")

            # BeReal: unverifiable — just show candidates
            br = plat_results.get("bereal", {})
            br_cands = br.get("candidates", [])
            if br_cands:
                emit(f"  ⚠  BeReal — {len(br_cands)} URL(s) candidates (non vérifiables sans auth) :")
                for c in br_cands[:3]:
                    emit(f"  🔗  {c['url']}")

            if found_summary:
                emit(f"  🔍  Trouvé : {', '.join(found_summary)}")
            elif not br_cands:
                emit("  ℹ  Aucun profil trouvé sur Twitter/X, Snapchat, Telegram")

            fb = plat_results.get("facebook", {})
            if fb.get("search_url"):
                emit(f"  🔗  Facebook (recherche manuelle) : {fb['search_url']}")

            # Store — merge avec TikTok/LinkedIn déjà en place
            for pk in ("twitter", "snapchat", "bereal", "telegram", "facebook"):
                if pk in plat_results:
                    report["social_media"].setdefault("platforms", {})[pk] = plat_results[pk]

        except Exception as exc:
            emit(f"  ℹ  Multi-platform search unavailable: {exc}")
        emit("")

    # ── Checkpoint: LLM synthesis + confirmation ─────────────────
    if event_callback:
        event_callback({"type": "progress", "step": "step0_99", "label": "LLM Checkpoint",
                        "phase": 1, "status": "running"})
    _sm   = report.get("social_media", {})
    _mg   = _sm.get("maigret", {})
    _act  = _mg.get("activity_signals", {})

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
            {"username": p["username"], "display_name": p.get("display_name", ""),
             "relevance": p["relevance"], "first_seen": p.get("first_seen")}
            for p in _sm.get("instagram", {}).get("found", [])[:5]
        ],
        "tiktok": [
            {"username": p["username"], "display_name": p.get("display_name", ""),
             "relevance": p["relevance"], "url": p["url"]}
            for p in _sm.get("tiktok", {}).get("found", [])[:5]
        ],
        "linkedin_candidates": [c["url"] for c in _sm.get("linkedin", {}).get("candidates", [])[:5]],
        "maigret": {
            "total_found":       _mg.get("total_found", 0),
            "location_relevant": [{"site": p["site"], "url": p["url"]} for p in _mg.get("location_relevant", [])[:6]],
        },
        "activity_signals": {
            "reddit": {
                "last_active": _act.get("reddit", {}).get("last_active"),
                "subreddits":  _act.get("reddit", {}).get("subreddits", []),
            } if _act.get("reddit") else None,
            "github": {
                "location":   _act.get("github", {}).get("location"),
                "last_active": _act.get("github", {}).get("last_active"),
            } if _act.get("github") else None,
        },
    }

    identity_text  = ""
    timeline_text  = ""
    locations_text = ""

    # ── Fallback: rule-based synthesis (always runs first) ───────
    # Gives the investigator useful evidence even when no LLM or when LLM crashes.
    def _rule_synthesis() -> tuple[str, str, str]:
        _ig   = evidence.get("instagram", [])
        _ph   = evidence.get("phone") or {}
        _mg   = evidence.get("maigret", {})
        _act  = evidence.get("activity_signals", {})
        _dem  = report.get("demographics", {})
        _dip  = report.get("diplomas", {})
        _biz  = report.get("business", {})
        _plat = report.get("social_media", {}).get("platforms", {})

        # IDENTITY
        id_parts: list[str] = []
        if _ig:
            best = _ig[0]
            dn = f' "{best["display_name"]}"' if best.get("display_name") else ""
            id_parts.append(f"Instagram profile found: @{best['username']}{dn} (relevance {best['relevance']}/10).")
        if _ph.get("valid"):
            id_parts.append(
                f"Phone {_ph.get('type','?')} [{_ph.get('carrier','')} — {_ph.get('region','')}]."
                + (f" Found on: {', '.join(_ph.get('social',[]))}." if _ph.get("social") else "")
            )
        if _dip.get("total_theses", 0) or _dip.get("bac_results"):
            bac = _dip.get("bac_results", [])
            thesis = _dip.get("theses", [])
            if bac:
                id_parts.append(f"Bac result found: {bac[0]['name']} ({bac[0].get('year','?')}).")
            if thesis:
                id_parts.append(f"Thesis on theses.fr: {thesis[0]['title'][:60]}.")
        if _biz.get("sirene"):
            s = _biz["sirene"][0]
            id_parts.append(f"Business registry: SIREN {s.get('siren','?')} — {s.get('name','?')} ({s.get('city','?')}).")
        if not id_parts:
            id_parts.append(f"No strong identity signals found in Phase 1 for {firstname} {lastname}.")
        ident = " ".join(id_parts)

        # TIMELINE (most recent first)
        tl_items: list[str] = []
        rd = _act.get("reddit") or {}
        gh = _act.get("github") or {}
        if rd.get("last_active"):
            subs = ", ".join(rd.get("subreddits", [])[:3])
            tl_items.append(f"• {rd['last_active']}: Reddit — last active" + (f" ({subs})" if subs else ""))
        if gh.get("last_active"):
            loc = f" — 📍 {gh['location']}" if gh.get("location") else ""
            tl_items.append(f"• {gh['last_active']}: GitHub{loc}")
        for p in _ig:
            fs = p.get("first_seen", "")
            pfx = f"• {fs}: " if fs else "• "
            dn = f' "{p["display_name"]}"' if p.get("display_name") else ""
            tl_items.append(f"{pfx}Instagram — @{p['username']}{dn}")
        for pk, pd in _plat.items():
            for prof in pd.get("found", [])[:2]:
                tl_items.append(f"• {pd['label']} — @{prof['username']}")
        loc_sites = [p["site"] for p in _mg.get("location_relevant", [])[:4]]
        if loc_sites:
            tl_items.append(f"• Maigret — Location/Sport profiles: {', '.join(loc_sites)}")
        tline = "\n".join(tl_items) if tl_items else "No activity timeline data."

        # LOCATIONS — only real person signals, NOT surname etymology
        locs: list[str] = []
        if _ph.get("region"):
            locs.append(_ph["region"])
        if gh.get("location"):
            locs.append(gh["location"])
        li_serp = report.get("social_media", {}).get("linkedin", {}).get("serp_found", [])
        for li_p in li_serp[:2]:
            if li_p.get("location"):
                locs.append(li_p["location"])
        for ig_p in _ig[:2]:
            if ig_p.get("location"):
                locs.append(ig_p["location"])
        locs_str = ", ".join(dict.fromkeys(locs)) if locs else ""

        return ident, tline, locs_str

    identity_text, timeline_text, locations_text = _rule_synthesis()

    # ── LLM synthesis (enriches rule-based output when available) ─
    if backend and _HAS_LLM:
        _llm_prompt = (
            f"You are an OSINT analyst helping locate a missing person.\n\n"
            f"Target: {firstname} {lastname}"
            + (f"  (born ~{birth_year})" if birth_year else "") + "\n\n"
            f"Passive intelligence gathered so far:\n"
            f"{json.dumps(evidence, indent=2, ensure_ascii=False)}\n\n"
            f"Based on this data, provide three sections:\n"
            f"IDENTITY: 2-3 sentences describing who this person appears to be.\n"
            f"TIMELINE: Chronological last known activities (most recent first). "
            f"Format: '• <date/period>: <platform> — <what was found/location hint>'.\n"
            f"LOCATIONS: Comma-separated cities/regions that appear in the data.\n\n"
            f"Be specific and factual."
        )
        _llm_ok = False
        for _attempt in range(2):   # retry once on cold-start timeout
            try:
                synth = llm_completion(
                    model=backend,
                    messages=[{"role": "user", "content": _llm_prompt}],
                    max_tokens=600,
                    timeout=llm_timeout,
                )
                raw = synth.choices[0].message.content or ""
                parts = re.split(r'\n(?=IDENTITY:|TIMELINE:|LOCATIONS:)', raw.strip())
                llm_id, llm_tl, llm_loc = "", "", ""
                for part in parts:
                    if part.startswith("IDENTITY:"):
                        llm_id = part[9:].strip()
                    elif part.startswith("TIMELINE:"):
                        llm_tl = part[9:].strip()
                    elif part.startswith("LOCATIONS:"):
                        llm_loc = part[10:].strip()
                if llm_id:  identity_text  = llm_id
                if llm_tl:  timeline_text  = llm_tl
                if llm_loc: locations_text = llm_loc
                _emit_tokens(synth)
                _llm_ok = True
                break
            except Exception as exc:
                _exc_str = str(exc).lower()
                _cold_start = (
                    "timed out waiting for llama" in _exc_str
                    or "llama-server" in _exc_str
                    or "connection timed out" in _exc_str   # litellm.Timeout on slow model load
                )
                if _cold_start and _attempt == 0:
                    emit(f"  ⚠  Ollama model loading (timed out) — retrying in 30s…")
                    import time as _t; _t.sleep(30)
                    continue
                emit(f"  ⚠  LLM synthesis unavailable ({type(exc).__name__}) — showing rule-based summary.")

    # Always display the synthesis in the terminal
    emit(f"\n  ┌─ 📋 Checkpoint synthesis {'─'*36}┐")
    emit(f"  │  IDENTITY  : {identity_text[:120]}")
    if locations_text:
        emit(f"  │  LOCATIONS : {locations_text[:120]}")
    for tl in timeline_text.splitlines()[:8]:
        emit(f"  │  {tl}")
    emit(f"  └{'─'*49}┘\n")

    report["timeline"] = {
        "llm_identity":     identity_text,
        "llm_timeline":     timeline_text,
        "llm_locations":    locations_text,
        "activity_signals": evidence["activity_signals"],
    }

    # ── Phase 2: Email OSINT ─────────────────────────────────────
    if "email" not in active_modules:
        emit("  ℹ  Email module disabled — investigation complete.")
        if report_callback:
            report_callback(report)
        return

    # 2.1 — Permutation
    emit(f"  💭 [Step 1/4] Generating email candidates for {firstname} {lastname}…")
    loop = asyncio.get_event_loop()
    candidates = await loop.run_in_executor(
        None, _generate_emails, firstname, lastname, birth_year, keywords
    )

    # ── Extract Instagram obfuscated patterns for candidate scoring ──
    from skills.social_media.ig_lookup import (
        parse_obfuscated_email as _parse_ig_email,
        parse_obfuscated_phone as _parse_ig_phone,
        match_email as _match_ig_email,
        match_phone as _match_ig_phone,
        scan_report_for_emails as _scan_report_emails,
    )
    ig_lookups = report.get("social_media", {}).get("ig_lookups", [])
    ig_email_patterns = [
        _parse_ig_email(lk["obfuscated_email"])
        for lk in ig_lookups
        if lk.get("status") == "found" and lk.get("obfuscated_email")
    ]
    ig_phone_patterns = [
        _parse_ig_phone(lk["obfuscated_phone"])
        for lk in ig_lookups
        if lk.get("status") == "found" and lk.get("obfuscated_phone")
    ]

    if ig_email_patterns:
        for pat in ig_email_patterns:
            resolved = pat.get("resolved_domain")
            hint_str = pat["raw"]
            if resolved:
                hint_str += f" → {resolved}"
            emit(f"  🎯  Instagram email hint: {hint_str}")

        # Cross-data scan: find matching emails already in the report
        cross_hits = _scan_report_emails(report, ig_email_patterns)
        if cross_hits:
            emit(f"  🔗  Cross-data match — found in investigation data:")
            for h in cross_hits:
                emit(f"  ✅    {h['email']}  [{h['source']}]  ({', '.join(h['reasons'])})")
            report["emails"]["ig_cross_match"] = cross_hits

        # Re-rank candidates: resolved domain first, then other matches
        resolved_domains = {p["resolved_domain"] for p in ig_email_patterns if p.get("resolved_domain")}

        def _ig_score(email: str) -> int:
            local, _, domain = email.partition("@")
            for pat in ig_email_patterns:
                ok, _ = _match_ig_email(email, pat)
                if ok:
                    return 0 if domain in resolved_domains else 1
            return 2
        candidates = sorted(candidates, key=_ig_score)
        matched = [c for c in candidates if _ig_score(c) < 2]
        if matched:
            emit(f"  ✅  {len(matched)} candidate(s) match pattern — prioritised: {', '.join(matched[:6])}")

    emit(f"  📦  {len(candidates)} candidates — first: {', '.join(candidates[:5])}")
    emit("")

    # 2.2 — Email validation (Reacher / check-if-email-exists)
    from skills.email.smtp_validate import _check_reacher_available, _MAX_VALIDATE, _MAX_SERP
    reacher_up = _check_reacher_available()
    checked    = min(len(candidates), _MAX_VALIDATE)
    if reacher_up:
        emit(f"  💭 [Step 2/4] Email validation via Reacher — checking {checked}/{len(candidates)} candidates…")
    else:
        emit(f"  💭 [Step 2/4] Email validation (MX-only) — checking {checked}/{len(candidates)} candidates…")
        if len(candidates) > _MAX_VALIDATE:
            emit(f"  ℹ  Capped at {_MAX_VALIDATE} (start Reacher for full SMTP verification)")
    validated    = await loop.run_in_executor(None, _smtp_validate_all, candidates)
    valid_emails = validated.get("valid", [])
    risky_emails = validated.get("risky", [])
    unverifiable = validated.get("unverifiable", [])
    src          = validated.get("source", "?")
    emit(f"  📦  [{src}] {len(valid_emails)} deliverable — {len(risky_emails)} risky — {len(unverifiable)} unknown — {validated.get('invalid_count',0)} invalid")
    # Flag candidates that match Instagram pattern
    if ig_email_patterns:
        ig_matched_emails = [e for e in (valid_emails + risky_emails + unverifiable)
                             if any(_match_ig_email(e, p)[0] for p in ig_email_patterns)]
        if ig_matched_emails:
            emit(f"  🎯  Instagram pattern match in results: {', '.join(ig_matched_emails[:5])}")

    for email in valid_emails:
        det = next((d for d in validated.get("details", []) if d["email"] == email), {})
        flags = []
        if det.get("is_catch_all"):  flags.append("catch-all")
        if det.get("is_disposable"): flags.append("disposable")
        if det.get("is_role"):       flags.append("role")
        if any(_match_ig_email(email, p)[0] for p in ig_email_patterns):
            flags.append("✓ Instagram hint")
        if det.get("serp_hit"):      flags.append(f"indexed on web ({det['serp_count']} results)")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        emit(f"  ✅  {email}{flag_str}")
    for email in risky_emails:
        det = next((d for d in validated.get("details", []) if d["email"] == email), {})
        reason = "catch-all" if det.get("is_catch_all") else ("disposable" if det.get("is_disposable") else "risky")
        extra  = f", indexed ({det['serp_count']} results)" if det.get("serp_hit") else ""
        emit(f"  ⚠  {email}  [{reason}{extra}]")
    # Show SERP-confirmed emails that SMTP couldn't verify
    serp_likely = [
        d for d in validated.get("details", [])
        if d.get("serp_likely") and d["email"] not in valid_emails and d["email"] not in risky_emails
    ]
    for det in serp_likely:
        emit(f"  🌐  {det['email']}  [unverifiable by SMTP — found on web ({det['serp_count']} results)]")
    report["emails"]["smtp_valid"]   = list(valid_emails)
    report["emails"]["risky"]        = list(risky_emails)
    report["emails"]["serp_likely"]  = [d["email"] for d in serp_likely]
    report["emails"]["details"]      = validated.get("details", [])
    report["emails"]["reacher_used"] = reacher_up
    emit("")

    # 2.3 — GHunt (Gmail addresses in smtp_valid + unverifiable)
    gmail_candidates = [e for e in (valid_emails + unverifiable) if e.endswith("@gmail.com") or e.endswith("@googlemail.com")]
    ghunt_results: list[dict] = []
    if gmail_candidates:
        emit(f"  💭 [Step 2b] GHunt — {len(gmail_candidates)} Gmail candidate(s)…")
        for email in gmail_candidates[:5]:  # cap at 5 to avoid long waits
            emit(f"  🔍  ghunt {email}…")
            gh_result = await loop.run_in_executor(None, _ghunt, email)
            ghunt_results.append(gh_result)
            if gh_result.get("found"):
                name = gh_result.get("name") or "(unnamed)"
                emit(f"  ✅  {email} → Google account confirmed — {name}")
                if gh_result.get("maps_reviews"):
                    emit(f"  🗺️   Maps reviews: {gh_result['maps_reviews']}")
                report["emails"]["ghunt_confirmed"].append(email)
            elif gh_result.get("error") == "ghunt_unavailable":
                hint = gh_result.get("hint", "run: ghunt login (one-time browser OAuth)")
                emit(f"  ⚠  GHunt not authenticated — {hint}")
                break  # all emails will fail the same way
            elif gh_result.get("error"):
                emit(f"  ⚠  {email}: {gh_result['error']}")
            else:
                emit(f"  ✗  {email} — account not found")
        report["ghunt_details"] = ghunt_results
        emit("")

    # 2.4 — HIBP breach check
    hibp_targets = valid_emails
    hibp_results: list[dict] = []
    if hibp_targets:
        emit(f"  💭 [Step 3/4] HIBP breach check — {len(hibp_targets)} email(s)…")
        for email in hibp_targets:
            emit(f"  🔍  check_hibp {email}…")
            h = await loop.run_in_executor(None, _hibp, email)
            hibp_results.append(h)
            if h.get("breached"):
                names = [b["name"] for b in h.get("breaches", [])]
                emit(f"  ⚠  {email} → BREACHED ×{h.get('count')} : {', '.join(names)}")
            elif h.get("breached") is False:
                emit(f"  ✓  {email} — not breached")
            else:
                emit(f"  ?  {email} — {h.get('error', '?')}")
        emit("")

    breached = [h["email"] for h in hibp_results if h.get("breached")]
    report["emails"]["breached"] = breached
    report["hibp_details"]        = hibp_results
    report["risk_level"]          = "high" if breached else ("medium" if valid_emails else "none")

    # 2.5 — Specialist agents pre-analysis + LLM synthesis (Phase 3 intelligence)
    # Step A: run deterministic rule-based agents (no LLM, <100ms)
    emit("  💭 [Step 4/4] Running specialist agents…")
    try:
        from skills.core.agents import run_all_agents
        pre_analysis = run_all_agents(report)
        report["pre_analysis"] = pre_analysis
        id_a  = pre_analysis.get("identity", {})
        soc_a = pre_analysis.get("social", {})
        geo_a = pre_analysis.get("geolocation", {})
        tl_a  = pre_analysis.get("timeline", {})
        cor_a = pre_analysis.get("correlations", {})
        emit(f"  🔎  Identity agent  — confirmed: {len(id_a.get('confirmed',[]))}  "
             f"probable: {len(id_a.get('probable',[]))}  rejected: {len(id_a.get('rejected',[]))}")
        emit(f"  🌐  Social agent    — {soc_a.get('maigret_total',0)} platforms  "
             f"active: {len(soc_a.get('active_platforms',[]))}")
        emit(f"  📍  Geo agent       — {geo_a.get('confidence','?')}  "
             f"estimate: {geo_a.get('current_estimate','?')[:50]}")
        emit(f"  📅  Timeline agent  — {tl_a.get('event_count',0)} events  "
             f"span: {tl_a.get('span_years','?')}")
        emit(f"  🔗  Correlation agent — {len(cor_a.get('correlations',[]))} link(s)  "
             f"{len(cor_a.get('anomalies',[]))} anomaly(-ies)")
    except Exception as exc:
        pre_analysis = {}
        emit(f"  ⚠  Agent pre-analysis failed: {exc}")

    # Step B: LLM synthesis using agent briefings
    if backend and _HAS_LLM and (valid_emails or breached or report.get("social_media")):
        emit("  💭        Synthesising intelligence report…")
        try:
            from skills.core.evidence import build_context_summary
            ctx_data = build_context_summary(report)
        except Exception:
            ctx_data = {"target": report["target"]}

        _schema = (
            '{\n'
            '  "executive_summary": "3-5 factual sentences — who, where, key findings, confidence level",\n'
            '  "global_confidence": 0.75,\n'
            '  "identity": {\n'
            '    "confirmed": ["fact with source"],\n'
            '    "probable":  ["likely fact"],\n'
            '    "rejected":  ["rejected assumption"]\n'
            '  },\n'
            '  "digital_presence": {\n'
            '    "active_platforms":   [{"platform": "Instagram", "username": "x", "note": "..."}],\n'
            '    "inactive_platforms": [],\n'
            '    "username_pattern":   "description of username style",\n'
            '    "behavioral_notes":   ["observation 1"]\n'
            '  },\n'
            '  "geolocation": {\n'
            '    "confirmed": ["City/region with source"],\n'
            '    "probable":  ["likely location"],\n'
            '    "current_estimate": "Most likely current location"\n'
            '  },\n'
            '  "relational_network": {\n'
            '    "contacts":   [],\n'
            '    "associated_accounts": [],\n'
            '    "platforms_with_followers": []\n'
            '  },\n'
            '  "risk_indicators": ["indicator 1", "indicator 2"],\n'
            '  "hypotheses": [\n'
            '    {\n'
            '      "claim": "Specific, testable hypothesis",\n'
            '      "confidence": 0.85,\n'
            '      "level": "confirmed|probable|low",\n'
            '      "supporting": ["evidence 1", "evidence 2"],\n'
            '      "against": ["counter-evidence"]\n'
            '    }\n'
            '  ],\n'
            '  "timeline": [\n'
            '    {"date": "2024-03", "event": "Description", "confidence": "confirmed", "source": "GitHub"}\n'
            '  ],\n'
            '  "pivot_suggestions": [\n'
            '    {"action": "Specific next step", "priority": "high|medium|low", "rationale": "Why useful"}\n'
            '  ],\n'
            '  "human_verifications": [\n'
            '    "Manually verify: LinkedIn profile at URL X"\n'
            '  ],\n'
            '  "missing_data": ["What data would improve confidence"]\n'
            '}'
        )

        _analysis_prompt = (
            f"You are the synthesis agent in an OSINT investigation team.\n"
            f"Five specialist agents have analysed different domains for target {firstname} {lastname}.\n"
            f"Your role: integrate their findings into a comprehensive intelligence assessment.\n\n"
            f"IDENTITY AGENT BRIEFING:\n{json.dumps(pre_analysis.get('identity',{}), ensure_ascii=False)}\n\n"
            f"SOCIAL MEDIA AGENT BRIEFING:\n{json.dumps(pre_analysis.get('social',{}), ensure_ascii=False)}\n\n"
            f"GEOLOCATION AGENT BRIEFING:\n{json.dumps(pre_analysis.get('geolocation',{}), ensure_ascii=False)}\n\n"
            f"TIMELINE AGENT BRIEFING:\n{json.dumps(pre_analysis.get('timeline',{}), ensure_ascii=False)}\n\n"
            f"CORRELATION AGENT BRIEFING:\n{json.dumps(pre_analysis.get('correlations',{}), ensure_ascii=False)}\n\n"
            f"RAW INVESTIGATION CONTEXT:\n{json.dumps(ctx_data, ensure_ascii=False)}\n\n"
            f"CRITICAL RULES:\n"
            f"- CONFIRMED = multiple independent sources agree. PROBABLE = one strong source. LOW = weak signal.\n"
            f"- NEVER present a hypothesis as a confirmed fact.\n"
            f"- Every claim must cite its source.\n"
            f"- Hypotheses must be specific and falsifiable.\n"
            f"- Pivots must be actionable and specific.\n"
            f"- global_confidence is a float 0.0–1.0 representing overall identity certainty.\n\n"
            f"Respond ONLY with valid JSON matching this exact schema (no markdown, no extra text):\n{_schema}"
        )

        for _fattempt in range(2):
            try:
                final_resp = llm_completion(
                    model=backend,
                    messages=[{"role": "user", "content": _analysis_prompt}],
                    max_tokens=1600,
                    timeout=llm_timeout,
                )
                raw_analysis = final_resp.choices[0].message.content or ""
                _emit_tokens(final_resp)

                _json_str = re.sub(r'^```(?:json)?\s*', '', raw_analysis.strip())
                _json_str = re.sub(r'\s*```$', '', _json_str.strip())
                try:
                    analysis = json.loads(_json_str)
                    report["analysis"] = analysis
                    report["llm_summary"] = analysis.get("executive_summary", raw_analysis)
                    h_count = len(analysis.get("hypotheses", []))
                    p_count = len(analysis.get("pivot_suggestions", []))
                    hv_count = len(analysis.get("human_verifications", []))
                    gc = analysis.get("global_confidence", 0)
                    emit(f"  ✓  Intelligence report: confidence {gc:.0%} — "
                         f"{h_count} hypothesis(-es) — {p_count} pivot(s) — {hv_count} human check(s)")
                    if analysis.get("hypotheses"):
                        for hyp in analysis["hypotheses"][:3]:
                            lvl = hyp.get("level", "?")
                            cf  = hyp.get("confidence", 0)
                            emit(f"  {'✅' if lvl=='confirmed' else '🟡' if lvl=='probable' else '⚪'}  "
                                 f"[{lvl} {cf:.0%}] {hyp.get('claim','')[:90]}")
                    if analysis.get("geolocation", {}).get("current_estimate"):
                        emit(f"  📍  Location estimate: {analysis['geolocation']['current_estimate'][:80]}")
                    if analysis.get("pivot_suggestions"):
                        emit("  🔭  Top pivots:")
                        for pv in analysis["pivot_suggestions"][:3]:
                            emit(f"  {'🔴' if pv.get('priority')=='high' else '🟠' if pv.get('priority')=='medium' else '🟢'}  "
                                 f"{pv.get('action','')[:90]}")
                except json.JSONDecodeError:
                    report["llm_summary"] = raw_analysis
                    report["analysis"]    = {}
                    emit(f"  ✓  LLM summary generated ({len(raw_analysis)} chars, JSON parse failed — "
                         f"try a model with better JSON instruction-following)")
                break
            except Exception as exc:
                _exc_str = str(exc).lower()
                _is_timeout = (
                    "timed out waiting for llama" in _exc_str
                    or "llama-server" in _exc_str
                    or "connection timed out" in _exc_str
                )
                if _is_timeout and _fattempt == 0:
                    emit("  ⚠  Ollama model loading — retrying synthesis in 30s…")
                    import time as _t2; _t2.sleep(30)
                    continue
                emit(f"  ⚠  Final synthesis failed: {exc}")
                break
    else:
        # No LLM — build analysis from rule-based agents only
        tl_evts = pre_analysis.get("timeline", {}).get("events", [])
        report["analysis"] = {
            "executive_summary": report.get("timeline", {}).get("llm_identity", ""),
            "global_confidence": pre_analysis.get("identity", {}).get("confidence_score", 0.0),
            "hypotheses": [],
            "pivot_suggestions": [],
            "timeline": tl_evts[:10],
            "geolocation": {
                "confirmed": [{"location": l["location"], "source": l["source"]}
                              for l in pre_analysis.get("geolocation", {}).get("confirmed_locations", [])],
                "probable": [{"location": l["location"], "source": l["source"]}
                             for l in pre_analysis.get("geolocation", {}).get("probable_locations", [])],
                "current_estimate": pre_analysis.get("geolocation", {}).get("current_estimate", ""),
            },
        }
    emit("")

    emit(f"{'─' * 54}")
    emit("  ✓  Investigation complete.")
    emit(f"{'─' * 54}\n")

    if report_callback:
        report_callback(report)
