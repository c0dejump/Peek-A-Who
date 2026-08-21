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

# URL path markers that mean "this is a listing / directory page", not one person.
# The malt.fr/all-freelances page polluted the web_summary with a dozen names.
_LISTING_MARKERS = ("all-freelances", "/freelances", "/search", "/recherche",
                    "/annuaire", "/directory", "/list", "/profiles", "/jobs",
                    "/candidats", "/results", "/people", "/members")
# a "Firstname Lastname" pair (Title-case) — used to detect multi-person listings
_NAME_PAIR = _re.compile(r"\b[A-ZÀ-Ÿ][a-zà-ÿ]{2,}\s+[A-ZÀ-Ÿ][a-zà-ÿ]{2,}\b")


# role/status words that mark a page as a real identity/bio page
_ROLE_RE = _re.compile(
    r"\b(d[ée]veloppeur|fondateur|ing[ée]nieur|[ée]tudiant|freelance|consultant|"
    r"bas[ée] à|domicili|travaille|CEO|g[ée]rant|responsable|directeur|manager|"
    r"student|engineer|developer|founder|based in|works? at|siret|siren|"
    r"soci[ée]t[ée]|entreprise|portfolio|profil)\b", _re.I)

# social URLs that are POSTS / VIDEOS / STATUSES, not a person's profile page
_SOCIAL_NOISE = _re.compile(
    r"facebook\.com/[^/?#]+/(?:posts|videos|photos|story|reel|events)/|"
    r"facebook\.com/(?:watch|story\.php|events|groups|permalink)|"
    r"instagram\.com/(?:p|reel|reels|tv|stories|explore)/|"
    r"tiktok\.com/@[^/?#]+/(?:video|photo)/|tiktok\.com/(?:tag|music|discover|video)/|"
    r"(?:twitter|x)\.com/[^/?#]+/status/|"
    r"youtube\.com/(?:watch|shorts|playlist)|"
    r"linkedin\.com/(?:posts|feed|pulse|jobs)/", _re.I)


def _is_social_noise(url: str) -> bool:
    return bool(_SOCIAL_NOISE.search(url or ""))


def _looks_like_listing(url: str, snip: str) -> bool:
    """A directory/listing page (many names) rather than one person's page."""
    low = url.lower()
    if any(m in low for m in _LISTING_MARKERS):
        return True
    # 3+ distinct Firstname-Lastname pairs in one snippet → a list of people
    pairs = {p.lower() for p in _NAME_PAIR.findall(snip)}
    return len(pairs) >= 3


def _extract_handle(url: str, dom: str) -> tuple[str, str] | None:
    for d, (platform, pat) in _PLATFORM_PATTERNS.items():
        if dom == d or dom.endswith("." + d):
            m = _re.search(pat, url, _re.I)
            if m:
                u = m.group(1).strip("@").strip()
                if not (u and u.lower() not in _NON_USER and 1 < len(u) <= 40):
                    return None
                # github/gitlab: a bare profile is github.com/<user>; a URL with a
                # second path segment is a REPO (github.com/keycloak/keycloak) whose
                # first segment is the org, not the person — reject it.
                if platform == "github" and _re.search(r"(?:github|gitlab)\.com/[^/?#]+/[^/?#]", url, _re.I):
                    return None
                return platform, u
    return None


def _norm(s: str) -> str:
    return _re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _handle_relevant(username: str, title: str, snip: str,
                     firstname: str, lastname: str, pseudo: str) -> bool:
    """A handle scraped from a name search is only 'the person's account' if it
    plausibly relates to them — otherwise it's noise (an org/repo like keycloak)."""
    nu = _norm(username)
    fn, ln, ps = firstname.lower(), lastname.lower(), (pseudo or "").lower()
    if ps:
        nps = _norm(ps)
        if nps and (nps in nu or nu in nps):
            return True
    if fn and len(fn) >= 3 and fn in nu:
        return True
    if ln and len(ln) >= 3 and ln in nu:
        return True
    if fn and ln:
        combos = {_norm(fn + ln), _norm(ln + fn), _norm(fn[0] + ln), _norm(fn + ln[0])}
        if nu in combos or any(c and c in nu for c in combos):
            return True
    # the page itself is clearly about the person (both names present)
    text = (title + " " + snip).lower()
    return bool(fn and ln and fn in text and ln in text)


