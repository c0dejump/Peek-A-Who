"""
Name web search — the first thing a human investigator does.

A single search for a full name (+ city) very often surfaces the target's
LinkedIn (with employer / school / location / connection count right in the
snippet) and other identity pages (GitHub, press, etc.). PAW jumped straight to
username brute-forcing and skipped this. This step fixes that: it searches the
name, keeps real profile pages, and parses the LinkedIn snippet into structured
identity fields to cross-reference with the given parameters.
"""
from __future__ import annotations

from urllib.parse import urlparse

_PROFILE_DOMAINS = (
    "linkedin.com", "github.com", "gitlab.com", "x.com", "twitter.com",
    "medium.com", "researchgate.net", "viadeo.com", "malt.fr", "welcometothejungle.com",
    "doctolib.fr", "societe.com", "pappers.fr", "theses.fr", "youtube.com",
    "instagram.com", "facebook.com",
)


def _domain(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


import re as _re

# domain → (platform, regex to pull the username/handle from the path)
_PLATFORM_PATTERNS = {
    "instagram.com": ("instagram", r"instagram\.com/([^/?#]+)"),
    "tiktok.com":    ("tiktok",    r"tiktok\.com/@([^/?#]+)"),
    "twitter.com":   ("twitter",   r"twitter\.com/([^/?#]+)"),
    "x.com":         ("twitter",   r"x\.com/([^/?#]+)"),
    "github.com":    ("github",    r"github\.com/([^/?#]+)"),
    "facebook.com":  ("facebook",  r"facebook\.com/([^/?#]+)"),
    "youtube.com":   ("youtube",   r"youtube\.com/(?:@|c/|user/)?([^/?#]+)"),
    "medium.com":    ("medium",    r"medium\.com/@?([^/?#]+)"),
}
# path segments that are not usernames
_NON_USER = {"p", "explore", "reel", "reels", "stories", "watch", "search",
             "hashtag", "profile.php", "pages", "groups", "in", "company",
             "channel", "results", "user", "c", "@"}


def _extract_handle(url: str, dom: str) -> tuple[str, str] | None:
    for d, (platform, pat) in _PLATFORM_PATTERNS.items():
        if dom == d or dom.endswith("." + d):
            m = _re.search(pat, url, _re.I)
            if m:
                u = m.group(1).strip("@").strip()
                if u and u.lower() not in _NON_USER and 1 < len(u) <= 40:
                    return platform, u
    return None


def run_sync(firstname: str, lastname: str, cities: list[str] | None = None,
             keywords: list[str] | None = None) -> dict:
    firstname, lastname = (firstname or "").strip(), (lastname or "").strip()
    if not (firstname and lastname):
        return {"error": "Need both first and last name."}
    from skills.utils.search import web_search
    try:
        from skills.social_media.linkedin import _parse_snippet
    except Exception:
        _parse_snippet = lambda s: {}

    full = f"{firstname} {lastname}"
    # Keep it to 2 queries max so the step stays fast even if an engine is slow:
    # the plain name, plus name+city (the single strongest refinement).
    queries = [f'"{full}"']
    if cities:
        queries.append(f'"{full}" {cities[0]}')

    profiles: list[dict] = []
    linkedin: list[dict] = []
    seen: set[str] = set()

    for q in queries:
        res = web_search(q, num_results=10)
        for r in res.get("results", []):
            url = r.get("url", "")
            dom = r.get("domain") or _domain(url)
            key = url.split("?", 1)[0]
            if key in seen or not any(dom == d or dom.endswith("." + d) for d in _PROFILE_DOMAINS):
                continue
            seen.add(key)
            entry = {"domain": dom, "url": url, "title": r.get("title", ""),
                     "snippet": r.get("snippet", "")}
            hp = _extract_handle(url, dom)
            if hp:
                entry["platform"], entry["username"] = hp
            profiles.append(entry)
            if "linkedin.com/in/" in url or ("linkedin.com" in dom and firstname.lower() in (r.get("title","").lower())):
                info = _parse_snippet(r.get("snippet", "") + " " + r.get("title", ""))
                linkedin.append({"url": url, "title": r.get("title", ""), **info})

    # Cross-reference LinkedIn location with the given cities
    matched_city = ""
    for li in linkedin:
        loc = (li.get("location") or "").lower()
        for c in (cities or []):
            if c.lower() in loc:
                matched_city = c
                break

    # Platform → username surfaced directly by the name search
    by_platform: dict[str, str] = {}
    for p in profiles:
        if p.get("platform") and p.get("username") and p["platform"] not in by_platform:
            by_platform[p["platform"]] = p["username"]

    # "found" = enough to skip the noisy username brute-force
    found = bool(linkedin) or len(profiles) >= 2 or len(by_platform) >= 1

    return {
        "name": full,
        "queries": queries,
        "profiles": profiles[:15],
        "linkedin": linkedin[:5],
        "by_platform": by_platform,
        "employer":  next((li.get("company") for li in linkedin if li.get("company")), ""),
        "education": next((li.get("education") for li in linkedin if li.get("education")), ""),
        "location":  next((li.get("location") for li in linkedin if li.get("location")), ""),
        "matched_city": matched_city,
        "found": found,
    }
