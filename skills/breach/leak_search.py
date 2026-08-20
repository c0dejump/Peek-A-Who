"""
Breach / leak-data search — pivots from an identifier to real leaked records.

Unlike HIBP (which only tells you *whether* an email was breached), these
providers return the leaked *content* — linked emails, usernames, passwords /
hashes, phone numbers, physical addresses, IPs — which are the strongest pivots
in an investigation.

Providers (each used only when its key is configured, so it degrades cleanly):
  • Dehashed   — DEHASHED_KEY (+ DEHASHED_EMAIL for the legacy endpoint)
  • LeakCheck  — LEAKCHECK_KEY
  • IntelX     — INTELX_KEY

Query types: email, username, phone, name, ip, domain, password, hash (auto-detected).
"""
from __future__ import annotations

import os
import re

_TIMEOUT = 20

# Fields we normalise every provider's records down to
_FIELDS = ["email", "username", "password", "hashed_password", "name",
           "phone", "address", "ip_address", "database"]


def detect_type(query: str) -> str:
    q = query.strip()
    if "@" in q and re.match(r"[^@]+@[^@]+\.[^@]+", q):
        return "email"
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", q):
        return "ip"
    if re.fullmatch(r"\+?[\d\s().-]{7,}", q):
        return "phone"
    if re.fullmatch(r"([a-z0-9-]+\.)+[a-z]{2,}", q, re.I):
        return "domain"
    if " " in q:
        return "name"
    return "username"


def _norm_entry(raw: dict, provider: str) -> dict:
    """Map a provider record onto the common field set."""
    g = lambda *keys: next((raw[k] for k in keys if raw.get(k)), "")
    return {
        "provider":        provider,
        "email":           g("email"),
        "username":        g("username", "user", "login"),
        "password":        g("password", "plaintext"),
        "hashed_password": g("hashed_password", "hash", "password_hash"),
        "name":            g("name", "full_name", "first_name"),
        "phone":           g("phone", "phone_number", "telephone"),
        "address":         g("address", "location"),
        "ip_address":      g("ip_address", "ip", "last_ip"),
        "database":        g("database_name", "database", "source", "breach"),
    }


# ── Dehashed ────────────────────────────────────────────────────────────────
def _dehashed(query: str, qtype: str) -> dict | None:
    key = os.environ.get("DEHASHED_KEY", "").strip()
    if not key:
        return None
    import requests
    field_map = {"email": "email", "username": "username", "phone": "phone",
                 "name": "name", "ip": "ip_address", "domain": "domain",
                 "password": "password", "hash": "hashed_password"}
    field = field_map.get(qtype, "")
    q = f'{field}:"{query}"' if field else query
    try:
        r = requests.post(
            "https://api.dehashed.com/v2/search",
            headers={"Dehashed-Api-Key": key, "Content-Type": "application/json"},
            json={"query": q, "page": 1, "size": 100},
            timeout=_TIMEOUT,
        )
        if r.status_code in (401, 403):
            return {"provider": "dehashed", "error": "Invalid or unauthorised DEHASHED_KEY."}
        if not r.ok:
            return {"provider": "dehashed", "error": f"HTTP {r.status_code}"}
        data = r.json()
        entries = data.get("entries") or data.get("results") or []
        return {"provider": "dehashed",
                "total": data.get("total", len(entries)),
                "entries": [_norm_entry(e, "dehashed") for e in entries[:100]]}
    except Exception as exc:
        return {"provider": "dehashed", "error": str(exc)}


# ── LeakCheck ───────────────────────────────────────────────────────────────
def _leakcheck(query: str, qtype: str) -> dict | None:
    key = os.environ.get("LEAKCHECK_KEY", "").strip()
    if not key:
        return None
    import requests
    lc_type = {"email": "email", "username": "username", "phone": "phone",
               "domain": "domain", "ip": "origin"}.get(qtype, "auto")
    try:
        r = requests.get(
            "https://leakcheck.io/api/v2/query/" + query,
            headers={"X-API-Key": key, "Accept": "application/json"},
            params={"type": lc_type} if lc_type != "auto" else None,
            timeout=_TIMEOUT,
        )
        if r.status_code in (401, 403):
            return {"provider": "leakcheck", "error": "Invalid or unauthorised LEAKCHECK_KEY."}
        if not r.ok:
            return {"provider": "leakcheck", "error": f"HTTP {r.status_code}"}
        data = r.json()
        results = data.get("result") or data.get("results") or []
        return {"provider": "leakcheck",
                "total": data.get("found", len(results)),
                "entries": [_norm_entry(e, "leakcheck") for e in results[:100]]}
    except Exception as exc:
        return {"provider": "leakcheck", "error": str(exc)}


