"""
Profile enrichment skill — fetches bio, followers and metadata
for a validated social media profile.

Called after the investigator clicks "Valider" on a found profile.
Returns a dict with all extractable fields; missing fields are omitted.

Supported platforms:
  instagram  — mobile API → Playwright fallback
  tiktok     — embedded JSON (same request as detection, more fields)
  linkedin   — blocked; returns url only
  other      — returns url only

Usage:
    from skills.social_media.enrich import enrich_profile
    data = enrich_profile("tiktok", "khaby.lame", "https://www.tiktok.com/@khaby.lame")
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

_UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_UA_IG_APP = (
    "Instagram 210.0.0.28.71 Android (26/8.0.0; 480dpi; 1080x1920; "
    "OnePlus; 6T Dev; devitron; qcom; en_US; 314665256)"
)
_UA_FB = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"


# ── helpers ──────────────────────────────────────────────────────────────────

def _re1(pattern: str, text: str, group: int = 1, flags: int = 0) -> str:
    """Return first regex match group, or empty string."""
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else ""


def _int1(pattern: str, text: str) -> int | None:
    """Return first regex match as int, or None."""
    m = re.search(pattern, text)
    if m:
        try:
            return int(m.group(1).replace(",", "").replace(" ", ""))
        except ValueError:
            pass
    return None


def _unescape(s: str) -> str:
    """Decode \\u002F and similar unicode escapes."""
    try:
        return s.encode("utf-8").decode("unicode_escape")
    except Exception:
        return s


# ── Instagram ─────────────────────────────────────────────────────────────────

def _enrich_instagram(username: str) -> dict:
    import requests

    result: dict = {"platform": "instagram", "username": username,
                    "url": f"https://www.instagram.com/{username}/"}

    # 1) Try mobile API
    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": _UA_IG_APP,
            "x-ig-app-id": "936619743392459",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        r = sess.get(
            "https://i.instagram.com/api/v1/users/web_profile_info/",
            params={"username": username},
            timeout=12,
        )
        if r.status_code == 200:
            user = r.json().get("data", {}).get("user", {})
            if user:
                result["display_name"]  = user.get("full_name", "")
                result["bio"]           = user.get("biography", "")
                result["followers"]     = (user.get("edge_followed_by") or {}).get("count")
                result["following"]     = (user.get("edge_follow") or {}).get("count")
                result["posts"]         = (user.get("edge_owner_to_timeline_media") or {}).get("count")
                result["is_private"]    = user.get("is_private")
                result["is_verified"]   = user.get("is_verified")
                result["profile_pic"]   = user.get("profile_pic_url_hd") or user.get("profile_pic_url", "")
                result["external_url"]  = user.get("external_url", "")
                result["source"]        = "instagram_api"
                return {k: v for k, v in result.items() if v not in (None, "", [])}
    except Exception:
        pass

    # 2) Fallback: facebookexternalhit UA → og:title
    try:
        import requests as _req
        r2 = _req.get(
            f"https://www.instagram.com/{username}/",
            headers={"User-Agent": _UA_FB, "Accept-Language": "en-US,en;q=0.9"},
            timeout=12, allow_redirects=True,
        )
        if r2.status_code == 200:
            og_title = _re1(r'property="og:title"\s+content="([^"]+)"', r2.text)
            og_desc  = _re1(r'property="og:description"\s+content="([^"]+)"', r2.text)
            og_img   = _re1(r'property="og:image"\s+content="([^"]+)"', r2.text)
            if og_title:
                result["display_name"] = og_title
                result["bio"]          = og_desc
                result["profile_pic"]  = og_img
                result["source"]       = "og_tags"
                return {k: v for k, v in result.items() if v not in (None, "", [])}
    except Exception:
        pass

    # 3) Fallback: Playwright
    try:
        from skills.utils.browser import BrowserSession
        with BrowserSession() as b:
            status, html = b.fetch(
                f"https://www.instagram.com/{username}/",
                networkidle_timeout=8000,
            )
            if status == 200 and "login" not in html[:1000].lower():
                bio      = _re1(r'"biography"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
                fn       = _re1(r'"full_name"\s*:\s*"([^"]+)"', html)
                fol      = _int1(r'"edge_followed_by"\s*:\s*\{"count"\s*:\s*(\d+)', html)
                fol2     = _int1(r'"edge_follow"\s*:\s*\{"count"\s*:\s*(\d+)', html)
                posts    = _int1(r'"edge_owner_to_timeline_media"\s*:\s*\{"count"\s*:\s*(\d+)', html)
                pic      = _re1(r'"profile_pic_url_hd"\s*:\s*"([^"]+)"', html)
                if fn or bio or fol:
                    if fn:         result["display_name"] = fn
                    if bio:        result["bio"]          = bio
                    if fol:        result["followers"]    = fol
                    if fol2:       result["following"]    = fol2
                    if posts:      result["posts"]        = posts
                    if pic:        result["profile_pic"]  = pic
                    result["source"] = "playwright"
    except Exception:
        pass

    result["source"] = result.get("source", "detection_only")
    return {k: v for k, v in result.items() if v not in (None, "", [])}


# ── TikTok ────────────────────────────────────────────────────────────────────

def _enrich_tiktok(username: str) -> dict:
    import requests

    result: dict = {"platform": "tiktok", "username": username,
                    "url": f"https://www.tiktok.com/@{username}"}

    try:
        r = requests.get(
            f"https://www.tiktok.com/@{username}",
            headers={
                "User-Agent": _UA_CHROME,
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=14, allow_redirects=True,
        )
        if r.status_code != 200:
            result["error"] = f"HTTP {r.status_code}"
            return result

        html = r.text

        # All fields live in the embedded __UNIVERSAL_DATA__ / sigi-state JSON blob
        uid        = _re1(r'"uniqueId"\s*:\s*"([^"]+)"', html)
        if uid.lower() != username.lower():
            result["error"] = "profile not found"
            return result

        nickname   = _re1(r'"nickname"\s*:\s*"([^"]+)"', html)
        bio        = _re1(r'"signature"\s*:\s*"([^"]+)"', html)
        followers  = _int1(r'"followerCount"\s*:\s*(\d+)', html)
        following  = _int1(r'"followingCount"\s*:\s*(\d+)', html)
        hearts     = _int1(r'"heartCount"\s*:\s*"?(\d+)"?', html)
        videos     = _int1(r'"videoCount"\s*:\s*(\d+)', html)
        avatar_raw = _re1(r'"avatarLarger"\s*:\s*"([^"]+)"', html)
        verified   = '"verified":true' in html or '"verified": true' in html

        # TikTok JSON uses / for /
        avatar = avatar_raw.replace("\\u002F", "/").replace("\\/", "/") if avatar_raw else ""

        if nickname:  result["display_name"] = nickname
        if bio:       result["bio"]          = bio.replace("\\n", " ")
        if followers is not None: result["followers"]  = followers
        if following is not None: result["following"]  = following
        if hearts is not None:    result["hearts"]     = hearts
        if videos is not None:    result["videos"]     = videos
        if avatar:                result["profile_pic"] = avatar
        result["is_verified"] = verified
        result["source"]      = "embedded_json"

    except Exception as exc:
        result["error"] = str(exc)

    return {k: v for k, v in result.items() if v not in (None, "", [])}


# ── LinkedIn ──────────────────────────────────────────────────────────────────

def _enrich_linkedin(username: str, url: str) -> dict:
    return {
        "platform":  "linkedin",
        "username":  username,
        "url":       url or f"https://www.linkedin.com/in/{username}/",
        "source":    "unverified",
        "note":      "LinkedIn bloque toutes les requêtes automatisées. Vérification manuelle requise.",
    }


def _enrich_github(username: str, url: str = "") -> dict:
    """GitHub public profile via the REST API — real name, location, linked Twitter/blog."""
    import requests
    out = {"platform": "github", "username": username,
           "url": url or f"https://github.com/{username}", "found": False}
    try:
        r = requests.get(f"https://api.github.com/users/{username}",
                         headers={"User-Agent": "PAW-OSINT/1.0", "Accept": "application/vnd.github+json"},
                         timeout=10)
        if r.status_code == 404:
            return {**out, "note": "No such GitHub user."}
        if r.status_code == 403:
            return {**out, "note": "GitHub API rate-limited (unauthenticated)."}
        if not r.ok:
            return {**out, "note": f"HTTP {r.status_code}"}
        d = r.json()
        out.update({
            "found": True,
            "display_name": d.get("name") or "",
            "bio":          d.get("bio") or "",
            "location":     d.get("location") or "",
            "company":      d.get("company") or "",
            "external_url": d.get("blog") or "",
            "twitter":      d.get("twitter_username") or "",
            "followers":    d.get("followers"),
            "public_repos": d.get("public_repos"),
            "created_at":   (d.get("created_at") or "")[:10],
            "profile_pic":  d.get("avatar_url") or "",
        })
        return out
    except Exception as exc:
        return {**out, "error": str(exc)}


# ── Generic (maigret hits, other platforms) ───────────────────────────────────

def _enrich_generic(platform: str, username: str, url: str) -> dict:
    return {
        "platform": platform,
        "username": username,
        "url":      url,
        "source":   "detection_only",
    }


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_profile(
    platform: str,
    username: str,
    url: str = "",
    **kwargs: Any,
) -> dict:
    """
    Enrich a social media profile with all available public data.

    Args:
        platform: "instagram" | "tiktok" | "linkedin" | any other string
        username: profile username (without @)
        url:      profile URL (used for linkedin / generic)

    Returns dict with enriched data. Fields present only if available:
        display_name, bio, followers, following, posts/videos, hearts,
        is_private, is_verified, profile_pic, external_url,
        source, note, error
    """
    pl = platform.lower()
    username = username.lstrip("@").strip()

    if pl == "instagram":
        return _enrich_instagram(username)
    if pl == "tiktok":
        return _enrich_tiktok(username)
    if pl == "linkedin":
        return _enrich_linkedin(username, url)
    if pl in ("github", "githubgist"):
        return _enrich_github(username, url)
    return _enrich_generic(platform, username, url)


async def enrich_profile_async(platform: str, username: str, url: str = "") -> dict:
    """Async wrapper for use from asyncio pipeline."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, enrich_profile, platform, username, url)


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json
    platform = sys.argv[1] if len(sys.argv) > 1 else "tiktok"
    username = sys.argv[2] if len(sys.argv) > 2 else "khaby.lame"
    url      = sys.argv[3] if len(sys.argv) > 3 else ""
    result   = enrich_profile(platform, username, url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
