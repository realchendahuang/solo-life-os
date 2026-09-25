#!/usr/bin/env python3
"""Capture a single X/Twitter post as a Candidate Signal in `workspace/candidates/`.

Fetches the tweet without login or paid API dependencies via the vendored x-fetch
engine (FxTwitter), evaluates hit potential, and records a verified Candidate Signal.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[4]
XFETCH_DIR = REPO_ROOT / ".agents" / "skills" / "x-fetch" / "scripts"
SOURCE_REG_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(XFETCH_DIR))
sys.path.insert(0, str(SOURCE_REG_DIR))

import capture_candidate as candidate_mod  # noqa: E402
import poll_registry  # noqa: E402
from xtf.parsers.urls import parse_tweet_url  # noqa: E402
from xtf.router import Router  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")


class XSignalError(RuntimeError):
    """User-facing X signal capture error."""


def fetch_tweet_payload(url: str, timeout: int = 20) -> dict[str, Any]:
    try:
        username, tweet_id = parse_tweet_url(url)
    except ValueError as exc:
        raise XSignalError(f"invalid X/Twitter post URL: {url}") from exc

    router = Router(timeout=timeout)
    try:
        tweet = router.fetch_tweet(username, tweet_id)
        if not tweet or not isinstance(tweet, dict):
            raise XSignalError(f"empty response from x-fetch for {url}")
        return tweet
    except Exception as exc:  # noqa: BLE001
        raise XSignalError(f"failed to fetch tweet from {url}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture an X/Twitter post as a Candidate Signal in workspace/candidates/."
    )
    parser.add_argument("--url", required=True, help="Canonical post URL on x.com or twitter.com.")
    parser.add_argument(
        "--action",
        choices=["brief", "watch", "discard"],
        default=None,
        help="Override suggested action (default auto-classified).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect candidate signal without writing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = candidate_mod.find_repo_root()
        sources_dict = candidate_mod.load_sources(repo / "sources" / "registry.json", repo)
        source = sources_dict.get("x-direct-signal")
        if not source:
            raise XSignalError("registered source 'x-direct-signal' missing from sources/registry.json")

        now = datetime.now(SHANGHAI)
        tweet = fetch_tweet_payload(args.url)

        # The parse above validated the URL; reuse its handle and id rather than trusting
        # the payload (normalize_tweet_json does not carry a tweet id).
        url_username, url_tweet_id = parse_tweet_url(args.url)
        author_handle = str(tweet.get("screen_name") or url_username or "").lstrip("@")
        author_name = str(tweet.get("author") or author_handle)
        text = str(tweet.get("text") or "").strip()
        if not text:
            raise XSignalError("fetched tweet has no text content")

        first_line = text.splitlines()[0].strip()
        title = f"@{author_handle}: {first_line[:80]}" if author_handle else first_line[:80]

        # Extract metrics
        likes = tweet.get("likes") or 0
        retweets = tweet.get("retweets") or 0
        views = tweet.get("views") or 0
        replies = tweet.get("replies_count") or 0

        # Auto-classify blueprints and friction angles
        auto_action, classified_tags = poll_registry.classify_hit_potential(title, text, source)
        action = args.action or auto_action
        combined_tags = list(classified_tags)

        # Normalize the tweet timestamp; None (instead of "now") when it cannot be read.
        pub_iso = poll_registry.parse_published_at(tweet.get("created_at"))

        tweet_url = f"https://x.com/{author_handle}/status/{url_tweet_id}"
        canonical_url = candidate_mod.canonicalize_url(tweet_url)

        if likes:
            combined_tags.append(f"likes:{likes}")
        if retweets:
            combined_tags.append(f"retweets:{retweets}")
        if replies:
            combined_tags.append(f"replies:{replies}")
        if views:
            combined_tags.append(f"views:{views}")

        candidate_args = argparse.Namespace(
            source_id="x-direct-signal",
            url=canonical_url,
            title=title,
            excerpt=text[:500],
            author=f"@{author_handle} ({author_name})" if author_handle else None,
            published_at=pub_iso,
            verification_status="unverified",
            suggested_action=action,
            tag=combined_tags,
            output=None,
            dry_run=args.dry_run,
        )

        candidate_record = candidate_mod.build_candidate(candidate_args, now, source)

        candidates_dir = repo / "workspace" / "candidates"
        existing = candidate_mod.find_duplicate(candidates_dir, candidate_record)
        if existing:
            print(f"[capture-x-signal] candidate already exists: {existing.name}", file=sys.stderr)
            print(
                json.dumps(
                    {
                        "mode": "duplicate",
                        "path": str(existing.relative_to(repo)),
                        "candidate": candidate_record,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if not args.dry_run:
            target_path = candidate_mod.append_candidate_ledger(candidates_dir, candidate_record)
            print(f"[capture-x-signal] appended: {target_path}", file=sys.stderr)

        print(
            json.dumps(
                {
                    "mode": "dry-run" if args.dry_run else "captured",
                    "candidate": candidate_record,
                    "target_file": str(candidate_mod.candidates_ledger_path(candidates_dir)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (XSignalError, candidate_mod.CandidateError) as exc:
        print(f"[capture-x-signal] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
