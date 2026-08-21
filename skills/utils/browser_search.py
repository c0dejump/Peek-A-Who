"""
Real-browser Google search — for queries the lightweight engines can't do well.

DuckDuckGo / Bing (the `search.py` fallback chain) are fast and dependency-light,
but they don't honour the full set of Google dork operators (`AROUND(n)`, reliable
`inurl:`/`intitle:` ranking, `filetype:` coverage, verbatim `"…"`). For dorking we
want *actual Google*. Google has no organic API and blocks plain `requests`, so we
drive a headless browser (Chromium first, Firefox as fallback) via Selenium.

Design:
  • **One reused driver** — starting a browser costs ~2 s; a dork run fires a dozen
    queries, so the driver is a lazy module-level singleton (thread-locked) closed
    at interpreter exit. Callers never manage its lifecycle.
  • **Consent bypass** — EU users hit Google's cookie-consent wall, which hides the
    results. We seed a `CONSENT`/`SOCS` cookie on google.com before searching.
  • **Graceful absence** — if neither Selenium nor a browser is present, callers get
    an empty list and fall back to the normal engines. Never raises for that.

Returns the same `SearchResult` shape as `search.py`: {title, url, snippet, engine}.
"""
from __future__ import annotations

import atexit
import random
import threading
from urllib.parse import quote, urlparse, parse_qs

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_driver = None                 # reused Selenium WebDriver
_driver_kind = ""              # "chrome" | "firefox"
_lock = threading.Lock()
_unavailable = False           # set once if we prove no browser can start
_google_blocked = False        # set once Google serves a captcha/"sorry" wall

# markers that mean Google refused this session (headless/datacenter detection)
_BLOCK_MARKERS = ("unusual traffic", "/sorry/", "recaptcha", "captcha",
                  "our systems have detected")

# Optional UI notifier — called with a dict when a captcha needs solving. The
# pipeline wires this to its SSE event stream so a banner shows in the browser.
_captcha_notifier = None


def set_captcha_notifier(cb) -> None:
    """Register a callback(dict) invoked when Google shows a captcha."""
    global _captcha_notifier
    _captcha_notifier = cb


def _notify_captcha(info: dict) -> None:
    cb = _captcha_notifier
    if cb:
        try:
            cb(info)
        except Exception:
            pass


def _headful() -> bool:
    """Run a VISIBLE browser (so a human can solve a captcha)."""
    import os
    return os.environ.get("BROWSER_HEADFUL", "") == "1"


def _firefox_profile() -> str:
    import os
    return os.environ.get("BROWSER_FIREFOX_PROFILE", "").strip()


# ── Driver lifecycle ────────────────────────────────────────────────────────
def _build_chrome():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={_UA}")
    # Prefer a system Chromium if present (WSL/snap installs land here).
    import shutil
    for cand in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                 "/snap/bin/chromium", "/usr/bin/google-chrome"):
        if shutil.which(cand) or __import__("os").path.exists(cand):
            opts.binary_location = cand
            break
    import os as _os
    opts.add_argument(f"--user-data-dir=/tmp/paw-chrome-{_os.getpid()}")
    try:
        return webdriver.Chrome(options=opts)           # Selenium Manager resolves the driver
    except Exception:
        # explicit chromedriver (PATH, then the snap-shipped one)
        import shutil as _sh
        for drv in (_sh.which("chromedriver"), "/snap/bin/chromium.chromedriver"):
            if drv and (_sh.which(drv) or _os.path.exists(drv)):
                try:
                    return webdriver.Chrome(service=Service(drv), options=opts)
                except Exception:
                    continue
        raise


def _build_firefox():
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    opts = Options()
    if not _headful():
        opts.add_argument("--headless")
    opts.set_preference("general.useragent.override", _UA)
    # A logged-in Firefox profile carries the user's Google cookies → no captcha.
    prof = _firefox_profile()
    if prof:
        import os
        if os.path.isdir(prof):
            opts.add_argument("-profile")
            opts.add_argument(prof)
    return webdriver.Firefox(options=opts)


def _get_driver():
    """Lazily start (and cache) a browser. Firefox first when a Firefox profile is
    configured (Chromium can't reuse it), otherwise Chromium first, then Firefox."""
    global _driver, _driver_kind, _unavailable
    if _unavailable:
        return None
    if _driver is not None:
        return _driver
    order = (("firefox", _build_firefox), ("chrome", _build_chrome)) \
        if (_firefox_profile() or _headful()) else \
        (("chrome", _build_chrome), ("firefox", _build_firefox))
    for kind, builder in order:
        try:
            _driver = builder()
            _driver.set_page_load_timeout(25)
            _driver_kind = kind
            _seed_consent(_driver)
            atexit.register(_close_driver)
            return _driver
        except Exception:
            _driver = None
            continue
    _unavailable = True     # no browser could start — stop trying this process
    return None


