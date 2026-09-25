"""Browser backend — snapshot-based fetching via Camofox or Playwright.

Handles what direct HTTP can't: X Lists, X Articles, browser-rendered
Nitter pages, and Google-search mentions. Driver selection:

  XTF_BROWSER=camofox     (default) talk to Camofox on localhost:9377
  XTF_BROWSER=playwright  drive bundled Chromium via Playwright

Both drivers expose the same functions (check_camofox / camofox_fetch_page /
camofox_search), so this backend is driver-agnostic.
"""
from __future__ import annotations

import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional

from .. import config
from ..exceptions import BackendUnavailable, UpstreamDown
from ..i18n import t
from ..models import Article, Reply, Tweet
from ..parsers.snapshot import (
    extract_next_cursor,
    parse_article_snapshot,
    parse_replies_snapshot,
    parse_timeline_snapshot,
)
from .base import Backend

# local patch (X-Tiller): cap recursive nested-reply expansion. Each level costs
# one browser page fetch, so an unbounded loop over reply counts is a footgun.
MAX_REPLY_RECURSION = 20


def _load_driver(name: Optional[str] = None):
    """Import the requested driver module. Raises BackendUnavailable."""
    name = name or config.browser_driver()
    if name == "playwright":
        try:
            from . import _playwright_driver as drv
            return drv
        except ImportError as e:
            raise BackendUnavailable(
                f"Playwright not installed (pip install playwright): {e}"
            ) from e
    from . import _camofox_driver as drv
    return drv


