"""
Deterministic OSINT reasoner — zero-LLM synthesis.

Produces the same `report["analysis"]` schema the LLM synthesis step emits, but
purely from rules over the 5 specialist agents' output (`run_all_agents`) plus
the raw report. This makes PAW fully useful with no model available at all:
  cloud LLM  →  local Ollama  →  THIS deterministic reasoner (always works).

Everything is pure Python, offline, and runs in <50ms. Natural-language pieces
are templated, not generated, so they are stable and never hallucinate.
"""
from __future__ import annotations

from typing import Any


# ── small helpers ──────────────────────────────────────────────────────────
def _first(seq: list, default=None):
    return seq[0] if seq else default


def _confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "moderate"
    if score > 0.0:
        return "low"
    return "insufficient"


def _pseudo_confirmed(report: dict) -> dict[str, list[str]]:
    return report.get("social_media", {}).get("maigret", {}).get("pseudo_confirmed") or {}


def _fmt_last_activity(last: Any) -> str:
    """last_known_activity may be a dict {date,event,source} or a string."""
    if isinstance(last, dict):
        date = last.get("date", "")
        event = last.get("event", "")
        src = last.get("source", "")
        s = " — ".join(x for x in (date, event) if x)
        return f"{s} ({src})" if src else s
    return str(last or "")


# ── executive summary (templated) ──────────────────────────────────────────
def _build_summary(report: dict, ident: dict, social: dict, geo: dict,
                   timeline: dict, gc: float) -> str:
    tgt = report.get("target", {})
    name = f"{tgt.get('firstname','')} {tgt.get('lastname','')}".strip() or "The target"
    parts: list[str] = []

    conf_id = ident.get("confirmed", [])
    if conf_id:
        parts.append(f"{name}: {len(conf_id)} confirmed identity signal(s).")
    else:
        parts.append(f"{name}: no identity fact could be confirmed from independent sources.")

    active = social.get("active_platforms", [])
    if active:
        plats = ", ".join(dict.fromkeys(p.get("platform", "") for p in active if p.get("platform")))
        parts.append(f"Active online presence on: {plats}.")

    est = geo.get("current_estimate", "")
    if est:
        parts.append(f"Most likely location: {est}.")

    last = _fmt_last_activity(timeline.get("last_known_activity"))
    if last:
        parts.append(f"Last known online activity: {last}.")

    parts.append(f"Overall identity certainty: {_confidence_label(gc)} ({gc:.0%}).")
    return " ".join(parts)


# ── hypotheses (rule-generated, falsifiable) ───────────────────────────────
def _build_hypotheses(report: dict, ident: dict, social: dict, geo: dict) -> list[dict]:
    hyps: list[dict] = []

    # H1 — user-provided pseudo is the target (strongest anchor)
    pc = _pseudo_confirmed(report)
    for un, sites in pc.items():
        hyps.append({
            "claim": f"The account '@{un}' belongs to the target.",
            "confidence": 0.9,
            "level": "confirmed",
            "supporting": [f"Analyst-provided pseudo found on {len(sites)} site(s): {', '.join(sites)}"],
            "against": [],
        })

    # H2 — identity from concordant sources
    if len(ident.get("confirmed", [])) >= 2:
        hyps.append({
            "claim": "The civil identity is correctly attributed.",
            "confidence": min(0.85, 0.5 + 0.15 * len(ident["confirmed"])),
            "level": "confirmed" if len(ident["confirmed"]) >= 3 else "probable",
            "supporting": ident["confirmed"][:3],
            "against": ident.get("rejected", [])[:2],
        })
    elif ident.get("probable"):
        hyps.append({
            "claim": "The civil identity is plausibly attributed but under-corroborated.",
            "confidence": 0.4,
            "level": "low",
            "supporting": ident["probable"][:2],
            "against": ident.get("rejected", [])[:2],
        })

    # H3 — geolocation
    conf_loc = geo.get("confirmed_locations", [])
    prob_loc = geo.get("probable_locations", [])
    if conf_loc:
        loc = conf_loc[0]
        hyps.append({
            "claim": f"The target is based in {loc.get('location','?')}.",
            "confidence": 0.7,
            "level": "probable",
            "supporting": [f"{loc.get('location','?')} — {loc.get('source','?')}"],
            "against": [],
        })
    elif prob_loc:
        loc = prob_loc[0]
        hyps.append({
            "claim": f"The target may be located in {loc.get('location','?')}.",
            "confidence": 0.35,
            "level": "low",
            "supporting": [f"{loc.get('location','?')} — {loc.get('source','?')}"],
            "against": [],
        })

    # H4 — single coherent digital persona
    up = social.get("username_pattern", "")
    if social.get("maigret_total", 0) >= 3 and up:
        hyps.append({
            "claim": "The target reuses a consistent username pattern across platforms.",
            "confidence": 0.5,
            "level": "probable",
            "supporting": [f"Username pattern: {up}",
                           f"{social.get('maigret_total',0)} cross-platform hits"],
            "against": [],
        })

    return hyps


