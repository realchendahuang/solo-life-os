#!/usr/bin/env python3
"""
Playwright Client - Drop-in replacement for camofox_client.py.

Provides the same public interface as camofox_client but uses Playwright
(Chromium) instead of the Camofox REST API.

Public interface (mirrors camofox_client.py):
  check_camofox(port)            → always True (Playwright needs no server)
  camofox_open_tab(url, ...)     → returns fake tab_id, fetches page
  camofox_snapshot(tab_id, ...)  → returns stored page text
  camofox_close_tab(tab_id, ...) → frees stored page text
  camofox_fetch_page(url, ...)   → open URL, wait, return text content
  camofox_search(query, ...)     → search via Google/DDG, return results list

Additional high-level helpers for Nitter:
  playwright_fetch_nitter_timeline(username, cursor, wait) → List[Dict]
  playwright_fetch_nitter_replies(username, tweet_id, wait) → List[Dict]
  playwright_get_nitter_cursor(username_or_url, wait)      → str | None
"""

import os
import sys
import time
import secrets
import urllib.parse
from typing import Optional

# ---------------------------------------------------------------------------
# Chromium executable path
# ---------------------------------------------------------------------------
_CHROMIUM_EXEC_ENV = "PLAYWRIGHT_CHROMIUM_EXEC"


def _resolve_chromium_executable(browser_type) -> Optional[str]:
    """Return a Chromium executable path, preferring a valid env override."""
    env_path = os.environ.get(_CHROMIUM_EXEC_ENV)
    if env_path:
        if os.path.exists(env_path):
            return env_path
        print(
            f"[playwright_client] {_CHROMIUM_EXEC_ENV} does not exist: {env_path}; "
            "using Playwright bundled Chromium",
            file=sys.stderr,
        )

    executable_path = getattr(browser_type, "executable_path", None)
    return executable_path if executable_path and os.path.exists(executable_path) else None

# Default working Nitter instance (nitter.net is down; tiekoetter is live)
# Nitter fallback chain: tested 2026-03-22, only these 3 are alive
NITTER_INSTANCES = [
    "nitter.tiekoetter.com",   # 🇩🇪 fastest, curl+Playwright both work
    "xcancel.com",             # 🇺🇸 403 to curl but Playwright works
    "nitter.catsarch.com",     # 🇺🇸/🇩🇪 same as above
]
DEFAULT_NITTER = os.environ.get("NITTER_INSTANCE", NITTER_INSTANCES[0])

# ---------------------------------------------------------------------------
# Fake tab registry  (camofox_open_tab / camofox_snapshot compatibility)
# ---------------------------------------------------------------------------
_tab_store: dict = {}   # tab_id → page text


# ---------------------------------------------------------------------------
# Internal browser helpers
# ---------------------------------------------------------------------------

def _launch_browser():
    """Return a (playwright, browser) pair.  Caller must close both."""
    from playwright.sync_api import sync_playwright  # lazy import
    pw = sync_playwright().start()
    launch_options = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    executable_path = _resolve_chromium_executable(pw.chromium)
    if executable_path:
        launch_options["executable_path"] = executable_path
    browser = pw.chromium.launch(**launch_options)
    return pw, browser


def _new_context(browser, lang: str = "zh-CN"):
    return browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale=lang,
        viewport={"width": 1280, "height": 900},
    )


def _safe_goto(page, url: str, timeout: int = 30000):
    """Navigate to url, tolerating timeout errors."""
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception:
        pass  # partial load is fine for JS-heavy pages


def _page_text(page) -> str:
    """Return inner_text of <body>."""
    try:
        return page.inner_text("body", timeout=5000) or ""
    except Exception:
        pass
    try:
        return page.content()
    except Exception:
        return ""


def _fetch_url_text(url: str, wait: float = 8) -> Optional[str]:
    """Fetch *url* with Playwright, return visible text.  None on failure."""
    pw = browser = None
    try:
        pw, browser = _launch_browser()
        ctx = _new_context(browser)
        page = ctx.new_page()
        _safe_goto(page, url)
        time.sleep(wait)
        text = _page_text(page)
        ctx.close()
        return text or None
    except Exception as e:
        print(f"[playwright_client] fetch error {url[:80]}: {e}", file=sys.stderr)
        return None
    finally:
        try:
            browser and browser.close()
        except Exception:
            pass
        try:
            pw and pw.stop()
        except Exception:
            pass


def check_camofox(port: int = 9377) -> bool:
    """Always returns True – Playwright needs no separate server."""
    return True


def camofox_open_tab(url: str, session_key: str, port: int = 9377) -> Optional[str]:
    """Fetch *url* and store the text; return a synthetic tab_id."""
    if not url.startswith(("http://", "https://")):
        print(f"[playwright_client] rejected non-HTTP URL: {url[:60]}", file=sys.stderr)
        return None
    text = _fetch_url_text(url, wait=8)
    if text is None:
        return None
    tab_id = f"pw-{session_key}-{secrets.token_hex(4)}"
    _tab_store[tab_id] = text
    return tab_id


