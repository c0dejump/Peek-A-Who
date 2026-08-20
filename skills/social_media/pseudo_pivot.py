"""
Pseudo pivot — turn a CONFIRMED handle into real identity data.

The pipeline is good at breadth (does username X exist on 36 sites?) but that
drowns the signal in namesakes. The strongest move is depth-first on the
analyst's own confirmed handle: web-search it to find its real profile pages
(GitHub, X/Twitter, Medium…) and enrich the GitHub profile (real name,
location, linked Twitter/blog). This is what a human investigator does first.
"""
from __future__ import annotations

# Domains worth surfacing from a handle web-search (real profiles, not noise)
_PROFILE_DOMAINS = (
    "github.com", "x.com", "twitter.com", "medium.com", "gitlab.com", "reddit.com",
    "keybase.io", "dev.to", "hackerone.com", "bugcrowd.com", "stackoverflow.com",
    "youtube.com", "twitch.tv", "linkedin.com", "gitbook.io", "notion.site",
)


def pivot_handle(handle: str, sites: list[str] | None = None) -> dict:
    """Depth-first pivot on one confirmed handle."""
    handle = handle.strip().lstrip("@")
    out: dict = {"handle": handle, "web": [], "github": None}

    # 1) Web-search the handle → keep real profile pages
    try:
        from skills.utils.search import web_search
        res = web_search(f'"{handle}"', num_results=12)
        seen = set()
        for r in res.get("results", []):
            dom = r.get("domain", "")
            if any(dom == d or dom.endswith("." + d) for d in _PROFILE_DOMAINS) and dom not in seen:
                seen.add(dom)
                out["web"].append({"domain": dom, "title": r.get("title", ""), "url": r.get("url", "")})
    except Exception:
        pass

    # 2) GitHub deep-enrich if the handle was confirmed on GitHub, or a github.com
    #    hit came back from the web search
    on_github = any("github" in (s or "").lower() for s in (sites or [])) or \
                any("github.com" in w["domain"] for w in out["web"])
    if on_github:
        try:
            from skills.social_media.enrich import enrich_profile
            gh = enrich_profile("github", handle)
            if gh.get("found"):
                out["github"] = {k: gh.get(k) for k in
                                 ("display_name", "bio", "location", "company",
                                  "external_url", "twitter", "followers", "public_repos",
                                  "created_at", "profile_pic", "url")}
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
