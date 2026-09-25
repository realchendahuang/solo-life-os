#!/usr/bin/env python3
"""Append one explicitly supplied, windowed X metric snapshot."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo


ACCOUNT = "realchendahuang"
SHANGHAI = ZoneInfo("Asia/Shanghai")
METRIC_NAMES = (
    "impressions",
    "likes",
    "replies",
    "reposts",
    "quotes",
    "bookmarks",
    "profile_visits",
    "link_clicks",
)


class MetricError(RuntimeError):
    """A concise metric-recording failure safe to show to the user."""


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "profile").is_dir():
            return parent
    raise MetricError("cannot locate the X-Tiller repository root")


def parse_timestamp(value: str, *, flag: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MetricError(f"{flag} must be ISO 8601 with a timezone") from exc
    if parsed.tzinfo is None:
        raise MetricError(f"{flag} must be ISO 8601 with a timezone")
    return parsed.astimezone(SHANGHAI)


def build_record(args: argparse.Namespace, now: datetime) -> dict[str, object]:
    post_id = args.post_id.strip()
    if not re.fullmatch(r"[0-9]{1,19}", post_id):
        raise MetricError("--post-id must be a numeric X post ID")
    start = parse_timestamp(args.window_start, flag="--window-start")
    end = parse_timestamp(args.window_end, flag="--window-end")
    if end <= start:
        raise MetricError("--window-end must be after --window-start")
    metrics = {
        name: value
        for name in METRIC_NAMES
        if (value := getattr(args, name)) is not None
    }
    if not metrics:
        raise MetricError("supply at least one metric value")
    if any(value < 0 for value in metrics.values()):
        raise MetricError("metric values must be zero or greater")
    note = args.note.strip() if args.note and args.note.strip() else None
    return {
        "id": f"metric-{now:%Y%m%d-%H%M%S}-{uuid4().hex[:8]}",
        "recorded_at": now.isoformat(timespec="seconds"),
        "post_id": post_id,
        "post_url": f"https://x.com/{ACCOUNT}/status/{post_id}",
        "metric_window": args.metric_window,
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "source": args.source,
        "metrics": metrics,
        "note": note,
    }


def append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise MetricError(f"cannot write metrics ledger: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record explicitly supplied X metrics; this command never reads X."
    )
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--metric-window", required=True, choices=["1h", "24h", "7d", "30d", "custom"])
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--source", required=True, choices=["x-analytics", "x-api", "user-provided"])
    for metric in METRIC_NAMES:
        parser.add_argument(f"--{metric.replace('_', '-')}", dest=metric, type=int)
    parser.add_argument("--note")
    parser.add_argument("--ledger", type=Path, help="Metrics JSONL inside this repository.")
    parser.add_argument("--dry-run", action="store_true", help="Print the snapshot without writing it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = find_repo_root()
        ledger = args.ledger or repo / "workspace" / "metrics" / "ledger.jsonl"
        ledger = ledger if ledger.is_absolute() else repo / ledger
        try:
            ledger.resolve().relative_to(repo.resolve())
        except ValueError as exc:
            raise MetricError("--ledger must stay inside the X-Tiller repository") from exc
        record = build_record(args, datetime.now(SHANGHAI))
        if not args.dry_run:
            append_jsonl(ledger, record)
            print(f"[weekly-review] saved metrics: {ledger}", file=sys.stderr)
        print(
            json.dumps(
                {
                    "mode": "dry-run" if args.dry_run else "saved",
                    "ledger": str(ledger.relative_to(repo)),
                    "metric": record,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except MetricError as exc:
        print(f"weekly-review error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
