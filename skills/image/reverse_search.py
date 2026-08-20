"""
Reverse image search — the single biggest OSINT primitive that PAW was missing.

Given an image URL (a profile photo, a found picture…), it:
  • builds ready-to-open reverse-search links for the engines that matter for
    people/faces — Yandex (best for faces), Google Lens, Bing Visual Search,
    TinEye — which always work regardless of anti-bot measures, and
  • makes a best-effort scrape of Yandex/Bing for "pages that contain this
    image" (domains + titles), degrading gracefully when blocked.

No API key needed. For faces, Yandex is by far the strongest free engine.
"""
from __future__ import annotations

from urllib.parse import quote, urlparse

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def build_search_links(image_url: str) -> dict[str, str]:
    """Ready-to-open reverse-image-search URLs for the major engines."""
    u = quote(image_url, safe="")
    return {
        "yandex":      f"https://yandex.com/images/search?rpt=imageview&url={u}",
        "google_lens": f"https://lens.google.com/uploadbyurl?url={u}",
        "bing":        f"https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{u}",
        "tineye":      f"https://tineye.com/search?url={u}",
    }


def _domain(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _scrape_yandex(image_url: str, timeout: int) -> list[dict]:
    """Best-effort: 'sites that contain this image' from Yandex. Fragile by design."""
    import re
    import requests
    out: list[dict] = []
    try:
        r = requests.get(
            "https://yandex.com/images/search",
            params={"rpt": "imageview", "url": image_url, "cbir_page": "sites"},
            headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return out
        seen: set[str] = set()
        # Yandex embeds outbound links + titles in the markup; grab href/title pairs
        for m in re.finditer(r'href="(https?://[^"]+)"[^>]*>([^<]{4,120})<', r.text):
            url, title = m.group(1), m.group(2).strip()
            d = _domain(url)
            if not d or d.endswith("yandex.com") or d.endswith("yandex.net") or d in seen:
                continue
            seen.add(d)
            out.append({"title": title, "url": url, "domain": d, "engine": "yandex"})
            if len(out) >= 12:
                break
    except Exception:
        pass
    return out


def run_sync(image_url: str, scrape: bool = True, timeout: int = 12) -> dict:
    """
    Reverse-search an image URL.

    Returns:
        {
          "image_url": str,
          "search_links": {yandex, google_lens, bing, tineye},
          "matches": [{title, url, domain, engine}],   # best-effort, may be empty
          "note": str,
        }
    """
    image_url = (image_url or "").strip()
    if not image_url.startswith("http"):
        return {"error": "Provide a public image URL (http/https)."}

    links = build_search_links(image_url)
    matches: list[dict] = _scrape_yandex(image_url, timeout) if scrape else []

    note = ("Open the engine links to review matches visually — Yandex is the "
            "strongest for faces. Automated matches below are best-effort and "
            "often incomplete due to anti-bot measures.")
    return {
        "image_url":    image_url,
        "search_links": links,
        "matches":      matches,
        "match_count":  len(matches),
        "note":         note,
    }