# ── pivots (actionable next steps) ─────────────────────────────────────────
def _build_pivots(report: dict, social: dict, geo: dict, timeline: dict) -> list[dict]:
    pivots: list[dict] = []
    sm = report.get("social_media", {})

    # Confirmed pseudo → manual deep-dive
    for un, sites in _pseudo_confirmed(report).items():
        pivots.append({
            "action": f"Open @{un} on {', '.join(sites[:3])} and extract bio, links, and recent activity.",
            "priority": "high",
            "rationale": "Analyst-confirmed account — richest lead in the case.",
        })

    # Gmail candidates → GHunt
    breached = report.get("emails", {}).get("breached", [])
    gmails = [e for e in (report.get("emails", {}).get("smtp_valid", []) + breached)
              if isinstance(e, str) and e.endswith("@gmail.com")]
    if gmails:
        pivots.append({
            "action": f"Run GHunt on {gmails[0]} to recover Google account name, photo and reviews.",
            "priority": "high",
            "rationale": "A valid Gmail unlocks Google Maps reviews, YouTube, and profile photo.",
        })

    # LinkedIn candidates → manual check
    cands = sm.get("linkedin", {}).get("candidates", [])
    if cands and not sm.get("linkedin", {}).get("serp_found"):
        pivots.append({
            "action": f"Manually open the {len(cands)} LinkedIn candidate URL(s) — automated access is blocked.",
            "priority": "medium",
            "rationale": "LinkedIn returns 999 to bots; a human session can confirm employer and city.",
        })

    # Instagram not fully checked
    ig = sm.get("instagram", {})
    if ig.get("rate_limited") or (ig.get("checked", 0) and not ig.get("found")):
        pivots.append({
            "action": "Re-run the Instagram username check later (or logged in) — the search was rate-limited.",
            "priority": "medium",
            "rationale": "Instagram's login wall capped the pass; likely profiles were not reached.",
        })

    # Stale last activity
    last = _fmt_last_activity(timeline.get("last_known_activity"))
    if last:
        pivots.append({
            "action": f"Corroborate the last-seen date ({last}) against other platforms to bound the timeline.",
            "priority": "low",
            "rationale": "Tightening the last-activity window is key for a missing-person case.",
        })

    # No location at all
    if not geo.get("confirmed_locations") and not geo.get("probable_locations"):
        pivots.append({
            "action": "Search classified-ad and marketplace sites for the phone/name to surface a city.",
            "priority": "medium",
            "rationale": "No geolocation signal yet; ads often leak a town.",
        })

    return pivots


# ── human verifications ────────────────────────────────────────────────────
def _build_human_checks(report: dict, social: dict) -> list[str]:
    checks: list[str] = []
    sm = report.get("social_media", {})
    for c in sm.get("linkedin", {}).get("candidates", [])[:5]:
        checks.append(f"Manually verify LinkedIn candidate: {c.get('url', c)}")
    for p in social.get("active_platforms", []):
        if p.get("url"):
            checks.append(f"Confirm {p.get('platform','?')} profile: {p['url']}")
    # BeReal / unverifiable platforms
    for pk, pv in sm.get("platforms", {}).items():
        for cand in (pv.get("candidates", []) or [])[:2]:
            if isinstance(cand, str) and cand.startswith("http"):
                checks.append(f"Manually check {pk}: {cand}")
    return checks[:10]


# ── risk indicators & missing data ─────────────────────────────────────────
def _build_risk(report: dict, ident: dict, geo: dict, corr: dict) -> list[str]:
    risks: list[str] = []
    if not ident.get("confirmed"):
        risks.append("Identity unconfirmed — all conclusions are tentative.")
    for a in corr.get("anomalies", [])[:4]:
        risks.append(a if isinstance(a, str) else str(a))
    if ident.get("rejected"):
        risks.append(f"{len(ident['rejected'])} assumption(s) actively contradicted by evidence.")
    if len(geo.get("probable_locations", [])) >= 3:
        risks.append("Multiple divergent location signals — possible namesake confusion.")
    return risks


