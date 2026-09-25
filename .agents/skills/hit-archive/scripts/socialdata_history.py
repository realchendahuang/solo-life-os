#!/usr/bin/env python3
"""Backfill the full post history of @realchendahuang via SocialData.

SocialData (socialdata.tools) is a paid read-only X data proxy:
$0.20 per 1,000 results, cursor pagination on every endpoint, single
bearer-token auth. Its per-post views_count makes it the best source for
full-history backfill — X's own archive export has no view counts.

Two modes:

  --fetch   page the whole user timeline into
            workspace/research/socialdata-<user>-latest.json (raw evidence).
            Resumable: partial state keeps next_cursor; re-run with --continue.
  --import  sync fetched posts into workspace/posts/ (kind: published),
            dedup by status id. Replies and pure retweets are skipped by
            default; quotes (own posts quoting someone) are kept.

Credentials: env SOCIALDATA_API_KEY, or --key-file (default ~/.socialdata_key).
The key never goes into the repository.

Usage:
    python3 socialdata_history.py --fetch [--continue] [--delay 1.0] [--max-pages N]
    python3 socialdata_history.py --import [--include-replies] [--from-json PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontmatter import load_all, next_free_id, write  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
API_BASE = "https://api.socialdata.tools"
DEFAULT_KEY_FILE = Path.home() / ".socialdata_key"
TWITTER_DATE = "%a %b %d %H:%M:%S %z %Y"
PRICE_PER_RESULT = 0.0002  # USD

# SocialData tweet fields -> contracts/hit-post.md metric keys
FIELD_MAP = {
    "views_count": "views",
    "favorite_count": "likes",
    "retweet_count": "reposts",
    "reply_count": "replies",
    "quote_count": "quotes",
    "bookmark_count": "bookmarks",
}


def find_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "profile").is_dir():
            return parent
    raise SystemExit("cannot locate the X-Tiller repository root")


def load_key(args: argparse.Namespace) -> str:
    key = os.environ.get("SOCIALDATA_API_KEY", "").strip()
    if not key:
        key_file = Path(args.key_file)
        if key_file.is_file():
            key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(
            "no API key: set SOCIALDATA_API_KEY or write it to "
            f"{DEFAULT_KEY_FILE} (never commit it)"
        )
    return key


def api_get(path: str, params: dict[str, str], key: str, timeout: int = 60) -> tuple[dict | None, int]:
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        print(f"  HTTP {exc.code}: {body}", file=sys.stderr)
        return None, exc.code


def tweet_text(tweet: dict) -> str:
    note = tweet.get("note_tweet") or {}
    results = (note.get("note_tweet_results") or {})
    text = results.get("text") if isinstance(results, dict) else None
    if not text:
        text = tweet.get("full_text") or tweet.get("text") or ""
    return text.strip()


def parse_metrics(tweet: dict) -> dict[str, int]:
    return {
        contract_key: tweet[fetch_key]
        for fetch_key, contract_key in FIELD_MAP.items()
        if isinstance(tweet.get(fetch_key), int)
    }


def parse_posted_at(tweet: dict) -> str:
    for key in ("tweet_created_at", "created_at"):
        raw = tweet.get(key)
        if not raw:
            continue
        try:
            return datetime.strptime(raw, TWITTER_DATE).isoformat()
        except (ValueError, TypeError):
            pass
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).isoformat()
        except (ValueError, TypeError):
            pass
    return ""


def is_pure_retweet(tweet: dict) -> bool:
    return bool(tweet.get("retweeted_status"))


def is_reply(tweet: dict) -> bool:
    return bool(tweet.get("in_reply_to_status_id_str"))


def state_path(root: Path, username: str) -> Path:
    return root / "workspace" / "research" / f"socialdata-{username}-latest.json"


def fetch_history(args: argparse.Namespace) -> int:
    root = find_root()
    key = load_key(args)
    path = state_path(root, args.username)
    state: dict = {"user_id": args.user_id, "username": args.username,
                   "fetched_at": "", "next_cursor": "", "pages": 0,
                   "complete": False, "tweets": []}
    if args.continue_ and path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("complete"):
            print(f"already complete ({len(state['tweets'])} tweets); delete the file to refetch")
            return 0
        print(f"resuming: {len(state['tweets'])} tweets from {state['pages']} pages")

    seen = {t.get("id_str") for t in state["tweets"]}
    cursor = state.get("next_cursor") or ""
    pages = 0
    while True:
        params: dict[str, str] = {}
        if cursor:
            params["cursor"] = cursor
        payload, status = api_get(f"/twitter/user/{args.user_id}/tweets", params, key)
        if payload is None:
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            print(f"stopping after HTTP {status}; state saved, re-run with --continue")
            break
        tweets = payload.get("tweets") or []
        new = [t for t in tweets if t.get("id_str") and t["id_str"] not in seen]
        for t in new:
            seen.add(t["id_str"])
        state["tweets"].extend(new)
        state["pages"] += 1
        pages += 1
        cursor = payload.get("next_cursor") or ""
        state["next_cursor"] = cursor
        state["fetched_at"] = datetime.now(SHANGHAI).isoformat(timespec="seconds")
        state["complete"] = not cursor
        if state["pages"] % 5 == 0 or not cursor:
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        print(f"  page {state['pages']}: +{len(new)} tweets, total {len(state['tweets'])}, "
              f"est. ${len(state['tweets']) * PRICE_PER_RESULT:.2f}")
        if not cursor:
            print("timeline fully fetched")
            break
        if args.max_pages and pages >= args.max_pages:
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            print(f"hit --max-pages {args.max_pages}; saved state, re-run with --continue")
            break
        time.sleep(args.delay)

    print(f"saved: {path} ({len(state['tweets'])} tweets, {state['pages']} pages, "
          f"est. ${len(state['tweets']) * PRICE_PER_RESULT:.2f})")
    return 0


def import_history(args: argparse.Namespace) -> int:
    root = find_root()
    path = Path(args.from_json) if args.from_json else state_path(root, args.username)
    if not path.is_file():
        raise SystemExit(f"no fetch state: {path} (run --fetch first)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    snapshot = payload.get("fetched_at", "")[:16].replace("T", " ")

    archived: set[str] = set()
    for _p, meta, _b in load_all(root / "workspace" / "posts"):
        if meta.get("post_url"):
            tail = meta["post_url"].rstrip("/").rsplit("/", 1)[-1]
            archived.add(tail)

    candidates = []
    for tweet in payload.get("tweets", []):
        tid = tweet.get("id_str")
        if not tid or tid in archived:
            continue
        if is_pure_retweet(tweet):
            continue
        if is_reply(tweet) and not args.include_replies:
            continue
        candidates.append(tweet)
    candidates.sort(key=parse_posted_at)
    skipped_rt = sum(1 for t in payload.get("tweets", []) if is_pure_retweet(t))
    skipped_reply = sum(1 for t in payload.get("tweets", [])
                        if is_reply(t) and not is_pure_retweet(t))
    print(f"{path.name}: {len(payload.get('tweets', []))} fetched | {skipped_rt} retweets and "
          f"{skipped_reply} replies skipped by default | {len(candidates)} to import")

    posts_dir = root / "workspace" / "posts"
    day = datetime.now(SHANGHAI).strftime("%Y%m%d")
    written = 0
    for tweet in candidates:
        post_id, _target = next_free_id(posts_dir, f"post-{day}-")
        screen_name = (tweet.get("user") or {}).get("screen_name") or args.username
        url = f"https://x.com/{screen_name}/status/{tweet['id_str']}"
        metrics = parse_metrics(tweet)
        meta = {
            "id": post_id,
            "kind": "published",
            "post_url": url,
            "posted_at": parse_posted_at(tweet),
            "collected_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            "channel": "unknown",
            "source": "socialdata",
        }
        if metrics:
            meta["metrics"] = metrics
        if is_reply(tweet):
            meta["in_reply_to_status_id_str"] = tweet["in_reply_to_status_id_str"]
        line = " ".join(f"{k}={metrics[k]}" for k in ("views", "likes", "reposts", "replies", "quotes", "bookmarks") if k in metrics)
        body = (tweet_text(tweet) or "（无法取回正文）")
        body += f"\n\n## 我的批注\n\n（为什么这条值得学/为什么它能爆？）\n\n## 数据回采\n- {snapshot} snapshot (socialdata): {line}\n"
        write(posts_dir / f"{post_id}.md", meta, body)
        written += 1
    print(f"written {written} archives")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="page the whole timeline (paid per result)")
    ap.add_argument("--import", dest="import_", action="store_true", help="sync fetched posts into the archive")
    ap.add_argument("--username", default="realchendahuang")
    ap.add_argument("--user-id", default="1779691567546269696")
    ap.add_argument("--continue", dest="continue_", action="store_true", help="resume an interrupted fetch")
    ap.add_argument("--max-pages", type=int, help="stop after N pages (then --continue)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between pages")
    ap.add_argument("--include-replies", action="store_true", help="import replies too (default skipped)")
    ap.add_argument("--from-json", help="import from a specific fetch state file")
    ap.add_argument("--key-file", default=str(DEFAULT_KEY_FILE))
    args = ap.parse_args()
    if not args.fetch and not args.import_:
        ap.error("choose --fetch or --import")
    if args.fetch:
        return fetch_history(args)
    return import_history(args)


if __name__ == "__main__":
    sys.exit(main())
