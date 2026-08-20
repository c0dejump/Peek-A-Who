"""
Rule-based specialist agents — no LLM, pure deterministic logic.

Each agent analyses a specific domain of the investigation report and returns a
structured pre-analysis dict.  These are fed into the LLM synthesis prompt so
the model receives "specialist briefings" instead of raw data dumps.

Pattern: each agent runs fast (pure Python), enriches the context, and the
synthesis LLM reasons across all of them.

Usage:
    from skills.core.agents import run_all_agents
    pre = run_all_agents(report)
    # pass pre to build_context_summary or directly into the LLM prompt
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone


# ── helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _domain_of(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""

def _year_range(birth_year_str: str) -> tuple[int, int] | None:
    m = re.match(r"(\d{4})", str(birth_year_str or ""))
    if not m:
        return None
    y = int(m.group(1))
    return (y - 2, y + 2)

def _extract_locations(report: dict) -> list[tuple[str, str, str]]:
    """Return list of (location, source, confidence_level)."""
    locs: list[tuple[str, str, str]] = []
    ph = report.get("phone", {})
    if ph.get("region"):
        locs.append((ph["region"], "phone carrier", "probable"))
    sm   = report.get("social_media", {})
    for ig in sm.get("instagram", {}).get("found", [])[:3]:
        if ig.get("location"):
            locs.append((ig["location"], f"Instagram @{ig['username']}", "probable"))
    mg  = sm.get("maigret", {})
    act = mg.get("activity_signals", {})
    gh  = act.get("github", {})
    if gh.get("location"):
        locs.append((gh["location"], "GitHub profile", "probable"))
    stg = act.get("steam", {})
    if stg.get("country"):
        locs.append((stg["country"], "Steam profile", "low"))
    for li in sm.get("linkedin", {}).get("serp_found", [])[:2]:
        if li.get("location"):
            locs.append((li["location"], f"LinkedIn — {li.get('title','')}", "probable"))
    # Multiple concordant sources → upgrade to confirmed
    from collections import Counter
    loc_counts = Counter(l.lower().strip() for l, _, _ in locs)
    result: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for (loc, src, lvl) in locs:
        key = loc.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        effective = "confirmed" if loc_counts[key] >= 2 else lvl
        result.append((loc, src, effective))
    return result


# ── Agent 1: Identity ─────────────────────────────────────────────────────────

def run_identity_agent(report: dict) -> dict:
    """
    Analyse identity signals: name, education, business, demographics, email.
    Returns confirmed / probable / rejected buckets + confidence score.
    """
    target  = report.get("target", {})
    fn      = target.get("firstname", "")
    ln      = target.get("lastname", "")
    by      = target.get("birth_year", "")
    dip     = report.get("diplomas", {})
    biz     = report.get("business", {})
    dem     = report.get("demographics", {})
    em      = report.get("emails", {})
    sm      = report.get("social_media", {})

    confirmed: list[str] = []
    probable:  list[str] = []
    rejected:  list[str] = []

    # Analyst-provided pseudo confirmed on real sites → strongest identity anchor
    for _un, _sites in (sm.get("maigret", {}).get("pseudo_confirmed") or {}).items():
        confirmed.append(f"User-provided pseudo @{_un} confirmed on: {', '.join(_sites)}")

    # Name web search → LinkedIn employer/school/location (strong identity data)
    _ns = report.get("name_search") or {}
    if _ns.get("employer"):  confirmed.append(f"Employer (LinkedIn): {_ns['employer']}")
    if _ns.get("education"): confirmed.append(f"Education (LinkedIn): {_ns['education']}")
    if _ns.get("location"):
        _mc = " — matches a given city" if _ns.get("matched_city") else ""
        confirmed.append(f"Location (LinkedIn): {_ns['location']}{_mc}")
    for _p in _ns.get("profiles", [])[:5]:
        probable.append(f"Profile page: {_p['domain']} — {_p['url']}")

    # Depth-first pivot on the confirmed handle (web + GitHub) → real identity data
    _piv = sm.get("maigret", {}).get("pseudo_pivot") or {}
    _pid = _piv.get("identity", {})
    if _pid.get("name"):    confirmed.append(f"Real name via GitHub: {_pid['name']}")
    if _pid.get("location"): confirmed.append(f"Location via GitHub profile: {_pid['location']}")
    if _pid.get("twitter"): confirmed.append(f"Linked Twitter/X (from GitHub): @{_pid['twitter']}")
    for _h, _hd in _piv.get("handles", {}).items():
        doms = [w["domain"] for w in _hd.get("web", [])]
        if doms:
            probable.append(f"@{_h} profile pages: {', '.join(dict.fromkeys(doms))}")

    # Name confirmed if appears in multiple data sources
    name_sources: list[str] = []
    if dip.get("bac_results"):
        for b in dip["bac_results"][:2]:
            n = b.get("name", "")
            if fn.lower() in n.lower() or ln.lower() in n.lower():
                name_sources.append(f"bac record ({b['name']})")
    if dip.get("theses"):
        for t in dip["theses"][:2]:
            n = t.get("author", "") or t.get("title", "")
            if fn.lower() in n.lower() or ln.lower() in n.lower():
                name_sources.append(f"thesis record ({t.get('title','')[:40]})")
    for ig in sm.get("instagram", {}).get("found", [])[:2]:
        dn = ig.get("display_name", "")
        if fn.lower() in dn.lower() or ln.lower() in dn.lower():
            name_sources.append(f"Instagram display name ({dn})")
    for li in sm.get("linkedin", {}).get("serp_found", [])[:2]:
        title = li.get("title", "")
        if fn.lower() in title.lower() or ln.lower() in title.lower():
            name_sources.append(f"LinkedIn ({title})")
    for b in biz.get("sirene", [])[:2] + biz.get("pappers", [])[:2]:
        nm = b.get("name", "")
        if ln.lower() in nm.lower():
            name_sources.append(f"business registry ({nm})")

    if len(name_sources) >= 2:
        confirmed.append(f"Identity {fn} {ln} confirmed in: {'; '.join(name_sources[:3])}")
    elif name_sources:
        probable.append(f"Identity {fn} {ln} found in: {name_sources[0]}")

    # Birth year
    if by and dip.get("bac_results"):
        for b in dip["bac_results"]:
            bac_yr = b.get("year")
            if bac_yr:
                yr_range = _year_range(by)
                est_birth = int(bac_yr) - 18
                if yr_range and yr_range[0] <= est_birth <= yr_range[1]:
                    confirmed.append(f"Birth year ~{by} consistent with BAC in {bac_yr} (est. born {est_birth})")
                elif yr_range:
                    rejected.append(f"Birth year {by} inconsistent with BAC {bac_yr} (est. born {est_birth})")
                break

    # Education
    for t in dip.get("theses", [])[:2]:
        confirmed.append(f"Academic record: thesis '{t.get('title','?')[:50]}' — {t.get('institution','?')} ({t.get('year','?')})")
    for b in dip.get("bac_results", [])[:2]:
        confirmed.append(f"BAC result: {b.get('name','?')} ({b.get('year','?')})")

    # Business
    for b in biz.get("sirene", [])[:2]:
        txt = f"Business: SIREN {b.get('siren','?')} — {b.get('name','?')} ({b.get('city','?')})"
        probable.append(txt)
    for b in biz.get("pappers", [])[:2]:
        txt = f"Corporate: {b.get('name','?')} — role: {b.get('role','?')} ({b.get('city','?')})"
        probable.append(txt)

    # Email identifiers
    valid_em = em.get("smtp_valid", [])
    if valid_em:
        confirmed.append(f"Verified email(s): {', '.join(valid_em[:3])}")
    if em.get("breached"):
        confirmed.append(f"Email(s) found in data breaches: {', '.join(em['breached'][:3])}")

    # Confidence score: ratio of confirmed vs total claims
    total = len(confirmed) + len(probable) + len(rejected)
    if total == 0:
        score = 0.0
    else:
        score = round((len(confirmed) * 1.0 + len(probable) * 0.6) / max(total, 3), 2)
        score = min(score, 1.0)

    return {
        "agent":     "identity",
        "run_at":    _now_iso(),
        "confirmed": confirmed,
        "probable":  probable,
        "rejected":  rejected,
        "confidence_score": score,
        "name_sources":     name_sources,
        "birth_year_verified": any("Birth year" in c and "consistent" in c for c in confirmed),
    }


# ── Agent 2: Digital Presence ─────────────────────────────────────────────────

def run_social_agent(report: dict) -> dict:
    """
    Analyse digital presence: platforms found, activity signals, username patterns.
    """
    sm     = report.get("social_media", {})
    mg     = sm.get("maigret", {})
    act    = mg.get("activity_signals", {})
    plat   = sm.get("platforms", {})

    active_platforms: list[dict] = []
    inactive_platforms: list[dict] = []
    username_variants: list[str] = []

    # Analyst-provided pseudo confirmed on real sites → active by definition
    for _un, _sites in (mg.get("pseudo_confirmed") or {}).items():
        for _site in _sites:
            active_platforms.append({"platform": _site, "username": _un,
                                     "relevance": 10, "source": "user_pseudo"})
        username_variants.append(_un)

    # Instagram
    for ig in sm.get("instagram", {}).get("found", [])[:5]:
        entry = {
            "platform": "Instagram",
            "username": ig.get("username", ""),
            "display_name": ig.get("display_name", ""),
            "relevance": ig.get("relevance", 0),
            "bio": ig.get("bio", "")[:100],
            "followers": ig.get("followers"),
            "is_private": ig.get("is_private", False),
        }
        (active_platforms if ig.get("relevance", 0) >= 7 else inactive_platforms).append(entry)
        if ig.get("username"):
            username_variants.append(ig["username"])

    # TikTok
    for tt in sm.get("tiktok", {}).get("found", [])[:3]:
        entry = {"platform": "TikTok", "username": tt.get("username",""),
                 "relevance": tt.get("relevance", 0)}
        (active_platforms if tt.get("relevance", 0) >= 7 else inactive_platforms).append(entry)
        if tt.get("username"):
            username_variants.append(tt["username"])

    # Multi-platform
    for pk, pv in plat.items():
        for prof in pv.get("found", [])[:2]:
            entry = {"platform": pk.capitalize(), "username": prof.get("username",""),
                     "url": prof.get("url",""), "relevance": prof.get("relevance", 0)}
            (active_platforms if prof.get("relevance", 0) >= 7 else inactive_platforms).append(entry)
            if prof.get("username"):
                username_variants.append(prof["username"])

    # LinkedIn SERP
    for li in sm.get("linkedin", {}).get("serp_found", [])[:2]:
        active_platforms.append({"platform": "LinkedIn", "title": li.get("title",""),
                                  "url": li.get("url",""), "company": li.get("company","")})

    # Maigret categories
    maigret_summary: dict[str, int] = {}
    for cat in ("social", "location_relevant", "marketplace", "gaming", "dating", "forums"):
        items = mg.get(cat, [])
        if items:
            maigret_summary[cat] = len(items)

    # Activity signals
    activity: list[str] = []
    rd = act.get("reddit", {})
    gh = act.get("github", {})
    if rd.get("last_active"):
        subs = ", ".join(rd.get("subreddits", [])[:3])
        activity.append(f"Reddit @{rd.get('username','?')} — last active {rd['last_active']}"
                        + (f" ({subs})" if subs else ""))
    if gh.get("last_active"):
        loc = f" — location: {gh['location']}" if gh.get("location") else ""
        activity.append(f"GitHub @{gh.get('username','?')} — last activity {gh['last_active']}{loc}")
    st = act.get("steam", {})
    if st.get("last_active") or st.get("status_message"):
        when = st.get("last_active") or st.get("status_message")
        ctry = f" — location: {st['country']}" if st.get("country") else ""
        activity.append(f"Steam @{st.get('username','?')} — last online {when}{ctry}")

    # Username pattern analysis
    username_pattern = _analyse_username_pattern(username_variants)

    return {
        "agent":              "social_media",
        "run_at":             _now_iso(),
        "active_platforms":   active_platforms,
        "inactive_platforms": inactive_platforms,
        "maigret_summary":    maigret_summary,
        "maigret_total":      mg.get("total_found", 0),
        "activity_signals":   activity,
        "username_variants":  list(dict.fromkeys(username_variants)),
        "username_pattern":   username_pattern,
    }


def _analyse_username_pattern(variants: list[str]) -> str:
    """Infer the most likely username construction pattern."""
    if not variants:
        return ""
    clean = [v.lower() for v in variants]
    # Check for common separators
    with_dot   = [v for v in clean if "." in v]
    with_under = [v for v in clean if "_" in v]
    with_dash  = [v for v in clean if "-" in v]
    note = f"{len(variants)} username variant(s)"
    if with_dot:
        note += f"; dot-separated ({', '.join(with_dot[:2])})"
    if with_under:
        note += f"; underscore ({', '.join(with_under[:2])})"
    if with_dash:
        note += f"; dash ({', '.join(with_dash[:2])})"
    return note


# ── Agent 3: Geolocation ──────────────────────────────────────────────────────

def run_geo_agent(report: dict) -> dict:
    """
    Extract and correlate location signals across all sources.
    """
    locs = _extract_locations(report)
    sm   = report.get("social_media", {})
    ph   = report.get("phone", {})

    confirmed_locs = [(l, s) for l, s, c in locs if c == "confirmed"]
    probable_locs  = [(l, s) for l, s, c in locs if c == "probable"]

    # Look for location evolution (multiple different locations)
    all_loc_names = [l for l, _, _ in locs]
    evolution: list[str] = []
    if len(set(l.lower() for l in all_loc_names)) > 1:
        evolution = [f"Multiple locations detected: {', '.join(dict.fromkeys(all_loc_names)[:4])}"]

    # Cross-reference: does the phone region match social media locations?
    phone_region = ph.get("region", "")
    social_regions = [l for l, s, _ in locs if "Instagram" in s or "GitHub" in s or "LinkedIn" in s]
    cross_confirmed: list[str] = []
    if phone_region and social_regions:
        for sr in social_regions:
            if phone_region.lower() in sr.lower() or sr.lower() in phone_region.lower():
                cross_confirmed.append(f"Phone region ({phone_region}) matches {sr}")

    # Current location estimate
    current_estimate = ""
    if confirmed_locs:
        current_estimate = confirmed_locs[0][0]
    elif probable_locs:
        current_estimate = probable_locs[0][0]

    return {
        "agent":              "geolocation",
        "run_at":             _now_iso(),
        "confirmed_locations": [{"location": l, "source": s} for l, s in confirmed_locs],
        "probable_locations":  [{"location": l, "source": s} for l, s in probable_locs],
        "location_evolution":  evolution,
        "cross_confirmed":     cross_confirmed,
        "current_estimate":    current_estimate,
        "confidence":          "confirmed" if confirmed_locs else ("probable" if probable_locs else "unknown"),
    }


# ── Agent 4: Timeline ─────────────────────────────────────────────────────────

def run_timeline_agent(report: dict) -> dict:
    """
    Build a chronological activity timeline with confidence levels.
    """
    events: list[dict] = []

    def _add(date: str, event: str, source: str, confidence: str = "probable",
             location: str = "") -> None:
        if date:
            events.append({"date": date, "event": event, "source": source,
                           "confidence": confidence, "location": location or ""})

    tgt = report.get("target", {})
    if tgt.get("birth_year"):
        _add(str(tgt["birth_year"]), "Birth year (approx.)", "investigation input", "probable")

    dip = report.get("diplomas", {})
    for b in dip.get("bac_results", [])[:3]:
        if b.get("year"):
            _add(str(b["year"]), f"BAC — {b.get('name','?')}", "French education records", "confirmed")
    for b in dip.get("brevet_results", [])[:2]:
        if b.get("year"):
            _add(str(b["year"]), f"Brevet — {b.get('name','?')}", "French education records", "confirmed")
    for t in dip.get("theses", [])[:2]:
        if t.get("year"):
            _add(str(t["year"]), f"Thesis: {t.get('title','?')[:50]}", "theses.fr", "confirmed")

    biz = report.get("business", {})
    for b in biz.get("sirene", [])[:2]:
        if b.get("date_creation"):
            _add(b["date_creation"], f"Business creation: {b.get('name','?')}", "SIRENE", "confirmed")

    biz_reg = report.get("phone", {})
    if biz_reg.get("region"):
        # phone carrier region is an (undated) coarse location anchor
        pass

    sm  = report.get("social_media", {})
    act = sm.get("maigret", {}).get("activity_signals", {})
    rd  = act.get("reddit", {})
    gh  = act.get("github", {})
    st  = act.get("steam", {})

    if gh.get("last_active"):
        _add(gh["last_active"], "GitHub activity", "GitHub", "confirmed",
             location=gh.get("location", ""))
    if rd.get("last_active"):
        subs = ", ".join(rd.get("subreddits", [])[:2])
        _add(rd["last_active"], "Reddit activity" + (f" ({subs})" if subs else ""), "Reddit", "confirmed")
    if st.get("last_active") or st.get("status_message"):
        when = st.get("last_active") or st.get("status_message")
        _add(str(when), f"Steam last online — @{st.get('username','?')}", "Steam", "confirmed",
             location=st.get("country", ""))

    for ig in sm.get("instagram", {}).get("found", [])[:3]:
        if ig.get("first_seen"):
            _add(ig["first_seen"], f"Instagram @{ig['username']} — first archived", "Wayback/archive", "probable")

    em = report.get("emails", {})
    for hd in report.get("hibp_details", []):
        if hd.get("breached"):
            for breach in (hd.get("breaches") or [])[:2]:
                if breach.get("BreachDate"):
                    _add(breach["BreachDate"],
                         f"Email {hd['email']} in breach: {breach.get('name','?')}",
                         "HIBP", "confirmed")

    # Sort by date descending (most recent first)
    def _sort_key(e: dict) -> str:
        return e["date"]

    events.sort(key=_sort_key, reverse=True)

    last_known = events[0] if events else None

    # ── Geotime: where the target was, when (dated + located signals) ──
    geotime = [
        {"date": e["date"], "location": e["location"], "event": e["event"],
         "source": e["source"], "confidence": e["confidence"]}
        for e in events if e.get("location")
    ]
    # Add undated coarse anchors (phone region) at the end so they're not lost
    ph_region = report.get("phone", {}).get("region")
    if ph_region and not any(g["location"] == ph_region for g in geotime):
        geotime.append({"date": "", "location": ph_region, "event": "Phone carrier region",
                        "source": "phone", "confidence": "probable"})
    last_location = next((g for g in geotime if g["date"]), None)

    return {
        "agent":      "timeline",
        "run_at":     _now_iso(),
        "events":     events,
        "event_count": len(events),
        "last_known_activity": last_known,
        "span_years": _span_years(events),
        "geotime":    geotime,
        "last_known_location": last_location,
    }


def _span_years(events: list[dict]) -> str | None:
    years = []
    for e in events:
        m = re.match(r"(\d{4})", e.get("date", ""))
        if m:
            years.append(int(m.group(1)))
    if not years:
        return None
    return f"{min(years)}–{max(years)}"


# ── Agent 5: Correlation ──────────────────────────────────────────────────────

def run_correlation_agent(report: dict) -> dict:
    """
    Find cross-source correlations, username patterns, anomalies, and hidden links.
    """
    sm   = report.get("social_media", {})
    mg   = sm.get("maigret", {})
    em   = report.get("emails", {})
    ph   = report.get("phone", {})
    dip  = report.get("diplomas", {})
    biz  = report.get("business", {})

    correlations: list[str] = []
    anomalies:    list[str] = []
    patterns:     list[str] = []

    # Username → email correlation
    ig_usernames = [p.get("username","") for p in sm.get("instagram",{}).get("found",[])[:5]]
    valid_emails  = em.get("smtp_valid", [])
    for uname in ig_usernames:
        for email in valid_emails:
            local = email.split("@")[0].lower()
            if uname.lower() in local or local in uname.lower():
                correlations.append(
                    f"Username '{uname}' appears in email '{email}' local part → strong identity link"
                )

    # Phone ↔ social: same phone found on platforms
    ign_plats = [p.get("site","") for p in ph.get("ignorant_platforms",[]) if p.get("status")=="found"]
    if ign_plats:
        correlations.append(f"Phone number linked to: {', '.join(ign_plats)}")

    # Email domain patterns
    email_domains = [_domain_of(e) for e in valid_emails + em.get("risky", [])]
    domain_counts = Counter(email_domains)
    top_domains = [d for d, _ in domain_counts.most_common(3) if d]
    if top_domains:
        patterns.append(f"Dominant email domains: {', '.join(top_domains)}")

    # Instagram → cross-data email match
    cross = report.get("emails", {}).get("ig_cross_match", [])
    for hit in cross[:3]:
        correlations.append(
            f"Instagram obfuscated hint matched: {hit['email']} [{hit['source']}]"
        )

    # Maigret cross-platform — location-relevant sites
    loc_sites = [p.get("site","") for p in mg.get("location_relevant", [])[:4]]
    if loc_sites:
        patterns.append(f"Location/sport platforms found: {', '.join(loc_sites)}")

    # Anomaly: many breaches → high exposure
    breach_count = len(em.get("breached", []))
    if breach_count >= 3:
        anomalies.append(f"High breach exposure: {breach_count} email(s) found in HIBP")
    elif breach_count >= 1:
        anomalies.append(f"Email breach detected: {', '.join(em['breached'][:2])}")

    # Anomaly: username found on many platforms → consistent identity
    total_maigret = mg.get("total_found", 0)
    if total_maigret >= 10:
        anomalies.append(f"Consistent username found on {total_maigret} platforms — strong identity fingerprint")

    # Business + social correlation
    biz_cities = [b.get("city","") for b in biz.get("sirene",[])[:2] + biz.get("pappers",[])[:2] if b.get("city")]
    locs = _extract_locations(report)
    social_cities = [l for l, _, _ in locs]
    for bc in biz_cities:
        for sc in social_cities:
            if bc.lower() in sc.lower() or sc.lower() in bc.lower():
                correlations.append(f"Business location ({bc}) matches social location ({sc})")

    return {
        "agent":        "correlation",
        "run_at":       _now_iso(),
        "correlations": correlations,
        "anomalies":    anomalies,
        "patterns":     patterns,
        "overall_coherence": _coherence_score(correlations, anomalies),
    }


def _coherence_score(correlations: list, anomalies: list) -> str:
    """Simple heuristic: more cross-source confirmations → higher coherence."""
    score = len(correlations) * 0.15 + len(anomalies) * 0.05
    if score >= 0.6:
        return "high"
    elif score >= 0.3:
        return "medium"
    return "low"


# ── Master runner ─────────────────────────────────────────────────────────────

def run_all_agents(report: dict) -> dict:
    """
    Run all 5 specialist agents and return combined pre-analysis.
    All agents are pure Python — no LLM calls — and run in <100ms total.
    """
    try:
        identity = run_identity_agent(report)
    except Exception as exc:
        identity = {"agent": "identity", "error": str(exc)}
    try:
        social = run_social_agent(report)
    except Exception as exc:
        social = {"agent": "social_media", "error": str(exc)}
    try:
        geo = run_geo_agent(report)
    except Exception as exc:
        geo = {"agent": "geolocation", "error": str(exc)}
    try:
        timeline = run_timeline_agent(report)
    except Exception as exc:
        timeline = {"agent": "timeline", "error": str(exc)}
    try:
        correlation = run_correlation_agent(report)
    except Exception as exc:
        correlation = {"agent": "correlation", "error": str(exc)}

    return {
        "identity":     identity,
        "social":       social,
        "geolocation":  geo,
        "timeline":     timeline,
        "correlations": correlation,
        "generated_at": _now_iso(),
    }
