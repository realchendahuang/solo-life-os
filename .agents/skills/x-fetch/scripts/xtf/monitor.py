"""Incremental mentions monitor (--monitor mode). Cron-friendly.

First run establishes a baseline; later runs report only new URLs.
Cache lives in ``XTF_CACHE_DIR`` (default ~/.x-tweet-fetcher).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from . import config
from .exceptions import XtfError
from .i18n import t

_CACHE_MAX = 500


def _get_cache_path(username: str) -> Path:
    clean = username.lstrip("@").lower()
    return config.cache_dir() / f"mentions-cache-{clean}.json"


def _quarantine_cache(path: Path, reason: str) -> None:
    """local patch (X-Tiller): never silently reset the baseline.

    A corrupted cache is renamed to ``*.bad`` and announced, so previously
    reported mentions cannot be re-reported as new because of a parse error.
    """
    bad = path.with_name(path.name + ".bad")
    try:
        if bad.exists():
            bad = path.with_name(path.name + f".bad-{int(time.time())}")
        path.rename(bad)
        print(
            f"[monitor] cache {path} is {reason}; moved to {bad.name} "
            "and starting a fresh baseline",
            file=sys.stderr,
        )
    except OSError as exc:
        print(
            f"[monitor] cache {path} is {reason} and could not be quarantined "
            f"({exc}); starting a fresh baseline",
            file=sys.stderr,
        )


def _load_cache(username: str) -> dict:
    """Return a validated cache. Corrupt/invalid caches are quarantined."""
    path = _get_cache_path(username)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _quarantine_cache(path, f"unreadable ({type(exc).__name__})")
            return {"seen": [], "is_baseline": True}
        if isinstance(data, list):  # v1 legacy format (bare list)
            if all(isinstance(item, str) for item in data):
                return {"seen": list(data), "is_baseline": False}
            _quarantine_cache(path, "legacy list with non-string entries")
            return {"seen": [], "is_baseline": True}
        if not isinstance(data, dict) or not isinstance(data.get("seen"), list) \
                or not all(isinstance(item, str) for item in data["seen"]):
            _quarantine_cache(path, "missing a valid 'seen' string array")
            return {"seen": [], "is_baseline": True}
        return data
    return {"seen": [], "is_baseline": True}


def _save_cache(username: str, cache: dict) -> None:
    config.cache_dir().mkdir(parents=True, exist_ok=True)
    if len(cache["seen"]) > _CACHE_MAX:
        cache["seen"] = cache["seen"][-_CACHE_MAX:]
    with open(_get_cache_path(username), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _search_mentions_nitter(nitter_backend, username: str, limit: int) -> List[Dict]:
    clean = username.lstrip("@")
    tweets = nitter_backend.search(f"@{clean}", limit=limit)
    results = []
    for tw in tweets:
        handle = tw.author.lstrip("@")
        results.append({
            "url": f"https://x.com/{handle}/status/{tw.tweet_id}" if tw.tweet_id else "",
            "title": f"@{handle}: {tw.text[:80]}",
            "snippet": tw.text,
            "username": handle,
            "tweet_id": tw.tweet_id,
        })
    return [r for r in results if r["url"]]


def monitor_mentions(router, username: str, limit: int = 10,
                     use_nitter: bool = False) -> Dict[str, Any]:
    """Run one monitor cycle. Returns v1-compatible result dict."""
    result: Dict[str, Any] = {
        "username": username.lstrip("@"),
        "new_mentions": [],
        "is_baseline": False,
        "known_count": 0,
    }

    cache = _load_cache(username)
    # local patch (X-Tiller): .get guards a cache dict that lost its "seen" key.
    cache.setdefault("seen", [])
    cache.setdefault("is_baseline", False)
    seen_set = set(cache["seen"])
    result["known_count"] = len(seen_set)

    try:
        if use_nitter:
            all_results = _search_mentions_nitter(router.nitter, username, limit)
        else:
            if not router.browser.available():
                result["error"] = t("monitor_camofox_error", port=router.browser.port)
                return result
            all_results = router.browser.search_mentions(username, limit=limit)
    except XtfError as e:
        result["error"] = str(e)
        return result

    if cache["is_baseline"]:
        new_urls = [r["url"] for r in all_results]
        cache["seen"] = list(seen_set | set(new_urls))
        cache["is_baseline"] = False
        _save_cache(username, cache)
        result["is_baseline"] = True
        result["known_count"] = len(cache["seen"])
        print(t("monitor_baseline", count=len(cache["seen"])), file=sys.stderr)
    else:
        new_mentions = [r for r in all_results if r["url"] not in seen_set]
        for r in new_mentions:
            cache["seen"].append(r["url"])
        _save_cache(username, cache)
        result["new_mentions"] = new_mentions
        result["known_count"] = len(cache["seen"])
        if new_mentions:
            print(t("monitor_new_found", count=len(new_mentions)), file=sys.stderr)
        else:
            print(t("monitor_no_new", known=len(seen_set)), file=sys.stderr)

    return result
