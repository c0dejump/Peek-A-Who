"""
Pseudo pivot — turn a CONFIRMED handle into real identity data.

The pipeline is good at breadth (does username X exist on 36 sites?) but that
drowns the signal in namesakes. The strongest move is depth-first on the
analyst's own confirmed handle: web-search it to find its real profile pages
(GitHub, X/Twitter, Medium…) and enrich the GitHub profile (real name,
location, linked Twitter/blog). This is what a human investigator does first.
"""
from __future__ import annotations

import re

# Domains worth surfacing from a handle web-search (real profiles, not noise)
_PROFILE_DOMAINS = (
    "github.com", "x.com", "twitter.com", "medium.com", "gitlab.com", "reddit.com",
    "keybase.io", "dev.to", "hackerone.com", "bugcrowd.com", "stackoverflow.com",
    "youtube.com", "twitch.tv", "linkedin.com", "gitbook.io", "notion.site",
)

# common leet letter↔digit swaps — "codejump" → "c0dejump", etc.
_LEET = [("o", "0"), ("i", "1"), ("l", "1"), ("e", "3"), ("a", "4"), ("s", "5"), ("t", "7"), ("b", "8")]
# path segments on github/gitlab that are NOT a username
_CODE_NONUSER = {"orgs", "sponsors", "topics", "search", "marketplace", "features",
                 "about", "pricing", "explore", "trending", "collections", "login",
                 "settings", "notifications", "new", "apps"}


def _leet_variants(handle: str, maxn: int = 18) -> list[str]:
    """Small set of leetspeak variants so 'codejump' also probes 'c0dejump'."""
    h = handle.lower()
    variants = [h]
    seen = {h}
    # swap ALL occurrences of each class, both directions
    for a, b in _LEET:
        for x, y in ((a, b), (b, a)):
            v = h.replace(x, y)
            if v != h and v not in seen:
                seen.add(v); variants.append(v)
    # single-position swaps (catches a leet char in just one spot)
    for i, ch in enumerate(h):
        for a, b in _LEET:
            for x, y in ((a, b), (b, a)):
                if ch == x:
                    v = h[:i] + y + h[i + 1:]
                    if v not in seen:
                        seen.add(v); variants.append(v)
    return variants[:maxn]


def _github_username(url: str) -> str | None:
    """Return the username IFF url is a bare github/gitlab *profile* page (not a repo)."""
    m = re.match(r"https?://(?:www\.)?(?:github|gitlab)\.com/([^/?#]+)/?(?:[?#].*)?$", url, re.I)
    if not m:
        return None
    user = m.group(1).lower()
    return None if user in _CODE_NONUSER else user


def _github_probe(user: str) -> dict:
    """Probe a GitHub profile via the *web* page (not rate-limited like the API).
    Returns {exists: bool|None, name: str} — name is the displayed full name if any."""
    import requests
    out = {"exists": None, "name": ""}
    try:
        r = requests.get(f"https://github.com/{user}",
                         headers={"User-Agent": "Mozilla/5.0 (PAW-OSINT)"},
                         timeout=8, allow_redirects=True)
        if r.status_code == 404:
            out["exists"] = False
            return out
        if r.status_code == 200 and f"/{user.lower()}" in (r.url or "").lower():
            out["exists"] = True
            m = re.search(r'itemprop="name"[^>]*>\s*([^<]+?)\s*<', r.text)
            if m:
                nm = m.group(1).strip()
                if nm and nm.lower() != user.lower():
                    out["name"] = nm
    except Exception:
        pass
    return out


def pivot_handle(handle: str, sites: list[str] | None = None,
                 firstname: str = "", lastname: str = "") -> dict:
    """Depth-first pivot on one confirmed handle."""
    handle = handle.strip().lstrip("@")
    out: dict = {"handle": handle, "web": [], "github": None, "github_candidates": []}
    variants = _leet_variants(handle)
    _vset = set(variants)

    from skills.social_media.enrich import enrich_profile

    # 1) GitHub: the handle OR a leet variant (codejump → c0dejump) may be a real
    #    user — and several can co-exist as DIFFERENT people. Collect every variant
    #    that actually exists (web-page check, not API-rate-limited) as a candidate.
    cands: list[dict] = []
    for cand in variants:
        p = _github_probe(cand)
        if p["exists"]:
            cands.append({"username": cand, "url": f"https://github.com/{cand}",
                          "name": p.get("name", "")})
        if len(cands) >= 4:
            break
    out["github_candidates"] = cands

    # Pick one only when it's unambiguous: a single candidate, or one whose profile
    # name matches the target. Otherwise leave `github` empty and let all candidates
    # surface as leads (we must not assert the wrong namesake).
    chosen = None
    if len(cands) == 1:
        chosen = cands[0]
    elif cands and (firstname or lastname):
        fn, ln = firstname.lower(), lastname.lower()
        for c in cands:
            nm = (c.get("name") or "").lower()
            if nm and ((fn and fn in nm) or (ln and ln in nm)):
                chosen = c
                break
    if chosen:
        gh = {}
        try:
            gh = enrich_profile("github", chosen["username"])     # rich data if the API isn't rate-limited
        except Exception:
            gh = {}
        entry = {k: gh.get(k) for k in
                 ("display_name", "bio", "location", "company", "external_url",
                  "twitter", "followers", "public_repos", "created_at", "profile_pic")}
        entry["url"] = gh.get("url") or chosen["url"]
        entry["username"] = chosen["username"]
        entry["verified"] = bool(gh.get("found"))
        out["github"] = entry
        out["handle_resolved"] = chosen["username"]

    # 2) Web-search the handle → keep real profile pages. For github/gitlab, ONLY
    #    keep a bare profile page whose username matches the handle or a variant —
    #    reject other people's repos (github.com/<someone-else>/<repo>).
    try:
        from skills.utils.search import web_search
        res = web_search(f'"{handle}"', num_results=12)
        seen = set()
        for r in res.get("results", []):
            dom = r.get("domain", "")
            url = r.get("url", "")
            if not any(dom == d or dom.endswith("." + d) for d in _PROFILE_DOMAINS):
                continue
            if "github.com" in dom or "gitlab.com" in dom:
                gu = _github_username(url)
                if not gu or gu not in _vset:
                    continue            # a repo, or a different user → skip
            if dom in seen:
                continue
            seen.add(dom)
            out["web"].append({"domain": dom, "title": r.get("title", ""), "url": url})
    except Exception:
        pass

    return out


def run_sync(pseudo_confirmed: dict, max_handles: int = 4) -> dict:
    """
    Pivot on every confirmed handle. `pseudo_confirmed` is {handle: [sites]}.
    Returns {handles: {handle: {web[], github}}, identity: {name, location, twitter}}.
    """
    handles = list((pseudo_confirmed or {}).items())[:max_handles]
    results: dict = {}
    name = location = twitter = ""
    for handle, sites in handles:
        p = pivot_handle(handle, sites)
        results[handle] = p
        gh = p.get("github") or {}
        name = name or gh.get("display_name", "")
        location = location or gh.get("location", "")
        twitter = twitter or gh.get("twitter", "")
    return {
        "handles": results,
        "identity": {"name": name, "location": location, "twitter": twitter},
    }