class BrowserBackend(Backend):
    name = "browser"

    def __init__(self, driver: Optional[str] = None, port: Optional[int] = None,
                 nitter_instance: Optional[str] = None,
                 timeout: Optional[int] = None):
        self.driver_name = driver or config.browser_driver()
        self.port = port or config.browser_port()
        # local patch (X-Tiller): page-wait budget threaded from --timeout.
        self.page_wait = 8.0 if timeout is None else float(max(1, timeout))
        # Nitter host used for browser-rendered pages (first configured instance)
        inst = nitter_instance or config.nitter_instances()[0]
        self.nitter_host = inst.split("://", 1)[-1].rstrip("/")
        # local patch (X-Tiller): CLI-overridable nested-reply expansion cap.
        self.max_reply_recursion = MAX_REPLY_RECURSION
        self._drv = None

    @property
    def drv(self):
        if self._drv is None:
            self._drv = _load_driver(self.driver_name)
        return self._drv

    def available(self) -> bool:
        try:
            return bool(self.drv.check_camofox(self.port))
        except BackendUnavailable:
            return False

    def _require(self, err_key: str) -> None:
        if not self.drv.check_camofox(self.port):
            raise BackendUnavailable(t(err_key, port=self.port))

    def _fetch_page(self, url: str, session_key: str, wait: Optional[float] = None) -> str:
        # local patch (X-Tiller): default wait now comes from --timeout.
        if wait is None:
            wait = self.page_wait
        snapshot = self.drv.camofox_fetch_page(url, session_key=session_key,
                                               wait=wait, port=self.port)
        if not snapshot:
            raise UpstreamDown(t("err_snapshot_failed"))
        return snapshot

    # ── paginated timeline core (shared by user timeline and lists) ──────
    def _paged_timeline(self, base_url: str, session_prefix: str,
                        limit: int, max_pages: int) -> tuple[List[Dict], int]:
        tweets: List[Dict] = []
        cursor: Optional[str] = None
        page = 1
        while len(tweets) < limit and page <= max_pages:
            if cursor:
                encoded = urllib.parse.quote(cursor, safe="")
                url = f"{base_url}?cursor={encoded}"
            else:
                url = base_url
            print(f"[x-tweet-fetcher] page {page}/{max_pages} — {url}", file=sys.stderr)

            try:
                snapshot = self._fetch_page(url, f"{session_prefix}-p{page}")
            except UpstreamDown:
                if page == 1:
                    raise
                print(f"[x-tweet-fetcher] page {page} snapshot failed, stopping", file=sys.stderr)
                break

            remaining = limit - len(tweets)
            new_tweets = parse_timeline_snapshot(snapshot, limit=remaining)

            seen = {(tw["author"], tw["text"][:80]) for tw in tweets}
            for tw in new_tweets:
                key = (tw["author"], tw["text"][:80])
                if key not in seen:
                    tweets.append(tw)
                    seen.add(key)

            print(f"[x-tweet-fetcher] page {page}: +{len(new_tweets)}, total {len(tweets)}",
                  file=sys.stderr)

            if len(new_tweets) == 0:
                break
            cursor = extract_next_cursor(snapshot)
            if not cursor:
                break
            page += 1
            if len(tweets) < limit:
                time.sleep(2)
        return tweets, page

    # ── capabilities ─────────────────────────────────────────────────────
    def fetch_timeline(self, username: str, limit: int = 20) -> List[Tweet]:
        self._require("err_camofox_not_running_user")
        raw, _pages = self._paged_timeline(
            f"https://{self.nitter_host}/{username}",
            f"timeline-{username}", limit, max_pages=6,
        )
        return [Tweet.from_snapshot_entry(tw) for tw in raw]

    def fetch_list(self, list_id: str, limit: int = 20) -> List[Tweet]:
        self._require("err_camofox_not_running_list")
        raw, _pages = self._paged_timeline(
            f"https://{self.nitter_host}/i/lists/{list_id}",
            f"list-{list_id}", limit, max_pages=10,
        )
        return [Tweet.from_snapshot_entry(tw) for tw in raw]

    def fetch_replies(self, username: str, tweet_id: str,
                      recurse_nested: bool = True,
                      max_recursion: Optional[int] = None) -> List[Reply]:
        if max_recursion is None:
            max_recursion = self.max_reply_recursion
        self._require("err_camofox_not_running_replies")
        nitter_url = f"https://{self.nitter_host}/{username}/status/{tweet_id}"
        print(t("opening_via_camofox", url=nitter_url), file=sys.stderr)

        snapshot = self._fetch_page(nitter_url, f"replies-{tweet_id}")
        raw = parse_replies_snapshot(snapshot, original_author=username)

        if recurse_nested:
            # local patch (X-Tiller): bounded by max_recursion (flag on the CLI).
            expanded = 0
            for reply in raw:
                if expanded >= max_recursion:
                    print(
                        f"[x-tweet-fetcher] nested-reply expansion capped at "
                        f"{max_recursion}",
                        file=sys.stderr,
                    )
                    break
                if reply.get("replies", 0) > 0 and reply.get("tweet_id"):
                    r_author = reply["author"].lstrip("@")
                    r_tid = reply["tweet_id"]
                    nested_url = f"https://{self.nitter_host}/{r_author}/status/{r_tid}"
                    print(f"[x-tweet-fetcher] nested replies: {r_author}/status/{r_tid}",
                          file=sys.stderr)
                    try:
                        nested_snap = self._fetch_page(nested_url, f"nested-{r_tid}")
                    except UpstreamDown:
                        continue
                    expanded += 1
                    nested = parse_replies_snapshot(nested_snap, original_author=r_author)
                    if nested:
                        reply["thread_replies"] = nested

        return [Reply.from_snapshot_entry(r) for r in raw]

    def fetch_article(self, article_id: str) -> Article:
        self._require("err_camofox_not_running_article")
        article_url = f"https://x.com/i/article/{article_id}"
        print(t("opening_article_via_camofox", url=article_url), file=sys.stderr)

        # X Articles are JS-heavy; longer wait
        snapshot = self._fetch_page(article_url, f"article-{article_id}",
                                    wait=max(self.page_wait, 10))
        parsed = parse_article_snapshot(snapshot)
        return Article(
            article_id=article_id,
            url=article_url,
            title=parsed["title"],
            author=parsed["author"],
            author_handle=parsed["author_handle"],
            content=parsed["content"],
            paragraphs=parsed["paragraphs"],
            word_count=parsed["word_count"],
            char_count=parsed["char_count"],
            is_partial=parsed["is_partial"],
        )

    # ── mentions search (Google via browser) ─────────────────────────────
    def search_mentions(self, username: str, limit: int = 10) -> List[Dict[str, Any]]:
        clean = username.lstrip("@")
        queries = [f"site:x.com @{clean}", f"site:x.com {clean}"]
        seen_urls: set = set()
        results: List[Dict[str, Any]] = []
        for query in queries:
            print(t("monitor_searching", query=query), file=sys.stderr)
            raw = self.drv.camofox_search(query, num=limit, port=self.port)
            for item in raw:
                url = item.get("url", "").strip()
                if url and url not in seen_urls and "x.com" in url:
                    seen_urls.add(url)
                    results.append({
                        "url": url,
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                    })
        return results
