"""
Playwright-based browser fallback for WAF/bot-protected pages.

Use this when direct requests.get() is blocked by:
  - Cloudflare (challenge page, 403/503)
  - Incapsula / Imperva
  - TikTok / other SPA sites requiring JS rendering
  - Any site returning suspicious redirects or empty bodies

NOT useful when the block requires authentication (e.g. LinkedIn authwall) —
in that case, load_cookies() with exported session cookies.

Usage (sync):
    from skills.utils.browser import BrowserSession
    with BrowserSession() as b:
        status, html = b.fetch("https://example.com")

Usage (async, from pipeline):
    result = await browser_fetch_async("https://example.com")

Cookie import (authenticated sessions):
    cookies = load_cookies_from_file("linkedin_cookies.json")  # Netscape or JSON format
    with BrowserSession(cookies=cookies) as b:
        status, html = b.fetch("https://www.linkedin.com/in/someone/")
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

_UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Script injected into every page to remove automation fingerprints
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['fr-FR', 'fr', 'en-US', 'en']});
window.chrome = { runtime: {} };
"""

_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-extensions",
    "--disable-gpu",
    "--window-size=1280,800",
]


def _is_waf_blocked(status: int, html: str) -> bool:
    """Heuristic: did a WAF intercept the response instead of the real page?"""
    if status in (403, 503, 429, 999):
        return True
    low = html[:3000].lower()
    signals = [
        "checking your browser",
        "ddos protection",
        "cloudflare",
        "incapsula incident",
        "ray id",
        "just a moment",
    ]
    return any(s in low for s in signals)


class BrowserSession:
    """
    Context-manager wrapping a Playwright Chromium browser.

    Lazy-initialises on first fetch(); closes on __exit__.
    Thread-safe only for sequential use within the same thread.
    """

    def __init__(
        self,
        headless: bool = True,
        locale: str = "fr-FR",
        cookies: list[dict] | None = None,
        user_data_dir: str | None = None,
    ):
        self._headless = headless
        self._locale = locale
        self._cookies = cookies or []
        self._user_data_dir = user_data_dir
        self._pw = None
        self._browser = None
        self._ctx = None

    def _start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=_LAUNCH_ARGS,
        )
        ctx_kwargs: dict = {
            "user_agent": _UA_CHROME,
            "locale": self._locale,
            "viewport": {"width": 1280, "height": 800},
            "accept_downloads": False,
        }
        self._ctx = self._browser.new_context(**ctx_kwargs)
        self._ctx.add_init_script(_STEALTH_JS)
        if self._cookies:
            self._ctx.add_cookies(self._cookies)

    def __enter__(self) -> "BrowserSession":
        self._start()
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        try:
            if self._ctx:
                self._ctx.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._browser = self._pw = None

    def fetch(
        self,
        url: str,
        wait: str = "domcontentloaded",
        networkidle_timeout: int = 6000,
        page_timeout: int = 20000,
    ) -> tuple[int, str]:
        """
        Navigate to url, return (http_status, page_html).

        wait: 'load' | 'domcontentloaded' | 'networkidle'
        networkidle_timeout: extra ms to wait for networkidle after initial load
        """
        if self._browser is None:
            self._start()

        page = self._ctx.new_page()
        try:
            resp = page.goto(url, wait_until=wait, timeout=page_timeout)
            status = resp.status if resp else 0

            # Wait for JS-rendered content to settle
            if networkidle_timeout:
                try:
                    page.wait_for_load_state("networkidle", timeout=networkidle_timeout)
                except Exception:
                    pass  # timeout is fine — we still grab whatever rendered

            html = page.content()
            return status, html
        finally:
            page.close()

    def fetch_text(self, url: str, **kwargs) -> tuple[int, str]:
        """Alias for fetch() — same return value."""
        return self.fetch(url, **kwargs)

    def load_cookies(self, cookies: list[dict]) -> None:
        """Add cookies to the current context (e.g. exported LinkedIn session)."""
        if self._ctx:
            self._ctx.add_cookies(cookies)
        else:
            self._cookies.extend(cookies)


# ── Cookie helpers ────────────────────────────────────────────────────────────

def load_cookies_from_file(path: str) -> list[dict]:
    """
    Load cookies from a JSON file (EditThisCookie / Cookie-Editor format).

    Each cookie dict must have at minimum: name, value, domain.
    Optional: path, expires, httpOnly, secure, sameSite.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Cookie file not found: {path}")

    raw = json.loads(p.read_text())
    if not isinstance(raw, list):
        raise ValueError("Expected a JSON array of cookie objects")

    # Normalise to Playwright format
    cleaned: list[dict] = []
    for c in raw:
        entry: dict = {
            "name":   c.get("name", ""),
            "value":  c.get("value", ""),
            "domain": c.get("domain", ""),
            "path":   c.get("path", "/"),
        }
        if c.get("expirationDate") or c.get("expires"):
            entry["expires"] = int(c.get("expirationDate") or c.get("expires") or -1)
        if "httpOnly" in c:
            entry["httpOnly"] = bool(c["httpOnly"])
        if "secure" in c:
            entry["secure"] = bool(c["secure"])
        cleaned.append(entry)
    return cleaned


# ── Async wrapper (for use from asyncio pipeline) ────────────────────────────

async def browser_fetch_async(
    url: str,
    cookies: list[dict] | None = None,
    headless: bool = True,
    locale: str = "fr-FR",
    networkidle_timeout: int = 6000,
) -> tuple[int, str]:
    """
    Async-friendly: runs Playwright in a thread-pool executor.
    Returns (status, html).
    """
    import asyncio

    def _run():
        with BrowserSession(headless=headless, locale=locale, cookies=cookies) as b:
            return b.fetch(url, networkidle_timeout=networkidle_timeout)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run)


# ── WAF-aware requests wrapper ────────────────────────────────────────────────

def smart_get(
    url: str,
    headers: dict | None = None,
    timeout: int = 12,
    browser_fallback: bool = True,
    cookies: list[dict] | None = None,
) -> tuple[int, str]:
    """
    Try requests.get() first; if WAF-blocked, fall back to Playwright.

    Returns (status_code, html_body).
    """
    import requests as _req

    sess = _req.Session()
    sess.headers.update({
        "User-Agent": _UA_CHROME,
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })
    if headers:
        sess.headers.update(headers)

    try:
        r = sess.get(url, timeout=timeout, allow_redirects=True)
        if not browser_fallback or not _is_waf_blocked(r.status_code, r.text):
            return r.status_code, r.text
    except Exception:
        if not browser_fallback:
            raise

    # Fallback: full browser
    with BrowserSession(cookies=cookies) as b:
        return b.fetch(url)


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://forebears.io/fr/surnames/dupont"
    print(f"Fetching {url} via BrowserSession …")
    with BrowserSession() as b:
        status, html = b.fetch(url)
    print(f"Status: {status}  |  HTML length: {len(html)}")
    # Print first non-whitespace block
    for line in html.split("\n"):
        stripped = line.strip()
        if len(stripped) > 40:
            print("Sample:", stripped[:120])
            break