def camofox_snapshot(tab_id: str, port: int = 9377) -> Optional[str]:
    """Return stored text for *tab_id*."""
    return _tab_store.get(tab_id)


def camofox_close_tab(tab_id: str, port: int = 9377):
    """Free the stored page text."""
    _tab_store.pop(tab_id, None)


def camofox_fetch_page(url: str, session_key: str, wait: float = 8, port: int = 9377) -> Optional[str]:
    """Fetch *url* via Playwright; return visible text.  Primary entry point."""
    return _fetch_url_text(url, wait=wait)


# ---------------------------------------------------------------------------
# Search (Google / DuckDuckGo)
# ---------------------------------------------------------------------------

def camofox_search(
    query: str,
    num: int = 10,
    lang: str = "zh-CN",
    engine: str = "google",
    port: int = 9377,
) -> list:
    """
    Search via Playwright (Google or DuckDuckGo).

    Returns [{"title": ..., "url": ..., "snippet": ...}, ...]
    """
    encoded = urllib.parse.quote(query)
    pw = browser = None
    results = []

    try:
        pw, browser = _launch_browser()
        ctx = _new_context(browser, lang=lang)
        page = ctx.new_page()

        if engine == "duckduckgo":
            search_url = f"https://duckduckgo.com/?q={encoded}&kl={lang}&t=h_"
            _safe_goto(page, search_url)
            time.sleep(5)
            results = _extract_ddg_results(page, num)
        else:
            search_url = f"https://www.google.com/search?q={encoded}&hl={lang}&num={num}"
            _safe_goto(page, search_url)
            time.sleep(4)
            results = _extract_google_results(page, num)

        ctx.close()
    except Exception as e:
        print(f"[playwright_client] search error: {e}", file=sys.stderr)
    finally:
        try:
            browser and browser.close()
        except Exception:
            pass
        try:
            pw and pw.stop()
        except Exception:
            pass

    return results


def _extract_google_results(page, max_results: int = 10) -> list:
    results = []
    try:
        items = page.query_selector_all("div.g")
        if not items:
            items = page.query_selector_all("div[data-hveid]")
        for item in items:
            if len(results) >= max_results:
                break
            try:
                title_el = item.query_selector("h3")
                title = title_el.inner_text().strip() if title_el else ""
                link_el = item.query_selector("a[href]")
                href = link_el.get_attribute("href") if link_el else ""
                url = href if href and href.startswith("http") else ""
                snippet = ""
                for sel in ["div[data-sncf='1']", "div.IsZvec", "span.aCOpRe",
                             "div[style*='-webkit-line-clamp']"]:
                    sn_el = item.query_selector(sel)
                    if sn_el:
                        snippet = sn_el.inner_text().strip()
                        break
                if not snippet:
                    all_text = item.inner_text().strip()
                    snippet = all_text.replace(title, "").strip()[:200]
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})
            except Exception:
                continue
    except Exception as e:
        print(f"[playwright_client] google parse: {e}", file=sys.stderr)
    return results


def _extract_ddg_results(page, max_results: int = 10) -> list:
    results = []
    try:
        items = page.query_selector_all("article[data-testid='result']")
        if not items:
            items = page.query_selector_all("li.PartialSearchResults-item")
        for item in items:
            if len(results) >= max_results:
                break
            try:
                title_el = item.query_selector("h2") or item.query_selector("h3")
                title = title_el.inner_text().strip() if title_el else ""
                link_el = item.query_selector("a[href]")
                href = link_el.get_attribute("href") if link_el else ""
                url = href if href and href.startswith("http") else ""
                snippet_el = (item.query_selector("div[data-result='snippet']") or
                              item.query_selector("span.result__snippet"))
                snippet = snippet_el.inner_text().strip() if snippet_el else ""
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})
            except Exception:
                continue
    except Exception as e:
        print(f"[playwright_client] ddg parse: {e}", file=sys.stderr)
    return results


# Legacy snapshot-based stubs (kept for import compatibility)
def _parse_duckduckgo_results(snapshot: str, max_results: int = 10) -> list:
    return []


def _parse_google_results(snapshot: str) -> list:
    return []


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys
    engine = "google"
    args = _sys.argv[1:]
    if "--engine" in args:
        idx = args.index("--engine")
        if idx + 1 < len(args):
            engine = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            args = args[:idx]
    query = " ".join(args) if args else "AI Agent"
    print(f"Searching ({engine}): {query}", file=_sys.stderr)
    results = camofox_search(query, engine=engine)
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['title']}")
        print(f"   {r['url']}")
        print(f"   {r['snippet'][:100]}...")
