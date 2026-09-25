#!/usr/bin/env python3
"""Backfill metrics (and optionally verbatim text) into workspace/posts/ archives.

Fetches each archived post through x-fetch (single-tweet backend, zero deps),
updates frontmatter `metrics` to the latest snapshot, and appends a timestamped
line under `## 数据回采` per contracts/hit-post.md. With --sync-text it also
replaces the archived body with the fetched verbatim text when they differ —
the script itself never rewrites any wording.

With --from-json the metrics come from an already-saved x-fetch payload instead
of a fresh fetch, so evidence collected earlier (for example a batch kept under
workspace/research/) can be merged offline without paying for the same request
twice.

Never records a fabricated all-zero snapshot: if the upstream payload reports
zero for every metric (and carries no explicit metrics_present list), the merge
is skipped and reported instead.

Usage:
    python3 backfill_metrics.py --url https://x.com/.../status/123 [--window 24h]
    python3 backfill_metrics.py --url <url> --from-json workspace/research/batch.json
    python3 backfill_metrics.py --all [--kind published] [--sync-text] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontmatter import load_all, write  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")

METRIC_KEYS = ("views", "likes", "reposts", "replies", "bookmarks")
FETCH_TO_CONTRACT = {
    "views": "views",
    "likes": "likes",
    "retweets": "reposts",
    "replies_count": "replies",
    "bookmarks": "bookmarks",
}


def find_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "profile").is_dir():
            return parent
    raise SystemExit("cannot locate the X-Tiller repository root")


STATUS_ID_RE = re.compile(r"/status(?:es)?/(\d+)")


def status_id_of(url: str) -> str:
    match = STATUS_ID_RE.search(url or "")
    return match.group(1) if match else ""


def load_payload_batch(path: Path) -> dict[str, dict]:
    """Index an already-saved x-fetch payload by status id.

    Accepts either one payload (``{"tweet": {...}}``) or a mapping of
    status id -> payload, which is how batch evidence is kept under
    workspace/research/.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read --from-json {path}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"--from-json {path} must contain a JSON object")

    if "tweet" in data:
        candidates = [data]
    else:
        candidates = [value for value in data.values() if isinstance(value, dict)]

    index: dict[str, dict] = {}
    for payload in candidates:
        tweet = payload.get("tweet")
        if not isinstance(tweet, dict):
            continue
        sid = str(tweet.get("tweet_id") or payload.get("tweet_id") or "")
        if not sid:
            url = str(payload.get("url") or tweet.get("url") or "")
            match = re.search(r"/status/(\d+)", url)
            sid = match.group(1) if match else ""
        if sid:
            index[sid] = payload
    if not index:
        raise SystemExit(f"--from-json {path} contains no payloads keyed by status id")
    return index