def _seed_consent(driver) -> None:
    """Drop a consent cookie so the EU cookie wall doesn't hide search results."""
    try:
        driver.get("https://www.google.com/")
        for name, val in (("CONSENT", "YES+cb"), ("SOCS", "CAI")):
            try:
                driver.add_cookie({"name": name, "value": val, "domain": ".google.com"})
            except Exception:
                pass
    except Exception:
        pass


def _close_driver() -> None:
    global _driver
    try:
        if _driver is not None:
            _driver.quit()
    except Exception:
        pass
    finally:
        _driver = None


# ── Result parsing ──────────────────────────────────────────────────────────
def _clean_href(href: str) -> str:
    """Google sometimes wraps links as /url?q=<real>&sa=… — unwrap those."""
    if not href:
        return ""
    if href.startswith("/url?"):
        q = parse_qs(urlparse(href).query).get("q", [""])[0]
        href = q or href
    return href


def _is_organic(href: str) -> bool:
    if not href.startswith("http"):
        return False
    host = urlparse(href).netloc.lower()
    if any(bad in host for bad in ("google.", "googleadservices.", "gstatic.",
                                   "googleusercontent.com/search")):
        return False
    if "/aclk" in href or "/aclick" in href or "googleadservices" in href:
        return False
    return True


def _parse_google(html: str) -> list[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for h3 in soup.find_all("h3"):
        a = h3.find_parent("a")
        if a is None:
            # sometimes the <a> is a sibling/ancestor's first anchor
            container = h3.find_parent("div")
            a = container.find("a", href=True) if container else None
        if not a or not a.get("href"):
            continue
        href = _clean_href(a.get("href", ""))
        if not _is_organic(href):
            continue
        key = href.split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        title = h3.get_text(strip=True)
        # Best-effort snippet: nearest ancestor block holding descriptive text.
        snippet = ""
        block = a
        for _ in range(4):
            block = block.parent
            if block is None:
                break
            txt = block.get_text(" ", strip=True)
            if len(txt) > len(title) + 40:
                # strip the title prefix if present
                snippet = txt.replace(title, "", 1).strip(" ·–-—|")[:300]
                break
        out.append({"title": title, "url": href, "snippet": snippet, "engine": "google"})
    return out


# ── Public entry point ──────────────────────────────────────────────────────
def google_search(query: str, region: str = "fr-fr", num_results: int = 10,
                  timeout: int = 20) -> list[dict]:
    """
    Run one Google search in a headless browser and return organic results.
    Returns [] (never raises) when no browser is available so callers fall back.
    """
    global _google_blocked
    query = (query or "").strip()
    if not query or _google_blocked:
        # Once Google has captcha'd this session, don't keep launching the browser
        # for nothing — callers fall back to Bing/DDG immediately.
        return []
    hl = "fr" if region.startswith("fr") else "en"
    gl = "fr" if region.startswith("fr") else "us"
    url = (f"https://www.google.com/search?q={quote(query)}"
           f"&num={min(max(num_results, 10), 30)}&hl={hl}&gl={gl}&pws=0")
    with _lock:                      # one browser, one query at a time
        driver = _get_driver()
        if driver is None:
            return []
        import time as _t
        try:
            driver.get(url)
            _t.sleep(0.4 + random.random() * 0.4)   # settle late-rendered nodes
            html = driver.page_source
            probe = (html[:4000].lower() + " " + (driver.current_url or "").lower())
        except Exception:
            return []
        if any(m in probe for m in _BLOCK_MARKERS):
            # In a VISIBLE browser the user can solve the captcha — notify the UI and
            # wait for them to clear it, then re-read the results.
            if _headful():
                _notify_captcha({"message": "Google is asking for a captcha — solve it "
                                            "in the browser window that opened, then it "
                                            "continues automatically.",
                                 "query": query})
                solved_html = _wait_for_captcha_solved(driver, timeout=150)
                if solved_html:
                    html = solved_html
                else:
                    _google_blocked = True
                    return []
            else:
                _notify_captcha({"message": "Google blocked the search with a captcha. "
                                            "Set a Firefox profile (Config) to reuse your "
                                            "cookies, or enable the visible browser to "
                                            "solve it. Falling back to Bing/DDG.",
                                 "query": query, "blocked": True})
                _google_blocked = True      # give up on Google for the rest of the session
                return []
    return _parse_google(html)[:num_results]


def _wait_for_captcha_solved(driver, timeout: int = 150) -> str | None:
    """Poll the visible browser until the captcha/'sorry' page is gone. Returns the
    results HTML once solved, or None on timeout."""
    import time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        _t.sleep(2.0)
        try:
            cur = (driver.current_url or "").lower()
            html = driver.page_source
        except Exception:
            return None
        probe = html[:4000].lower() + " " + cur
        if not any(m in probe for m in _BLOCK_MARKERS) and "search?q=" in cur:
            return html
    return None


def browser_available() -> bool:
    """Cheap probe: can we start a headless browser at all? (starts it if so)."""
    return _get_driver() is not None
