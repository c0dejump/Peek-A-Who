"""
Google dork skill — targeted advanced-operator searches for OSINT.

A "dork" is a search built from operators (`site:`, `filetype:`, `intitle:`,
`inurl:`, `intext:`, verbatim `"…"`) that surfaces things a plain query misses:
documents, exposed contact details, paste sites, code, social profiles.

PAW's lightweight engines (DuckDuckGo/Bing) honour some operators but rank them
poorly and skip others, so this skill runs the dorks against **real Google via a
headless browser** first (`engines=["google", …]`), falling back to Bing/DDG when
no browser is available. Everything flows through the shared `web_search`, so the
dedup / caching / result shape stay identical to the rest of PAW.

Usage (single source of truth — exposed as a Watson tool and an MCP tool):
    run_sync(firstname="Jane", lastname="Doe", pseudo="jdoe",
             email="jane@x.com", domain="example.com", city="Paris",
             keywords=["pentest"], categories=["socials","documents"])
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# extract the domains a dork restricts to, e.g. `… site:linkedin.com …` → linkedin.com
_SITE_RE = re.compile(r"site:([a-z0-9.-]+\.[a-z]{2,})", re.I)


def _site_targets(query: str) -> list[str]:
    return [m.lower() for m in _SITE_RE.findall(query or "")]


def _on_target_site(url: str, sites: list[str]) -> bool:
    """True when the result's host is (a subdomain of) one of the dorked sites."""
    if not sites:
        return True
    host = urlparse(url).netloc.lower()
    return any(host == s or host.endswith("." + s) for s in sites)

# Social/code sites worth an explicit site: sweep. Bing/DDG (the fallback when a
# real-Google browser session is blocked) handle ONE site: filter per query well
# but choke on a big "site:a OR site:b OR …" chain — so the shortlist is queried
# per-site, and only the wider OR bundle is used when Google is available.
_SOCIAL_SITES = [
    "linkedin.com", "github.com", "facebook.com", "instagram.com",
    "twitter.com", "tiktok.com", "reddit.com", "medium.com",
]
_PASTE_SITES = ["pastebin.com", "ghostbin.com", "throwbin.io", "controlc.com",
                "justpaste.it", "rentry.co"]