def run_sync(firstname: str, lastname: str, cities: list[str] | None = None,
             keywords: list[str] | None = None, pseudo: str = "") -> dict:
    firstname, lastname = (firstname or "").strip(), (lastname or "").strip()
    pseudo = (pseudo or "").strip()
    if not (firstname and lastname):
        return {"error": "Need both first and last name."}
    from skills.utils.search import web_search
    try:
        from skills.social_media.linkedin import _parse_snippet
    except Exception:
        _parse_snippet = lambda s: {}

    full = f"{firstname} {lastname}"
    # Several refined queries — plain name, name+each city, name+pseudo, name+keyword.
    # Then cross-reference: results/snippets that recur across queries are stronger.
    queries = [f'"{full}"']
    for c in (cities or [])[:2]:
        queries.append(f'"{full}" {c}')
    if pseudo:
        queries.append(f'"{full}" {pseudo}')
    if keywords:
        queries.append(f'"{full}" {keywords[0]}')
    queries = list(dict.fromkeys(queries))[:5]

    agg: dict[str, dict] = {}     # norm url → aggregated entry (with recurrence)
    linkedin: list[dict] = []
    bio_candidates: list[str] = []

    for q in queries:
        # Real Google (headless browser) first — "tristan michel angers" surfaces far
        # richer/reliable results there — then fall back to Bing/DDG. If Google
        # captcha-blocks the session, the browser engine self-disables and the rest
        # of the queries use the fallback automatically.
        res = web_search(q, num_results=8, engines=["google", "bing", "ddg"])
        for r in res.get("results", []):
            url = r.get("url", "")
            dom = r.get("domain") or _domain(url)
            title, snip = r.get("title", ""), r.get("snippet", "")
            _ts   = (title + " " + snip).lower()
            _tl   = title.lower()
            fn, ln = firstname.lower(), lastname.lower()
            _both_names    = fn in _ts and ln in _ts
            _both_in_title = fn in _tl and ln in _tl
            _has_role      = bool(_ROLE_RE.search(_ts))
            # collect descriptive bios: BOTH names + a role/place word, not a listing.
            if _both_names and len(snip) >= 60 and not _looks_like_listing(url, snip) and _has_role:
                bio_candidates.append(snip.strip())

            # Never surface post/video/status URLs as a profile (facebook Zelda posts…).
            if _is_social_noise(url):
                continue

            is_profile_dom = any(dom == d or dom.endswith("." + d) for d in _PROFILE_DOMAINS)
            hp = _extract_handle(url, dom) if is_profile_dom else None
            handle_ok = bool(hp) and _handle_relevant(hp[1], title, snip, firstname, lastname, pseudo)

            # Decide whether this result is really about the target:
            #  • a name-relevant profile handle (malt/tristanmichel2, github/…), OR
            #  • any profile-domain page whose title/snippet names the person, OR
            #  • a rich identity page on ANY domain (riberadev.fr, lefigaro entreprises):
            #    both names in the title, or both names + a role word in the snippet.
            keep = handle_ok or \
                   (is_profile_dom and _both_names) or \
                   (_both_in_title or (_both_names and _has_role))
            if not keep:
                continue

            key = url.split("?", 1)[0].rstrip("/")
            if key in agg:
                agg[key]["queries"].add(q)
                continue
            entry = {"domain": dom, "url": url, "title": title, "snippet": snip, "queries": {q}}
            if handle_ok:
                entry["platform"], entry["username"] = hp
            agg[key] = entry
            if "linkedin.com/in/" in url or ("linkedin.com" in dom and firstname.lower() in title.lower()):
                info = _parse_snippet(snip + " " + title)
                linkedin.append({"url": url, "title": title, **info})

    # Rank profiles by cross-query recurrence (matches across searches = stronger)
    profiles = sorted(agg.values(), key=lambda e: (-len(e["queries"]), e["domain"]))
    for p in profiles:
        p["seen_in"] = sorted(p.pop("queries"))
    cross_confirmed = [p for p in profiles if len(p["seen_in"]) >= 2]

    # Best descriptive summary (the 'AI-overview'-like snippet)
    bio = ""
    if bio_candidates:
        bio = max(dict.fromkeys(bio_candidates), key=len)[:400]

    # Employer / location from LinkedIn snippet first, else the bio
    employer  = next((li.get("company") for li in linkedin if li.get("company")), "")
    education = next((li.get("education") for li in linkedin if li.get("education")), "")
    location  = next((li.get("location") for li in linkedin if li.get("location")), "")
    if bio and not employer:
        m = _re.search(r"(?:fondateur|founder|CEO|g[ée]rant)\s+(?:de\s+(?:la\s+)?(?:structure\s+)?|of\s+)([A-Z][\w&.\- ]{2,30})", bio)
        if m: employer = m.group(1).strip()
    if bio and not location:
        # capture only the city (Title-case token, optional Title-case continuation
        # like "Saint-Denis") — stops at lowercase words such as "et intervenant".
        m = _re.search(r"(?:bas[ée]\s+à|domicili[ée]\s+à|based in|à)\s+"
                       r"([A-ZÀ-Ÿ][a-zà-ÿ]+(?:[-\s][A-ZÀ-Ÿ][a-zà-ÿ]+){0,2})", bio)
        if m: location = m.group(1).strip()

    matched_city = ""
    for c in (cities or []):
        if any(c.lower() in (li.get("location", "") or "").lower() for li in linkedin) or \
           (bio and c.lower() in bio.lower()):
            matched_city = c
            break

    by_platform: dict[str, str] = {}
    for p in profiles:
        if p.get("platform") and p.get("username") and p["platform"] not in by_platform:
            by_platform[p["platform"]] = p["username"]

    # ── Confidence that we found the RIGHT individual (0.0 – 1.0) ─────────
    # The brute-force is only skipped above ~0.8, so this must reward signals
    # that *disambiguate* one person (a param that matched), not merely that
    # *somebody* with this name exists on the web.
    # A pseudo is only "confirmed" when it actually appears in a found handle or
    # profile URL — not merely because a result showed up in the pseudo query.
    _nps = _norm(pseudo) if pseudo else ""
    _pseudo_hit = bool(_nps) and (
        any(_nps in _norm(v) or _norm(v) in _nps for v in by_platform.values()) or
        any(_nps in _norm(p.get("url", "")) for p in profiles)
    )
    _kw_hit = bool(keywords) and bio and any(
        (k or "").lower() in bio.lower() for k in keywords)

    confidence = 0.0
    reasons: list[str] = []
    if matched_city:
        confidence += 0.40; reasons.append(f"location matches param «{matched_city}»")
    if _pseudo_hit:
        confidence += 0.40; reasons.append(f"pseudo «{pseudo}» confirmed on a profile")
    if _kw_hit:
        confidence += 0.25; reasons.append("a provided keyword appears in the bio")
    if cross_confirmed:
        confidence += min(len(cross_confirmed), 2) * 0.20    # up to +0.40
        reasons.append(f"{len(cross_confirmed)} profile(s) recur across searches")
    if linkedin and (employer or education or location):
        confidence += 0.25; reasons.append("LinkedIn snippet parsed (employer/school/location)")
    if bio:
        confidence += 0.15; reasons.append("descriptive bio found")
    confidence = round(min(confidence, 1.0), 2)

    found = bool(linkedin) or bool(bio) or len(profiles) >= 2 or len(by_platform) >= 1
    # High-confidence = we're ≥80% sure it's the right person → skip the noisy brute-force.
    high_confidence = confidence >= 0.80

    return {
        "name": full,
        "queries": queries,
        "profiles": profiles[:15],
        "cross_confirmed": cross_confirmed[:10],   # seen across ≥2 searches
        "linkedin": linkedin[:5],
        "by_platform": by_platform,
        "web_summary": bio,
        "employer": employer,
        "education": education,
        "location": location,
        "matched_city": matched_city,
        "found": found,
        "confidence": confidence,
        "high_confidence": high_confidence,
        "confidence_reasons": reasons,
    }
