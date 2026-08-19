"""
Watson intent router — zero-LLM conversational fallback.

When no LLM is available (or it errors), Watson can still *do* things: this
module maps common analyst phrasings to concrete tool calls and returns a
templated answer. It is deterministic, offline, and instantaneous.

Supported intents (English + French):
  • summary        — "résumé", "what do we have", "bilan", "point"
  • email_osint    — an email address in the message
  • phone_lookup   — a phone number in the message
  • whois          — "whois <domain>"
  • web_archive    — "archive <url>" / a wayback request on a URL
  • username_check — "check/vérifie le pseudo <x>" (sherlock)
  • enrich         — "enrich <platform> <username>"
  • web_search     — "cherche / search / trouve <query>" (catch-all lead)

`route()` returns a dict {answer, tools_used, sources, confidence, intent} or
None when nothing matches (the caller then shows a help message).
"""
from __future__ import annotations

import re
from typing import Any

_EMAIL_RE  = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL_RE    = re.compile(r"https?://\S+")
_PHONE_RE  = re.compile(r"(?:\+\d{1,3}[\s.\-]?)?(?:\d[\s.\-]?){8,14}\d")
_DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.I)

_SUMMARY_RE  = re.compile(r"\b(r[ée]sum[ée]|resume|summar|bilan|recap|r[ée]capitulatif|"
                          r"what.*(have|got|know)|ce qu.?on a|qu.?on a|point|overview|status)\b", re.I)
_WHOIS_RE    = re.compile(r"\bwhois\b", re.I)
_ARCHIVE_RE  = re.compile(r"\b(archive|wayback|snapshot)\b", re.I)
_SHERLOCK_RE = re.compile(r"\b(sherlock|v[ée]rifie|verifie|check|cherche).*(pseudo|username|utilisateur|compte)\b", re.I)
_ENRICH_RE   = re.compile(r"\b(enrich|enrichi[ts]?)\b", re.I)
_SEARCH_RE   = re.compile(r"\b(cherche|recherche|search|google|trouve|find|look up|lookup)\b", re.I)

_PLATFORMS = ["instagram", "tiktok", "github", "reddit", "twitter", "linkedin",
              "snapchat", "telegram", "steam", "youtube", "facebook"]


# ── summary (the killer offline feature) ───────────────────────────────────
def _fmt_summary(report: dict) -> str:
    try:
        from skills.core.osint_reasoner import synthesize
        a = synthesize(report)
    except Exception as exc:
        return f"Could not build a summary: {exc}"

    tgt = report.get("target", {})
    name = f"{tgt.get('firstname','')} {tgt.get('lastname','')}".strip() or "the target"
    lines: list[str] = [f"**Summary — {name}**", ""]
    lines.append(a.get("executive_summary", ""))

    conf = a.get("identity", {}).get("confirmed", [])
    if conf:
        lines += ["", "**Confirmed:**"] + [f"• {c}" for c in conf[:6]]

    active = a.get("digital_presence", {}).get("active_platforms", [])
    if active:
        seen, plats = set(), []
        for p in active:
            k = (p.get("platform"), p.get("username"))
            if k not in seen:
                seen.add(k); plats.append(f"{p.get('platform','?')} @{p.get('username','?')}")
        lines += ["", "**Active platforms:** " + ", ".join(plats[:10])]

    hyps = a.get("hypotheses", [])
    if hyps:
        lines += ["", "**Working hypotheses:**"]
        for h in hyps[:4]:
            lines.append(f"• [{h.get('level','?')} {h.get('confidence',0):.0%}] {h.get('claim','')}")

    pivots = a.get("pivot_suggestions", [])
    if pivots:
        lines += ["", "**Suggested next steps:**"]
        for p in pivots[:4]:
            lines.append(f"• ({p.get('priority','?')}) {p.get('action','')}")

    missing = a.get("missing_data", [])
    if missing:
        lines += ["", "**Data gaps:** " + " ".join(missing[:3])]

    return "\n".join(l for l in lines if l is not None)


# ── entity extraction helpers ──────────────────────────────────────────────
def _pick_username(text: str) -> str:
    m = re.search(r"@([\w.\-]{2,32})", text)
    if m:
        return m.group(1)
    # token after pseudo/username/compte
    m = re.search(r"(?:pseudo|username|utilisateur|compte|account)\s*[:=]?\s*([\w.\-]{2,32})", text, re.I)
    return m.group(1) if m else ""


def _pick_platform(text: str) -> str:
    low = text.lower()
    for p in _PLATFORMS:
        if p in low:
            return p
    return ""


