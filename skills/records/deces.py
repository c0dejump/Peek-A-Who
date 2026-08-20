"""
French death records — the INSEE "fichier des décès" via the free deces.matchid.io
API (official open data, no key). Directly relevant to a missing-person case:
is this person recorded as deceased?

Returns matched death records with full name, birth date + place, death date +
place and age at death.
"""
from __future__ import annotations

_API = "https://deces.matchid.io/deces/api/v1/search"
_TIMEOUT = 15


def _fmt_date(d) -> str:
    """matchID dates come as 'YYYYMMDD' (or partial). Return YYYY-MM-DD."""
    s = str(d or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _s(v) -> str:
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x)
    return str(v or "")


def _loc(node: dict) -> str:
    if not isinstance(node, dict):
        return ""
    parts = [_s(node.get("city") or node.get("cityCode")),
             _s(node.get("departmentCode")),
             _s(node.get("country"))]
    return ", ".join(p for p in parts if p)


def run_sync(firstname: str = "", lastname: str = "", birth_year: str = "",
             city: str = "", size: int = 20) -> dict:
    """
    Search the INSEE death file by name (+ optional birth year / city).

    Returns:
        { "query", "total", "records": [{name, birth_date, birth_place,
          death_date, death_place, age}], "note"? }
    """
    import requests
    params: dict = {"size": max(1, min(int(size), 50))}
    if firstname: params["firstName"] = firstname
    if lastname:  params["lastName"]  = lastname
    if birth_year and str(birth_year).isdigit():
        params["birthDate"] = str(birth_year)   # matchID accepts a year
    if city:      params["birthCity"] = city
    if not (firstname or lastname):
        return {"error": "Provide at least a last name."}

    try:
        r = requests.get(_API, params=params, timeout=_TIMEOUT,
                         headers={"User-Agent": "PAW-OSINT/1.0", "Accept": "application/json"})
        if not r.ok:
            return {"error": f"HTTP {r.status_code}", "query": params}
        data = r.json()
    except Exception as exc:
        return {"error": str(exc), "query": params}

    resp = data.get("response", data)
    persons = resp.get("persons") or resp.get("results") or []
    total = resp.get("total", len(persons))

    records = []
    for p in persons[:params["size"]]:
        nm = p.get("name", {}) if isinstance(p.get("name"), dict) else {}
        first = " ".join(nm.get("first", [])) if isinstance(nm.get("first"), list) else nm.get("first", "")
        last  = nm.get("last", "") if isinstance(nm.get("last"), str) else " ".join(nm.get("last", []) or [])
        birth = p.get("birth", {}) or {}
        death = p.get("death", {}) or {}
        records.append({
            "name":        f"{first} {last}".strip() or p.get("fullText", ""),
            "birth_date":  _fmt_date(birth.get("date")),
            "birth_place": _loc(birth.get("location", {})),
            "death_date":  _fmt_date(death.get("date")),
            "death_place": _loc(death.get("location", {})),
            "age":         death.get("age") or p.get("age", ""),
        })

    out = {"query": {k: v for k, v in params.items() if k != "size"},
           "total": total, "records": records, "source": "INSEE (deces.matchid.io)"}
    if not records:
        out["note"] = "No death record found — the person is not in the INSEE deceased file."
    return out