def fetch_tweet(root: Path, url: str) -> dict:
    """Return the parsed x-fetch JSON payload for one post."""
    script = root / ".agents" / "skills" / "x-fetch" / "scripts" / "fetch_tweet.py"
    result = subprocess.run(
        ["python3", str(script), "--url", url, "--pretty"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error_code": "bad_output", "detail": result.stdout[-200:]}
    return payload


def extract_metrics(tweet: dict) -> dict[str, int]:
    """Map x-fetch tweet fields onto the contract metric keys (ints only)."""
    metrics: dict[str, int] = {}
    for fetch_key, contract_key in FETCH_TO_CONTRACT.items():
        value = tweet.get(fetch_key)
        if isinstance(value, int):
            metrics[contract_key] = value
    return metrics


def select_metrics(tweet: dict, payload: dict | None = None) -> tuple[dict[str, int], str | None]:
    """Choose which metrics are real enough to record.

    Returns ``(metrics, skip_reason)``. When the payload carries an explicit
    ``metrics_present`` list (added by x-fetch), only the listed keys are
    merged and an explicit zero is trusted. Otherwise an all-zero reading is
    treated as "upstream did not report metrics" and skipped.
    """
    fetched = extract_metrics(tweet)
    present = tweet.get("metrics_present")
    if present is None and isinstance(payload, dict):
        present = payload.get("metrics_present")
    if present is not None:
        wanted = {str(key) for key in present} if isinstance(present, (list, tuple, set)) else set()
        fetched = {
            contract_key: fetched[contract_key]
            for fetch_key, contract_key in FETCH_TO_CONTRACT.items()
            if contract_key in fetched and (fetch_key in wanted or contract_key in wanted)
        }
        if not fetched:
            return {}, "no metrics present upstream (metrics_present empty)"
        return fetched, None
    if not fetched:
        return {}, "no metrics in payload"
    if all(value == 0 for value in fetched.values()):
        return {}, "metrics all zero — skipped (upstream likely missing)"
    return fetched, None


def parse_created_at(raw: str) -> str | None:
    """Convert x-fetch's 'Sat Sep 05 02:15:18 +0000 2026' to ISO8601."""
    try:
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").isoformat()
    except (ValueError, TypeError):
        return None


def split_main_body(body: str) -> tuple[str, str]:
    """Split archive body into (main post text, annotation sections)."""
    for marker in ("## 我的批注", "## 数据回采"):
        index = body.find(marker)
        if index != -1:
            return body[:index].rstrip(), body[index:]
    return body.strip(), ""


def recycle_line(now: datetime, metrics: dict[str, int], window: str | None = None) -> str:
    """One 数据回采 snapshot line; the window label is required by contract."""
    values = " ".join(f"{key}={metrics[key]}" for key in METRIC_KEYS if key in metrics)
    label = f"[{window}] " if window else ""
    return f"- {now.strftime('%Y-%m-%d %H:%M')} {label}snapshot: {values}"


def append_recycle(body: str, line: str) -> tuple[str, bool]:
    """Append one snapshot line under ## 数据回采, creating the section if needed.

    Returns (new_body, appended). Idempotent: an identical line is not repeated.
    """
    if line in body:
        return body, False
    if "## 数据回采" in body:
        return f"{body.rstrip()}\n{line}\n", True
    return f"{body.rstrip()}\n\n## 数据回采\n{line}\n", True


def backfill_file(
    path: Path,
    meta: dict,
    body: str,
    payload: dict,
    sync_text: bool,
    now: datetime,
    window: str | None = None,
) -> tuple[dict, str, list[str]]:
    changes: list[str] = []
    if payload.get("error_code"):
        return meta, body, [f"fetch failed ({payload.get('error_code')})"]
    tweet = payload.get("tweet") or {}
    text = (tweet.get("text") or "").strip()
    if not text:
        return meta, body, ["fetch returned no text"]

    if sync_text:
        main, tail = split_main_body(body)
        if main != text:
            body = f"{text}\n\n{tail}".strip() + "\n"
            changes.append(f"text verbatim-synced ({len(main)} -> {len(text)} chars)")
        elif main:
            changes.append("text already verbatim")

    fetched, skip_reason = select_metrics(tweet, payload)
    if skip_reason:
        changes.append(skip_reason)
    else:
        current = meta.get("metrics")
        merged = {**(current if isinstance(current, dict) else {}), **fetched}
        meta = {**meta, "metrics": merged}
        changes.append("metrics=" + " ".join(f"{k}={fetched[k]}" for k in METRIC_KEYS if k in fetched))
        body, appended = append_recycle(body, recycle_line(now, fetched, window))
        if appended:
            changes.append("回采行已追加")

    if not meta.get("posted_at"):
        created = parse_created_at(tweet.get("created_at"))
        if created:
            meta = {**meta, "posted_at": created}
            changes.append(f"posted_at filled ({created[:10]})")

    return meta, body, changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="backfill a single archive file matching this URL")
    ap.add_argument("--recent", type=int, help="backfill archive files of --kind posted within the last N days")
    ap.add_argument("--all", action="store_true", help="backfill every archive file of --kind")
    ap.add_argument("--kind", default="published", choices=["published", "hit"])
    ap.add_argument("--sync-text", action="store_true", help="also sync verbatim text when it differs")
    ap.add_argument("--window", default="backfill",
                    help="window label written into the 回采 line (e.g. 24h/7d; default: backfill)")
    ap.add_argument("--dry-run", action="store_true", help="print planned changes without writing")
    ap.add_argument(
        "--from-json",
        help="merge metrics from an already-saved x-fetch payload instead of fetching "
             "(a single payload or a status-id -> payload batch file)",
    )
    ap.add_argument(
        "--no-fetch",
        action="store_true",
        help="plan only: report which files match without calling x-fetch (offline; no rate limit)",
    )
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between fetches in --all/--recent mode")
    args = ap.parse_args()
    if not args.url and not args.all and not args.recent:
        ap.error("choose --url, --all, or --recent <days>")
    if args.no_fetch and not args.dry_run:
        ap.error("--no-fetch only makes sense together with --dry-run")
    batch: dict[str, dict] = {}
    if args.from_json:
        batch = load_payload_batch(Path(args.from_json))
    if args.all and args.sync_text and not args.dry_run:
        print("warning: --all --sync-text rewrites bodies in bulk; run with --dry-run first",
              file=sys.stderr)

    root = find_root()
    posts_dir = root / "workspace" / "posts"
    now = datetime.now(SHANGHAI)

    errors: list[str] = []
    targets: list[tuple[Path, dict, str]] = []
    for path, meta, body in load_all(posts_dir, errors=errors):
        if not meta.get("post_url"):
            continue
        if args.url:
            if meta["post_url"].split("?")[0] == args.url.split("?")[0]:
                targets.append((path, meta, body))
        elif args.recent is not None:
            if meta.get("kind") == args.kind:
                posted_at = meta.get("posted_at")
                if posted_at:
                    try:
                        p_dt = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00")).astimezone(SHANGHAI)
                        age_days = (now - p_dt).total_seconds() / 86400
                        if 0 <= age_days <= args.recent:
                            targets.append((path, meta, body))
                    except Exception:
                        pass
        elif meta.get("kind") == args.kind:
            targets.append((path, meta, body))
    if args.recent is not None:
        targets.sort(key=lambda x: str(x[1].get("posted_at", "")), reverse=True)
    for err in errors:
        print(f"skipped unreadable file: {err}", file=sys.stderr)
    if not targets:
        raise SystemExit("no matching archive file")

    changed = skipped = failed = 0
    for i, (path, meta, body) in enumerate(targets, 1):
        url = meta["post_url"]
        if args.no_fetch:
            skipped += 1
            print(f"[{i}/{len(targets)}] {path.name}: would fetch {url}")
            continue
        if batch:
            sid = status_id_of(url)
            payload = batch.get(sid) if sid else None
            if payload is None:
                failed += 1
                print(f"[{i}/{len(targets)}] {path.name}: no payload for status {sid} in --from-json")
                continue
        else:
            payload = fetch_tweet(root, url)
        code = payload.get("error_code")
        if code == "rate_limited":
            print(f"[{i}/{len(targets)}] RATE LIMITED — stopping batch; re-run later from here")
            break
        new_meta, new_body, changes = backfill_file(
            path, meta, body, payload, args.sync_text, now, args.window
        )
        label = path.name
        if code or any("no text" in change for change in changes):
            failed += 1
            print(f"[{i}/{len(targets)}] {label}: {changes[0] if changes else code}")
        elif (new_meta, new_body) == (meta, body):
            skipped += 1
            detail = "; ".join(changes) if changes else "no changes"
            print(f"[{i}/{len(targets)}] {label}: {detail}")
        elif args.dry_run:
            changed += 1
            print(f"[{i}/{len(targets)}] {label}: would change — " + "; ".join(changes))
        else:
            write(path, new_meta, new_body)
            changed += 1
            print(f"[{i}/{len(targets)}] {label}: " + "; ".join(changes))
        if args.all and i < len(targets):
            time.sleep(args.delay)

    mode = " (dry-run)" if args.dry_run else ""
    if args.no_fetch:
        print(f"planned: {len(targets)} file(s), no fetch performed, no changes written")
        return 0
    print(f"done{mode}: changed={changed} skipped={skipped} failed={failed} total={len(targets)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
