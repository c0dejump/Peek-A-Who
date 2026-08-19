"""
Robust multi-engine web search core.

A single, resilient entry point (`web_search`) used everywhere PAW needs to
query a search engine — Watson's `web_search` tool, the SMTP SERP check, the
LinkedIn candidate finder, etc.

Design goals:
  • **Fallback chain** — DuckDuckGo HTML → DuckDuckGo Lite → Bing. If one
    engine is blocked, rate-limited, or returns nothing, the next is tried.
  • **Clean results** — DuckDuckGo redirect links (`//duckduckgo.com/l/?uddg=…`)
    are decoded, every result carries a parsed `domain`, and duplicates
    (same normalised URL) are dropped.
  • **Retry + backoff** — transient failures are retried with jitter.
  • **In-process TTL cache** — identical queries within `_CACHE_TTL` seconds
    reuse the previous result instead of re-hitting the network (kinder to the
    target engines and much faster for Watson's tool loop).

Everything is synchronous and dependency-light (requests + BeautifulSoup).
"""
from __future__ import annotations

import random
import re
import time
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

__all__ = ["web_search", "SearchResult", "clear_cache"]

SearchResult = dict[str, str]  # {title, url, snippet, domain, engine}

# ── User-Agent rotation ────────────────────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _headers(region: str) -> dict:
    lang = "fr-FR,fr;q=0.9,en;q=0.8" if region.startswith("fr") else "en-US,en;q=0.9"
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": lang,
    }