def _summarize_tool_result(intent: str, result: dict) -> str:
    """Turn a raw tool result into a short human sentence."""
    if result.get("error"):
        return f"⚠ {result['error']}"
    if intent == "web_search":
        rs = result.get("results", [])
        if not rs:
            return "No results found."
        out = [f"Found {len(rs)} result(s) (via {result.get('engine_used','search')}):"]
        for r in rs[:5]:
            out.append(f"• {r.get('title','')[:70]} — {r.get('domain','')}\n  {r.get('url','')}")
        return "\n".join(out)
    if intent == "username_check":
        urls = result.get("urls") or []
        n = result.get("found_count", len(urls))
        if not n:
            return "No accounts found for that username on the checked sites."
        return f"Found on {n} site(s):\n" + "\n".join(f"• {u}" for u in urls[:12])
    if intent == "email_osint":
        bits = []
        if "smtp" in result:  bits.append(f"SMTP: {result['smtp']}")
        if result.get("hibp"): bits.append(f"HIBP breaches: {result['hibp']}")
        if result.get("serp_hit") is not None:
            bits.append(f"web-indexed: {'yes' if result['serp_hit'] else 'no'}")
        return " | ".join(bits) or f"Email checked: {result}"
    # generic
    import json as _json
    return "```\n" + _json.dumps(result, ensure_ascii=False, indent=2, default=str)[:1200] + "\n```"


# ── public API ─────────────────────────────────────────────────────────────
def route(question: str, report: dict | None = None, case_id: str | None = None) -> dict[str, Any] | None:
    q = (question or "").strip()
    if not q:
        return None
    report = report or {}

    def _pack(answer: str, intent: str, tools=None, sources=None, conf="deterministic"):
        return {"answer": answer, "intent": intent, "tools_used": tools or [],
                "sources": sources or [], "confidence": conf}

    # 1) Summary — highest priority, pure local
    if _SUMMARY_RE.search(q):
        return _pack(_fmt_summary(report), "summary")

    # Lazy import of the tool executor
    def _exec(name, **params):
        from skills.core.watson_tools import execute_tool
        return execute_tool(name, params, case_id=case_id)

    # 2) Email OSINT
    m = _EMAIL_RE.search(q)
    if m:
        email = m.group(0)
        res = _exec("email_osint", email=email)
        return _pack(_summarize_tool_result("email_osint", res), "email_osint",
                     tools=[{"tool": "email_osint", "params": {"email": email}}])

    # 3) whois
    if _WHOIS_RE.search(q):
        dm = _DOMAIN_RE.search(q.replace("whois", ""))
        if dm:
            res = _exec("whois_lookup", domain=dm.group(1))
            return _pack(_summarize_tool_result("whois", res), "whois",
                         tools=[{"tool": "whois_lookup", "params": {"domain": dm.group(1)}}])

    # 4) web archive
    if _ARCHIVE_RE.search(q):
        um = _URL_RE.search(q) or _DOMAIN_RE.search(q)
        if um:
            url = um.group(0)
            res = _exec("web_archive", url=url)
            return _pack(_summarize_tool_result("web_archive", res), "web_archive",
                         tools=[{"tool": "web_archive", "params": {"url": url}}])

    # 5) username check (sherlock)
    if _SHERLOCK_RE.search(q):
        un = _pick_username(q)
        if un:
            res = _exec("sherlock_check", username=un)
            return _pack(_summarize_tool_result("username_check", res), "username_check",
                         tools=[{"tool": "sherlock_check", "params": {"username": un}}])

    # 6) enrich profile
    if _ENRICH_RE.search(q):
        plat = _pick_platform(q); un = _pick_username(q)
        if plat and un:
            res = _exec("enrich_profile", platform=plat, username=un)
            return _pack(_summarize_tool_result("enrich", res), "enrich",
                         tools=[{"tool": "enrich_profile", "params": {"platform": plat, "username": un}}])

    # 7) phone lookup
    pm = _PHONE_RE.search(q)
    if pm and len(re.sub(r"\D", "", pm.group(0))) >= 9:
        phone = pm.group(0).strip()
        res = _exec("phone_lookup", phone=phone)
        return _pack(_summarize_tool_result("phone_lookup", res), "phone_lookup",
                     tools=[{"tool": "phone_lookup", "params": {"phone": phone}}])

    # 8) generic web search (catch-all when a search verb is present)
    if _SEARCH_RE.search(q):
        # strip the search verb to build a cleaner query
        query = re.sub(_SEARCH_RE, "", q, count=1).strip(" :\"'") or q
        res = _exec("web_search", query=query, num_results=6)
        return _pack(_summarize_tool_result("web_search", res), "web_search",
                     tools=[{"tool": "web_search", "params": {"query": query}}])

    return None