def _build_missing(report: dict, ident: dict, social: dict, geo: dict) -> list[str]:
    missing: list[str] = []
    if not report.get("phone", {}).get("valid"):
        missing.append("A verified phone number would enable reverse-lookup and messaging-app checks.")
    if not report.get("emails", {}).get("smtp_valid"):
        missing.append("An SMTP-verified email would unlock GHunt and breach correlation.")
    if not geo.get("confirmed_locations"):
        missing.append("A confirmed city/region is still missing.")
    if not social.get("active_platforms"):
        missing.append("No high-relevance social profile confirmed yet.")
    if not report.get("target", {}).get("birth_year"):
        missing.append("Birth year would disambiguate namesakes.")
    return missing


# ── public API ─────────────────────────────────────────────────────────────
def synthesize(report: dict, pre_analysis: dict | None = None) -> dict:
    """
    Build the full `analysis` schema deterministically. `pre_analysis` is the
    output of `run_all_agents`; if omitted it is computed here.
    """
    if pre_analysis is None:
        try:
            from skills.core.agents import run_all_agents
            pre_analysis = run_all_agents(report)
        except Exception:
            pre_analysis = {}

    ident    = pre_analysis.get("identity", {}) or {}
    social   = pre_analysis.get("social", {}) or {}
    geo      = pre_analysis.get("geolocation", {}) or {}
    timeline = pre_analysis.get("timeline", {}) or {}
    corr     = pre_analysis.get("correlations", pre_analysis.get("correlation", {})) or {}

    gc = float(ident.get("confidence_score", 0.0) or 0.0)

    # digital presence
    active = social.get("active_platforms", [])
    behavioral = []
    if social.get("activity_signals"):
        behavioral = list(social["activity_signals"])[:4]

    # geolocation buckets → simple string lists (schema shape)
    geo_conf = [f"{l.get('location','?')} ({l.get('source','?')})"
                for l in geo.get("confirmed_locations", [])]
    geo_prob = [f"{l.get('location','?')} ({l.get('source','?')})"
                for l in geo.get("probable_locations", [])]

    # timeline events → schema shape
    tl = [{"date": e.get("date", ""), "event": e.get("event", ""),
           "confidence": e.get("confidence", "probable"), "source": e.get("source", "")}
          for e in timeline.get("events", [])][:12]

    # relational network (from correlation patterns, best-effort)
    assoc = list(social.get("username_variants", []))[:10]

    analysis = {
        "executive_summary": _build_summary(report, ident, social, geo, timeline, gc),
        "global_confidence": round(gc, 2),
        "identity": {
            "confirmed": ident.get("confirmed", []),
            "probable":  ident.get("probable", []),
            "rejected":  ident.get("rejected", []),
        },
        "digital_presence": {
            "active_platforms": [
                {"platform": p.get("platform", ""), "username": p.get("username", ""),
                 "note": p.get("source", "") or p.get("url", "")}
                for p in active
            ],
            "inactive_platforms": [
                {"platform": p.get("platform", ""), "username": p.get("username", "")}
                for p in social.get("inactive_platforms", [])[:15]
            ],
            "username_pattern": social.get("username_pattern", ""),
            "behavioral_notes": behavioral,
        },
        "geolocation": {
            "confirmed": geo_conf,
            "probable":  geo_prob,
            "current_estimate": geo.get("current_estimate", ""),
        },
        # Geo-temporal track: where the target was, when (most recent first)
        "geotime": timeline.get("geotime", []),
        "last_known_location": timeline.get("last_known_location"),
        "last_known_activity": _fmt_last_activity(timeline.get("last_known_activity")),
        "relational_network": {
            "contacts": [],
            "associated_accounts": assoc,
            "platforms_with_followers": [],
        },
        "risk_indicators": _build_risk(report, ident, geo, corr),
        "hypotheses": _build_hypotheses(report, ident, social, geo),
        "timeline": tl,
        "pivot_suggestions": _build_pivots(report, social, geo, timeline),
        "human_verifications": _build_human_checks(report, social),
        "missing_data": _build_missing(report, ident, social, geo),
        "engine": "deterministic",   # marks a no-LLM synthesis for the UI
    }
    return analysis