# ── URL helpers ────────────────────────────────────────────────────────────
def _decode_ddg(href: str) -> str:
    """DuckDuckGo wraps outbound links as //duckduckgo.com/l/?uddg=<enc>."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href:
        q = parse_qs(urlparse(href).query)
        if "uddg" in q:
            return unquote(q["uddg"][0])
    return href


def _decode_bing(href: str) -> str:
    """Bing wraps outbound links as /ck/a?...&u=a1<base64url-encoded-url>."""
    if not href or "bing.com/ck/" not in href:
        return href
    import base64
    q = parse_qs(urlparse(href).query)
    u = q.get("u", [""])[0]
    if u.startswith("a1"):
        u = u[2:]
    try:
        pad = "=" * (-len(u) % 4)
        return base64.urlsafe_b64decode(u + pad).decode("utf-8", "replace")
    except Exception:
        return href


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _norm_key(url: str) -> str:
    """Normalise a URL for dedup: drop scheme, www, trailing slash, query."""
    u = re.sub(r"^https?://", "", url.lower())
    u = re.sub(r"^www\.", "", u)
    u = u.split("?", 1)[0].split("#", 1)[0]
    return u.rstrip("/")


# ── Engine parsers ─────────────────────────────────────────────────────────
def _parse_ddg_html(html: str) -> list[SearchResult]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out: list[SearchResult] = []
    for el in soup.select(".result, .web-result"):
        a = el.select_one(".result__title a, .result__a")
        if not a:
            continue
        url = _decode_ddg(a.get("href", ""))
        if not url.startswith("http"):
            continue
        snip = el.select_one(".result__snippet")
        out.append({
            "title":   a.get_text(strip=True),
            "url":     url,
            "snippet": snip.get_text(strip=True) if snip else "",
            "engine":  "ddg",
        })
    return out


def _parse_ddg_lite(html: str) -> list[SearchResult]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out: list[SearchResult] = []
    links = soup.select("a.result-link")
    snippets = soup.select("td.result-snippet")
    for i, a in enumerate(links):
        url = _decode_ddg(a.get("href", ""))
        if not url.startswith("http"):
            continue
        snip = snippets[i].get_text(strip=True) if i < len(snippets) else ""
        out.append({
            "title":   a.get_text(strip=True),
            "url":     url,
            "snippet": snip,
            "engine":  "ddg-lite",
        })
    return out


def _parse_bing(html: str) -> list[SearchResult]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out: list[SearchResult] = []
    for li in soup.select("#b_results .b_algo"):
        a = li.select_one("h2 a")
        if not a:
            continue
        url = _decode_bing(a.get("href", ""))
        if not url.startswith("http"):
            continue
        cap = li.select_one(".b_caption p, .b_algoSlug")
        out.append({
            "title":   a.get_text(strip=True),
            "url":     url,
            "snippet": cap.get_text(strip=True) if cap else "",
            "engine":  "bing",
        })
    return out


# ── Engine fetchers (query → raw results) ──────────────────────────────────
def _fetch_engine(engine: str, query: str, region: str, timeout: int) -> list[SearchResult]:
    import requests
    if engine == "ddg":
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query, "kl": region}
        parser = _parse_ddg_html
    elif engine == "ddg-lite":
        url = "https://lite.duckduckgo.com/lite/"
        params = {"q": query, "kl": region}
        parser = _parse_ddg_lite
    elif engine == "bing":
        url = f"https://www.bing.com/search?q={quote(query)}"
        params = {"setlang": "fr" if region.startswith("fr") else "en"}
        parser = _parse_bing
    else:
        return []

    r = requests.get(url, params=params, headers=_headers(region), timeout=timeout)
    if r.status_code != 200:
        return []
    return parser(r.text)


# ── In-process TTL cache ───────────────────────────────────────────────────
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL = 900        # 15 minutes
_CACHE_MAX = 256


def clear_cache() -> None:
    _CACHE.clear()


def _cache_get(key: tuple) -> dict | None:
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.monotonic() - ts > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return val


def _cache_put(key: tuple, val: dict) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # drop the oldest entry
        oldest = min(_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _CACHE.pop(oldest, None)
    _CACHE[key] = (time.monotonic(), val)


# ── Public API ─────────────────────────────────────────────────────────────
_ENGINE_ORDER = ["ddg", "ddg-lite", "bing"]


def web_search(
    query: str,
    num_results: int = 8,
    region: str = "fr-fr",
    timeout: int = 12,
    engines: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Run a resilient web search across a fallback chain of engines.

    Returns:
        {
          "query": str,
          "results": [{title, url, snippet, domain, engine}],
          "total_found": int,
          "engine_used": str,      # first engine that produced results
          "engines_tried": [str],
          "error": str,            # only when *every* engine failed
        }
    """
    query = (query or "").strip()
    if not query:
        return {"query": query, "results": [], "total_found": 0, "error": "empty query"}

    num_results = min(max(int(num_results), 1), 25)
    order = engines or _ENGINE_ORDER
    key = (query, num_results, region, tuple(order))

    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return {**cached, "cached": True}

    tried: list[str] = []
    last_error = ""

    for engine in order:
        tried.append(engine)
        raw: list[SearchResult] = []
        # up to 2 attempts per engine with jittered backoff
        for attempt in range(2):
            try:
                raw = _fetch_engine(engine, query, region, timeout)
                if raw:
                    break
            except Exception as exc:
                last_error = f"{engine}: {exc}"
            if attempt == 0:
                time.sleep(0.4 + random.random() * 0.6)

        if not raw:
            continue

        # dedup + enrich + trim
        seen: set[str] = set()
        results: list[SearchResult] = []
        for item in raw:
            k = _norm_key(item["url"])
            if not k or k in seen:
                continue
            seen.add(k)
            item["domain"] = _domain(item["url"])
            results.append(item)
            if len(results) >= num_results:
                break

        if results:
            out = {
                "query":         query,
                "results":       results,
                "total_found":   len(results),
                "engine_used":   engine,
                "engines_tried": tried,
            }
            if use_cache:
                _cache_put(key, out)
            return out

    return {
        "query":         query,
        "results":       [],
        "total_found":   0,
        "engine_used":   "",
        "engines_tried": tried,
        "error":         last_error or "all engines returned no results",
    }
