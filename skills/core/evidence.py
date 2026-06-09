"""
Evidence confidence layer.

Every piece of OSINT data is tagged with:
  - source     : where the information came from
  - confidence : confirmed | probable | low | rejected
  - discovered_at : ISO timestamp
  - reasons    : list of strings explaining why this confidence level was assigned

Usage:
    ev = Evidence(value="Paris", source="GitHub profile", confidence="confirmed",
                  reasons=["location field set on GitHub account"])
    d  = ev.to_dict()   # serialisable

Factory shorthands:
    Evidence.confirmed("value", "GitHub profile", ["location field set"])
    Evidence.probable("value", "LinkedIn SERP snippet", ["city mentioned in bio"])
    Evidence.low("value", "Reddit post keyword match", [])
    Evidence.rejected("value", "HIBP false positive", ["different DOB"])
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

ConfidenceLevel = Literal["confirmed", "probable", "low", "rejected"]

_CONFIDENCE_SCORES: dict[ConfidenceLevel, float] = {
    "confirmed": 1.0,
    "probable":  0.7,
    "low":       0.35,
    "rejected":  0.0,
}


@dataclass
class Evidence:
    value:        Any
    source:       str
    confidence:   ConfidenceLevel = "low"
    reasons:      list[str]       = field(default_factory=list)
    discovered_at: str            = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    verified_at:  str | None      = None

    # ── factories ────────────────────────────────────────────────

    @classmethod
    def confirmed(cls, value: Any, source: str, reasons: list[str] | None = None) -> "Evidence":
        return cls(value=value, source=source, confidence="confirmed", reasons=reasons or [])

    @classmethod
    def probable(cls, value: Any, source: str, reasons: list[str] | None = None) -> "Evidence":
        return cls(value=value, source=source, confidence="probable", reasons=reasons or [])

    @classmethod
    def low(cls, value: Any, source: str, reasons: list[str] | None = None) -> "Evidence":
        return cls(value=value, source=source, confidence="low", reasons=reasons or [])

    @classmethod
    def rejected(cls, value: Any, source: str, reasons: list[str] | None = None) -> "Evidence":
        return cls(value=value, source=source, confidence="rejected", reasons=reasons or [])

    # ── helpers ──────────────────────────────────────────────────

    @property
    def score(self) -> float:
        return _CONFIDENCE_SCORES.get(self.confidence, 0.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = self.score
        return d

    def mark_verified(self) -> "Evidence":
        self.verified_at = datetime.now(timezone.utc).isoformat()
        return self


def merge_evidence(items: list["Evidence"]) -> ConfidenceLevel:
    """
    Combine multiple evidence items into a single confidence level.
    Rules:
      - 2+ confirmed → confirmed
      - 1 confirmed + 1 probable → confirmed
      - 2+ probable → probable
      - rest → low
    """
    confirmed_count = sum(1 for e in items if e.confidence == "confirmed")
    probable_count  = sum(1 for e in items if e.confidence == "probable")
    if confirmed_count >= 2 or (confirmed_count >= 1 and probable_count >= 1):
        return "confirmed"
    if confirmed_count == 1 or probable_count >= 2:
        return "probable"
    return "low"


def build_context_summary(report: dict) -> dict:
    """
    Build a compact, LLM-friendly context dict from a full investigation report.
    Used by the chat endpoint to stay within token limits.
    """
    sm   = report.get("social_media", {})
    mg   = sm.get("maigret", {})
    act  = mg.get("activity_signals", {})
    ph   = report.get("phone", {})
    em   = report.get("emails", {})
    dip  = report.get("diplomas", {})
    biz  = report.get("business", {})
    dem  = report.get("demographics", {})
    tl   = report.get("timeline", {})

    ig_found = [
        {"username": p.get("username"), "display_name": p.get("display_name"),
         "relevance": p.get("relevance"), "bio": p.get("bio", "")[:120]}
        for p in sm.get("instagram", {}).get("found", [])[:5]
    ]
    tt_found = [
        {"username": p.get("username"), "display_name": p.get("display_name"),
         "relevance": p.get("relevance")}
        for p in sm.get("tiktok", {}).get("found", [])[:4]
    ]
    li_found = sm.get("linkedin", {}).get("serp_found", [])[:3]
    maigret_cats = {
        k: [{"site": p.get("site"), "url": p.get("url")} for p in v[:4]]
        for k, v in mg.items()
        if isinstance(v, list) and v and k != "activity_signals"
    }
    platforms = {
        k: [{"username": p.get("username"), "url": p.get("url")}
            for p in v.get("found", [])[:3]]
        for k, v in sm.get("platforms", {}).items()
        if v.get("found")
    }

    return {
        "target":       report.get("target", {}),
        "demographics": {
            "bearers_france": dem.get("bearers_since_1890"),
            "origin":         dem.get("name_origin", "")[:100],
        },
        "phone": {
            "number":  ph.get("formatted"),
            "type":    ph.get("type"),
            "carrier": ph.get("carrier"),
            "region":  ph.get("region"),
            "found_on": [p.get("site") for p in ph.get("ignorant_platforms", [])
                         if p.get("status") == "found"],
        } if ph else None,
        "diplomas": {
            "bac":    [(b.get("name"), b.get("year")) for b in dip.get("bac_results", [])[:3]],
            "theses": [(t.get("title", "")[:60], t.get("year")) for t in dip.get("theses", [])[:2]],
        },
        "business": {
            "sirene":  [(b.get("name"), b.get("city")) for b in biz.get("sirene", [])[:3]],
            "pappers": [(b.get("name"), b.get("city")) for b in biz.get("pappers", [])[:3]],
        },
        "social_media": {
            "instagram":   ig_found,
            "tiktok":      tt_found,
            "linkedin":    [{"url": p.get("url"), "title": p.get("title"), "company": p.get("company"),
                             "location": p.get("location")} for p in li_found],
            "maigret":     {"total": mg.get("total_found", 0), "by_category": maigret_cats},
            "platforms":   platforms,
        },
        "activity": {
            "reddit": act.get("reddit", {}),
            "github": act.get("github", {}),
        },
        "emails": {
            "smtp_valid":      em.get("smtp_valid", []),
            "risky":           em.get("risky", []),
            "serp_likely":     em.get("serp_likely", []),
            "breached":        em.get("breached", []),
            "ghunt_confirmed": em.get("ghunt_confirmed", []),
        },
        "identity":  tl.get("llm_identity", ""),
        "timeline":  tl.get("llm_timeline", ""),
        "locations": tl.get("llm_locations", ""),
        "analysis":  report.get("analysis", {}),
    }
