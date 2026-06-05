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
    _search_diplomas_direct,
    _search_phone_direct,
    _search_instagram_direct,
    _search_social_platforms_direct,
    _run_maigret_direct,
    _enrich_activity_signals,
    _search_sirene_pappers_direct,
    _diploma_relevance,
)

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

    city_extras  = _cities_to_keywords(cities or [])
    all_keywords = list(keywords)
    for k in city_extras:
        if k not in all_keywords:
            all_keywords.append(k)

    if city_extras:
        emit(f"  🏙️  Cities → extra keywords: {', '.join(city_extras)}")

    active_modules = list(modules) if modules else ["demographics", "diplomas", "email", "phone", "social_media"]
    report = _blank_report(firstname, lastname, birth_year, all_keywords, cities or [])

    emit(f"{'━' * 54}")
    emit(f"  PEEK-A-WHO  [direct pipeline — no MCP subprocess]")
    emit(f"{'━' * 54}")
    emit("")

    # ── Step 0: Etymology (filae.com) ──────────────────────────
    if "demographics" in active_modules and lastname:
        emit(f"  💭 [Step 0] Surname demographics — {lastname}…")
        try:
            loop = asyncio.get_event_loop()
            ety = await loop.run_in_executor(None, _etymology, lastname, birth_year)
            if ety.get("bearers_since_1890"):
                emit(f"  👥  {ety['bearers_since_1890']} bearers since 1890 — {ety.get('departments_count','?')} dept(s) — rank: {ety.get('national_rank','?')}")
            if ety.get("birth_year_context"):
                emit(f"  📅  Birth year {birth_year}: {ety['birth_year_context']}")
            dist = ety.get("geographic_distribution", [])
            if dist:
                top = ", ".join(f"{d['department']} ({d['count']})" for d in dist[:5])
                emit(f"  🗺️   Top departments: {top}")
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
                    emit(f"  📜  {b['name']} — {b.get('diploma','?')} ({b['year']}, âge {b['age_at_bac']})")
            elif birth_yr_int:
                emit(f"  ℹ  No bac result (years {birth_yr_int+17}–{birth_yr_int+20})")
            if brevet:
                emit(f"  🎓  {len(brevet)} brevet result(s):")
                for b in brevet:
                    emit(f"  📜  {b['name']} (brevet {b['year']}, âge {b['age_at_brevet']})")

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
        emit("  🔗 [Step 0.8] Annuaires (Cloudflare-protected — open manually):")
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
                    found   = [p["site"] for p in platforms if p["status"] == "found"]
                    limited = [p["site"] for p in platforms if p["status"] == "rate_limited"]
                    emit(f"  🔍  ignorant — {len(platforms)} platforms:")
                    if found:   emit(f"  ✅    Registered on: {', '.join(found)}")
                    if limited: emit(f"  ⚠    Rate-limited: {', '.join(limited)}")
            report["phone"] = ph
        except Exception as exc:
            emit(f"  ℹ  Phone OSINT unavailable: {exc}")
        emit("")

    # ── Step 0.95: Instagram ─────────────────────────────────────
    if "social_media" in active_modules and (firstname or lastname):
        emit("  💭 [Step 0.95] Instagram username search…")
        try:
            dept_codes = [k for k in city_extras if re.match(r"^\d{2}$", k)]
            ig_usernames = _generate_ig_usernames(
                firstname, lastname, birth_year,
                keywords=all_keywords, pseudo=pseudo, dept_codes=dept_codes,
            )
            emit(f"  📱  {len(ig_usernames)} candidates — first: {', '.join(ig_usernames[:5])}")
            ig = await _search_instagram_direct(ig_usernames, firstname, lastname, keywords=all_keywords)
            found = ig.get("found", [])
            emit(f"  🔍  Checked {ig['checked']}/{ig['generated']} — {len(found)} profile(s) found")
            for p in found[:5]:
                dn       = f' — "{p["display_name"]}"' if p.get("display_name") else ""
                age_note = f" (first seen {p['first_seen']})" if p.get("first_seen") else ""
                emit(f"  ✅  @{p['username']}{dn}{age_note} [{p['relevance']}/10]")
            if not found:
                emit("  ℹ  No Instagram profiles found")
            report["social_media"] = {"instagram": ig}
        except Exception as exc:
            emit(f"  ℹ  Instagram search unavailable: {exc}")
        emit("")

    # ── Step 0.96: Multi-platform ────────────────────────────────
    if "social_media" in active_modules and (pseudo or firstname or lastname or all_keywords):
        dept_codes_sm = [k for k in city_extras if re.match(r"^\d{2}$", k)]
        sm_usernames  = _generate_ig_usernames(
            firstname, lastname, birth_year,
            keywords=all_keywords, pseudo=pseudo, dept_codes=dept_codes_sm,
        )
        emit("  💭 [Step 0.96] Multi-platform (Twitter/X, TikTok, Snapchat, BeReal, LinkedIn)…")
        try:
            plat = await _search_social_platforms_direct(
                sm_usernames[:10], firstname, lastname, keywords=all_keywords,
            )
            total_plat = sum(len(v.get("found", [])) for v in plat.values() if isinstance(v, dict))
            emit(f"  🌐  {total_plat} profile(s) found")
            for pk, pd in plat.items():
                fnd = pd.get("found", [])
                if fnd:
                    for prof in fnd[:5]:
                        dn = f' — "{prof["display_name"]}"' if prof.get("display_name") else ""
                        emit(f"  ✅  {pd['label']}: @{prof['username']}{dn} [{prof['relevance']}/10]")
                elif pk == "facebook" and pd.get("search_url"):
                    emit(f"  🔗  Facebook: {pd['search_url']}")
            report["social_media"]["platforms"] = plat
        except Exception as exc:
            emit(f"  ℹ  Multi-platform search unavailable: {exc}")
        emit("")

    # ── Step 0.97: Maigret ───────────────────────────────────────
    if "social_media" in active_modules and (pseudo or firstname or lastname or all_keywords):
        maigret_names: list[str] = []
        if pseudo:
            p_clean = re.sub(r"[^a-z0-9._]", "", pseudo.lower().translate(_ACCENT_MAP))
            if p_clean:
                maigret_names.append(p_clean)
        for kw in (keywords or []):
            kw_c = re.sub(r"[^a-z0-9._-]", "", kw.lower().translate(_ACCENT_MAP))
            if kw_c and len(kw_c) > 2 and kw_c not in maigret_names:
                maigret_names.append(kw_c)
        for n in _generate_ig_usernames(firstname, lastname, birth_year, pseudo=pseudo)[:5]:
            if n not in maigret_names:
                maigret_names.append(n)
        maigret_names = maigret_names[:5]

        emit(f"  💭 [Step 0.97] Cross-platform (maigret) — {', '.join(maigret_names)}…")
        try:
            mg = await _run_maigret_direct(maigret_names)
            if mg.get("not_installed"):
                emit("  ℹ  maigret not installed (pip install maigret)")
            else:
                emit(f"  🌐  {mg.get('total_found', 0)} profile(s) found")
                if mg.get("location_relevant"):
                    emit(f"  📍  Location/Sport: {', '.join(p['site'] for p in mg['location_relevant'][:6])}")
                if mg.get("total_found", 0) > 0:
                    act = await _enrich_activity_signals(mg)
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
                    mg["activity_signals"] = act
                report.setdefault("social_media", {})["maigret"] = mg
        except Exception as exc:
            emit(f"  ℹ  Cross-platform search unavailable: {exc}")
        emit("")

    # ── Checkpoint: LLM synthesis + confirmation ─────────────────
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

    if backend and _HAS_LLM:
        try:
            synth = llm_completion(
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
                        f"TIMELINE: Chronological last known activities (most recent first). "
                        f"Format: '• <date/period>: <platform> — <what was found/location hint>'.\n"
                        f"LOCATIONS: Comma-separated cities/regions that appear in the data.\n\n"
                        f"Be specific and factual."
                    ),
                }],
                max_tokens=600,
                timeout=90,
            )
            raw = synth.choices[0].message.content or ""
            parts = re.split(r'\n(?=IDENTITY:|TIMELINE:|LOCATIONS:)', raw.strip())
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
                for tl in timeline_text.splitlines()[:6]:
                    emit(f"  │  {tl}")
                emit(f"  └{'─'*49}┘\n")
        except Exception as exc:
            emit(f"  ⚠  LLM synthesis failed: {exc}")

    report["timeline"] = {
        "llm_identity":     identity_text,
        "llm_timeline":     timeline_text,
        "llm_locations":    locations_text,
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

    if "email" in active_modules and confirmation_wait is not None and (firstname or lastname):
        emit("  ⏸  Waiting for user confirmation before deep OSINT…")
        action = confirmation_wait()
        if action != "continue":
            emit("  ⛔  Investigation stopped by user.")
            if report_callback:
                report_callback(report)
            return
        emit("  ✓  User confirmed — continuing with deep OSINT…")
        emit("")

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
        None, _generate_emails, firstname, lastname, birth_year, all_keywords
    )
    emit(f"  📦  {len(candidates)} candidates — first: {', '.join(candidates[:5])}")
    emit("")

    # 2.2 — SMTP validation
    emit(f"  💭 [Step 2/4] SMTP validation — {len(candidates)} candidates…")
    validated = await loop.run_in_executor(None, _smtp_validate_all, candidates)
    valid_emails    = validated.get("valid", [])
    unverifiable    = validated.get("unverifiable", [])
    emit(f"  📦  {len(valid_emails)} valid — {len(unverifiable)} unverifiable (big providers)")
    for email in valid_emails:
        emit(f"  ✓  {email}")
    report["emails"]["smtp_valid"] = list(valid_emails)
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

    # 2.5 — Final LLM summary
    if backend and _HAS_LLM and (valid_emails or breached or report.get("social_media")):
        emit("  💭 [Step 4/4] Generating final LLM report…")
        try:
            final_data = {
                "target":       report["target"],
                "demographics": report.get("demographics", {}),
                "phone":        report.get("phone", {}),
                "social_media": {
                    "instagram_found": [p["username"] for p in report["social_media"].get("instagram", {}).get("found", [])],
                    "maigret_total":   report["social_media"].get("maigret", {}).get("total_found", 0),
                },
                "emails":       {"smtp_valid": valid_emails},
                "breaches":     [{"email": h["email"], "count": h["count"]} for h in hibp_results if h.get("breached")],
                "timeline":     report.get("timeline", {}),
            }
            final_resp = llm_completion(
                model=backend,
                messages=[{
                    "role": "user",
                    "content": (
                        f"You are an OSINT analyst. Summarise the following investigation findings "
                        f"for {firstname} {lastname} in 3-5 paragraphs. "
                        f"Focus on: who this person is, where they might be, how to reach them, "
                        f"and what actions are recommended. "
                        f"Be factual, concise, and reference specific data points.\n\n"
                        f"{json.dumps(final_data, indent=2, ensure_ascii=False)}"
                    ),
                }],
                max_tokens=800,
                timeout=120,
            )
            report["llm_summary"] = final_resp.choices[0].message.content or ""
            emit(f"  ✓  LLM summary generated ({len(report['llm_summary'])} chars)")
        except Exception as exc:
            emit(f"  ⚠  Final LLM summary failed: {exc}")
        emit("")

    emit(f"{'─' * 54}")
    emit("  ✓  Investigation complete.")
    emit(f"{'─' * 54}\n")

    if report_callback:
        report_callback(report)
