"""HTTP layer: single choke point for all upstream calls.

Replaces the v1 ``http_get -> dict | str | None`` tri-state with:
  - success  -> body (str) or parsed JSON (via get_json)
  - failure  -> typed exception (RateLimited / NotFound / UpstreamDown)

Retries transient failures (429, 5xx, network errors) with exponential
backoff. 404 and 4xx are not retried.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .config import RETRY_ATTEMPTS, RETRY_BACKOFF_BASE, USER_AGENT
from .exceptions import NotFound, RateLimited, UpstreamDown

_MAX_BODY = 10 * 1024 * 1024


def get_text(url: str, headers: Optional[Dict[str, str]] = None,
             timeout: int = 15, retries: int = RETRY_ATTEMPTS) -> str:
    """GET a URL, return the response body as text. Raises typed errors."""
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(_MAX_BODY).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(f"HTTP 404 — {url}") from e
            if e.code in (403, 429):
                last_exc = RateLimited(f"HTTP {e.code} — {url}")
            elif e.code >= 500:
                last_exc = UpstreamDown(f"HTTP {e.code} — {url}")
            else:
                raise UpstreamDown(f"HTTP {e.code}: {e.reason} — {url}") from e
        except urllib.error.URLError as e:
            last_exc = UpstreamDown(f"network error — {url}: {e.reason}")
        except TimeoutError:
            last_exc = UpstreamDown(f"timeout — {url}")

        if attempt < retries:
            time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))

    assert last_exc is not None
    raise last_exc


def get_json(url: str, headers: Optional[Dict[str, str]] = None,
             timeout: int = 15, retries: int = RETRY_ATTEMPTS) -> Any:
    """GET a URL and parse JSON. Raises UpstreamDown on malformed JSON."""
    raw = get_text(url, headers=headers, timeout=timeout, retries=retries)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise UpstreamDown(f"invalid JSON from {url}") from e


def probe(url: str, timeout: int = 3) -> bool:
    """Lightweight reachability check. Never raises."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(1024)
        return True
    except Exception:
        return False