_DOC_TYPES = ["pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "ppt", "pptx"]

# Which engines to try, best-operator-support first. Google (headless browser)
# understands the full operator set; Bing/DDG are the resilient fallback.
_DORK_ENGINES = ["google", "bing", "ddg"]


def _q(s: str) -> str:
    return f'"{s.strip()}"' if s and " " in s.strip() else (s or "").strip()


def _build_dorks(full: str, pseudo: str, email: str, domain: str,
                 city: str, keywords: list[str], categories: set[str]) -> list[dict]:
    """Return a list of {category, label, query} dorks for the given target."""
    d: list[dict] = []
    name = f'"{full}"' if full else ""
    ident = name or (_q(pseudo) if pseudo else "") or (email or "")
    ctx = f" {_q(city)}" if city else ""

    if "socials" in categories and ident:
        # One dork per site: a single site: filter ranks reliably on every engine,
        # whereas a big "site:a OR site:b …" chain only works on real Google.
        for s in _SOCIAL_SITES:
            d.append({"category": "socials", "label": f"Profiles on {s}",
                      "query": f"{ident} site:{s}"})

    if "documents" in categories and ident:
        ftypes = " OR ".join(f"filetype:{t}" for t in _DOC_TYPES)
        d.append({"category": "documents", "label": "Documents mentioning the target",
                  "query": f"{ident}{ctx} ({ftypes})"})

    if "contact" in categories:
        if email:
            d.append({"category": "contact", "label": "Email exposure (verbatim)",
                      "query": f'"{email}"'})
        if full:
            d.append({"category": "contact", "label": "Name + contact details",
                      "query": f'{name}{ctx} (intext:"@" OR "email" OR "tel" OR "phone" OR "contact")'})

    if "leaks" in categories and (ident or email):
        pastes = " OR ".join(f"site:{s}" for s in _PASTE_SITES)
        subj = f'"{email}"' if email else ident
        d.append({"category": "leaks", "label": "Paste sites / dumps",
                  "query": f"{subj} ({pastes})"})

    if "code" in categories and (ident or pseudo or email):
        subj = _q(pseudo) if pseudo else (email or ident)
        d.append({"category": "code", "label": "Source code / repos",
                  "query": f"{subj} (site:github.com OR site:gitlab.com OR site:bitbucket.org)"})

    if "domain" in categories and domain:
        d.append({"category": "domain", "label": "Everything indexed on the domain",
                  "query": f"site:{domain}"})
        d.append({"category": "domain", "label": "Exposed documents on the domain",
                  "query": f"site:{domain} ({' OR '.join(f'filetype:{t}' for t in _DOC_TYPES)})"})
        d.append({"category": "domain", "label": "Login / admin / config surfaces",
                  "query": f"site:{domain} (inurl:login OR inurl:admin OR inurl:config OR intitle:index.of)"})

    if "keywords" in categories and full and keywords:
        for kw in keywords[:3]:
            d.append({"category": "keywords", "label": f"Name + «{kw}»",
                      "query": f'{name} {_q(kw)}'})

    return d


def run_sync(firstname: str = "", lastname: str = "", pseudo: str = "",
             email: str = "", domain: str = "", city: str = "",
             keywords: list[str] | None = None, categories: list[str] | None = None,
             per_dork: int = 6, region: str = "fr-fr",
             engines: list[str] | None = None) -> dict:
    """
    Run a set of Google dorks for a target and aggregate the results.

    categories: subset of
        socials, documents, contact, leaks, code, domain, keywords
        (default: all applicable to the given parameters).
    """
    from skills.utils.search import web_search

    firstname = (firstname or "").strip()
    lastname  = (lastname or "").strip()
    pseudo    = (pseudo or "").strip()
    email     = (email or "").strip()
    domain    = (domain or "").strip().lower()
    city      = (city or "").strip()
    keywords  = [k for k in (keywords or []) if k]
    full      = f"{firstname} {lastname}".strip()

    if not (full or pseudo or email or domain):
        return {"error": "Need at least a name, pseudo, email or domain to dork."}

    all_cats = {"socials", "documents", "contact", "leaks", "code", "domain", "keywords"}
    cats = set(categories) & all_cats if categories else all_cats
    order = engines or _DORK_ENGINES

    dorks = _build_dorks(full, pseudo, email, domain, city, keywords, cats)

    engine_used_any = ""
    agg: dict[str, dict] = {}      # norm url → result (+ which dorks hit it)
    out_dorks: list[dict] = []

    for dk in dorks:
        res = web_search(dk["query"], num_results=max(per_dork * 2, 8),
                         region=region, engines=order)
        eu = res.get("engine_used", "")
        engine_used_any = engine_used_any or eu
        # Fallback engines (Bing/DDG) don't strictly honour site: — they broaden.
        # Since the dork names the target domain(s), enforce it ourselves.
        sites = _site_targets(dk["query"])
        rows = [r for r in res.get("results", []) if _on_target_site(r.get("url", ""), sites)][:per_dork]
        for r in rows:
            key = (r.get("url", "").split("#")[0].rstrip("/"))
            if not key:
                continue
            if key in agg:
                agg[key]["dorks"].add(dk["label"])
                continue
            agg[key] = {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "domain":  r.get("domain") or (urlparse(r.get("url", "")).netloc.lower()),
                "snippet": r.get("snippet", ""),
                "category": dk["category"],
                "dorks":   {dk["label"]},
            }
        out_dorks.append({
            "category":    dk["category"],
            "label":       dk["label"],
            "query":       dk["query"],
            "engine_used": eu,
            "hits":        len(rows),
        })

    results = list(agg.values())
    for r in results:
        r["dorks"] = sorted(r["dorks"])
    # results confirmed by more than one dork rank first
    results.sort(key=lambda r: (-len(r["dorks"]), r["domain"]))

    return {
        "target":       full or pseudo or email or domain,
        "categories":   sorted(cats),
        "engine_used":  engine_used_any,
        "browser":      engine_used_any == "google",
        "dorks":        out_dorks,
        "dork_count":   len(out_dorks),
        "results":      results[:50],
        "result_count": len(results),
        "found":        bool(results),
    }


if __name__ == "__main__":
    import json, sys
    kw = sys.argv[3:] or None
    print(json.dumps(run_sync(*(sys.argv[1:3] + ["", ""])[:2],
                              keywords=kw), ensure_ascii=False, indent=2))