# ── IntelX (existence/sources only — content needs paged fetch) ─────────────
def _intelx(query: str, qtype: str) -> dict | None:
    key = os.environ.get("INTELX_KEY", "").strip()
    if not key:
        return None
    import requests
    base = os.environ.get("INTELX_BASE", "https://2.intelx.io")
    try:
        s = requests.post(f"{base}/intelligent/search",
                          headers={"x-key": key, "Content-Type": "application/json"},
                          json={"term": query, "maxresults": 30, "media": 0, "sort": 4},
                          timeout=_TIMEOUT)
        if s.status_code in (401, 402, 403):
            return {"provider": "intelx", "error": "Invalid/expired INTELX_KEY or no credits."}
        if not s.ok:
            return {"provider": "intelx", "error": f"HTTP {s.status_code}"}
        sid = s.json().get("id")
        if not sid:
            return {"provider": "intelx", "total": 0, "entries": []}
        rr = requests.get(f"{base}/intelligent/search/result",
                          headers={"x-key": key}, params={"id": sid, "limit": 30},
                          timeout=_TIMEOUT)
        recs = rr.json().get("records", []) if rr.ok else []
        # IntelX returns leak *sources* (buckets/systems), not parsed fields
        entries = [{"provider": "intelx", "database": r.get("bucket", ""),
                    "name": r.get("name", ""), "date": r.get("date", ""),
                    "media": r.get("mediah", "")} for r in recs[:30]]
        return {"provider": "intelx", "total": len(entries), "entries": entries}
    except Exception as exc:
        return {"provider": "intelx", "error": str(exc)}


_PROVIDERS = [_dehashed, _leakcheck, _intelx]


def run_sync(query: str, query_type: str = "auto") -> dict:
    """
    Search leak databases for an identifier.

    Returns:
        {
          "query", "query_type",
          "providers_used": [str],
          "providers": {name: {total, entries[]} | {error}},
          "total": int,
          "linked": {emails[], usernames[], phones[], passwords_seen: int},
          "note": str,   # present when no provider is configured
        }
    """
    query = (query or "").strip()
    if not query:
        return {"error": "Empty query."}
    qtype = query_type if query_type in (
        "email", "username", "phone", "name", "ip", "domain", "password", "hash"
    ) else detect_type(query)

    results: dict[str, dict] = {}
    used: list[str] = []
    for fn in _PROVIDERS:
        res = fn(query, qtype)
        if res is None:
            continue   # provider not configured
        name = res.get("provider", fn.__name__)
        results[name] = res
        if "entries" in res:
            used.append(name)

    if not results:
        return {
            "query": query, "query_type": qtype, "providers": {}, "total": 0,
            "note": ("No leak-data provider configured. Add one of DEHASHED_KEY, "
                     "LEAKCHECK_KEY or INTELX_KEY in Settings to enable this."),
        }

    # Aggregate pivots across providers
    emails, usernames, phones, pw_seen = set(), set(), set(), 0
    total = 0
    for res in results.values():
        for e in res.get("entries", []):
            total += 1
            if e.get("email"):    emails.add(e["email"].lower())
            if e.get("username"): usernames.add(e["username"])
            if e.get("phone"):    phones.add(e["phone"])
            if e.get("password") or e.get("hashed_password"): pw_seen += 1

    return {
        "query": query, "query_type": qtype,
        "providers_used": used, "providers": results, "total": total,
        "linked": {
            "emails": sorted(emails)[:30], "usernames": sorted(usernames)[:30],
            "phones": sorted(phones)[:20], "passwords_seen": pw_seen,
        },
    }
