#!/usr/bin/env python3
"""Build a cautious weekly-review baseline from the X-Tiller post archive.

Published posts come from `workspace/posts/*.md` frontmatter (the single
source of truth per contracts/hit-post.md); feedback and metric snapshots
still come from their JSONL ledgers. Metric snapshots are compared only
inside one window bucket, and only the latest snapshot per post is summed;
user-stated feedback reasons/constraints are surfaced verbatim.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


SHANGHAI = ZoneInfo("Asia/Shanghai")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_POST_URL_RE = re.compile(r"/status/(\d+)/?$")

# Fixed metric windows keep their plain name (they are comparable across
# posts); every other window is keyed by its explicit bounds so two different
# custom windows can never merge into one bucket.
FIXED_METRIC_WINDOWS = frozenset({"1h", "24h", "7d", "30d"})
#: Bucket for the cumulative counters the archive already carries in its frontmatter.
#: Deliberately not one of the fixed windows: those measure a stated interval, while an
#: archive counter measures "whatever the collector last saw", so the two must not merge.
ARCHIVE_METRIC_WINDOW = "archive-snapshot"
# Most recent distinct user-stated reasons/constraints surfaced per outcome.
FEEDBACK_EVIDENCE_LIMIT = 10
_EPOCH = datetime(1970, 1, 1, tzinfo=SHANGHAI)


class ReviewError(RuntimeError):
    """A local review-input failure safe to show to the user."""


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "profile").is_dir():
            return parent
    raise ReviewError("cannot locate the X-Tiller repository root")


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(SHANGHAI)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError as exc:
        raise ReviewError(f"cannot read {path}: {exc}") from exc
    return records


def records_in_period(
    records: list[dict[str, Any]], *, timestamp_field: str, start: date, end: date
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        timestamp = parse_timestamp(record.get(timestamp_field))
        if timestamp and start <= timestamp.date() <= end:
            selected.append(record)
    return selected


def post_format(record: dict[str, Any]) -> str:
    """Format label from an explicit thread size; absence is never guessed."""
    size = record.get("thread_size")
    if isinstance(size, int) and not isinstance(size, bool):
        return "thread" if size > 1 else "single"
    return "unknown"


def load_published_from_posts(posts_dir: Path) -> list[dict[str, Any]]:
    """Convert post-archive frontmatter into published-review records.

    Only `kind: published` entries with a posted_at and post_url qualify.
    """
    records: list[dict[str, Any]] = []
    for path in sorted(posts_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReviewError(f"cannot read {path}: {exc}") from exc
        match = _FRONTMATTER_RE.match(text)
        if not match:
            continue
        meta = yaml.safe_load(match.group(1))
        if not isinstance(meta, dict) or meta.get("kind") != "published":
            continue
        posted_at = parse_timestamp(meta.get("posted_at"))
        if posted_at is None:
            continue
        post_id = None
        if isinstance((url := meta.get("post_url")), str):
            url_match = _POST_URL_RE.search(url)
            if url_match:
                post_id = url_match.group(1)
        # `structure` is optional in contracts/hit-post.md. When the archive
        # is silent, thread granularity is unknown and must not become a
        # fabricated "single"; only a stated structure yields a size.
        structure = meta.get("structure")
        if isinstance(structure, str) and structure.strip():
            thread_size = 2 if structure.strip() == "thread" else 1
        else:
            thread_size = None
        records.append(
            {
                "published_at": posted_at.isoformat(),
                "post_id": post_id or meta.get("id", path.stem),
                "thread_size": thread_size,
                "pillar": meta.get("pillar"),
            }
        )
    return records


def load_archive_metric_snapshots(posts_dir: Path) -> list[dict[str, Any]]:
    """Metric snapshots already present in post-archive frontmatter.

    The archive fills `metrics` on every backfill, but the review used to read only
    workspace/metrics/ledger.jsonl, so a fully populated archive still produced a
    review that claimed no metrics existed. These records are cumulative counters, so
    they are emitted under their own bucket and never mixed into a 1h/24h/7d/30d window.
    """
    snapshots: list[dict[str, Any]] = []
    for path in sorted(posts_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReviewError(f"cannot read {path}: {exc}") from exc
        match = _FRONTMATTER_RE.match(text)
        if not match:
            continue
        meta = yaml.safe_load(match.group(1))
        if not isinstance(meta, dict) or meta.get("kind") != "published":
            continue
        values = meta.get("metrics")
        if not isinstance(values, dict):
            continue
        metrics = {
            key: value
            for key, value in values.items()
            if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
        }
        if not metrics:
            continue
        recorded_at = parse_timestamp(meta.get("collected_at"))
        if recorded_at is None:
            continue
        post_id = None
        if isinstance((url := meta.get("post_url")), str):
            url_match = _POST_URL_RE.search(url)
            if url_match:
                post_id = url_match.group(1)
        snapshots.append(
            {
                "recorded_at": recorded_at.isoformat(),
                "post_id": post_id or str(meta.get("id") or path.stem),
                "metric_window": ARCHIVE_METRIC_WINDOW,
                "metrics": metrics,
            }
        )
    return snapshots


def metric_window_key(record: dict[str, Any]) -> str | None:
    """Bucket key for one metric snapshot.

    Fixed windows keep their plain name. Every other window is keyed by its
    explicit bounds as ``custom:<window_start>..<window_end>`` so two
    different custom windows never merge into one bucket.
    """
    window = record.get("metric_window")
    if not isinstance(window, str) or not window:
        return None
    if window in FIXED_METRIC_WINDOWS or window == ARCHIVE_METRIC_WINDOW:
        return window
    start = record.get("window_start")
    end = record.get("window_end")
    start = start if isinstance(start, str) and start else "?"
    end = end if isinstance(end, str) and end else "?"
    return f"custom:{start}..{end}"


def latest_snapshots_by_post(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Keep only the latest snapshot per (window bucket, post_id).

    Repeated snapshots of the same post in the same window measure the same
    thing, so they must not be summed. "Latest" is by ``recorded_at``; ties
    fall back to file order (the later line wins), and records without a
    usable timestamp rank below timestamped records. The returned mapping is
    bucket -> selected records (one per post).
    """
    best_rank: dict[tuple[str, str], tuple[int, datetime, int]] = {}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for index, record in enumerate(records):
        bucket = metric_window_key(record)
        if bucket is None:
            continue
        post_id = record.get("post_id")
        identity = post_id if isinstance(post_id, str) and post_id else f"<no-post-id:{index}>"
        timestamp = parse_timestamp(record.get("recorded_at"))
        rank = (1 if timestamp is not None else 0, timestamp or _EPOCH, index)
        key = (bucket, identity)
        if key not in best_rank or rank > best_rank[key]:
            best_rank[key] = rank
            latest[key] = record
    grouped: dict[str, list[dict[str, Any]]] = {}
    for (bucket, _identity), record in latest.items():
        grouped.setdefault(bucket, []).append(record)
    return grouped


def collect_feedback_evidence(
    feedback: list[dict[str, Any]], *, limit: int = FEEDBACK_EVIDENCE_LIMIT
) -> dict[str, dict[str, list[str]]]:
    """Group verbatim user-stated reasons/constraints by outcome, newest first.

    Only explicit `reason` and `constraints` text is surfaced; nothing is
    inferred from silence. At most `limit` distinct strings are kept per
    outcome.
    """
    ordered = sorted(feedback, key=_feedback_recency, reverse=True)
    by_outcome: dict[str, dict[str, list[str]]] = {}
    for record in ordered:
        outcome = record.get("outcome")
        if not isinstance(outcome, str) or not outcome:
            continue
        entry = by_outcome.setdefault(outcome, {"reasons": [], "constraints": []})
        reason = record.get("reason")
        if isinstance(reason, str) and reason.strip():
            text = reason.strip()
            if text not in entry["reasons"] and len(entry["reasons"]) < limit:
                entry["reasons"].append(text)
        constraints = record.get("constraints")
        if isinstance(constraints, list):
            for value in constraints:
                if not isinstance(value, str) or not value.strip():
                    continue
                text = value.strip()
                if text not in entry["constraints"] and len(entry["constraints"]) < limit:
                    entry["constraints"].append(text)
    return {outcome: by_outcome[outcome] for outcome in sorted(by_outcome)}


def _feedback_recency(record: dict[str, Any]) -> tuple[int, datetime]:
    timestamp = parse_timestamp(record.get("recorded_at"))
    return (0, _EPOCH) if timestamp is None else (1, timestamp)


def build_review(
    *,
    start: date,
    end: date,
    now: datetime,
    published_records: list[dict[str, Any]],
    feedback_records: list[dict[str, Any]],
    metric_records: list[dict[str, Any]],
) -> dict[str, Any]:
    published = records_in_period(
        published_records, timestamp_field="published_at", start=start, end=end
    )
    feedback = records_in_period(
        feedback_records, timestamp_field="recorded_at", start=start, end=end
    )
    metrics = records_in_period(
        metric_records, timestamp_field="recorded_at", start=start, end=end
    )
    format_counts = Counter(post_format(record) for record in published)
    outcome_counts = Counter(
        outcome
        for record in feedback
        if isinstance((outcome := record.get("outcome")), str)
    )
    latest_by_bucket = latest_snapshots_by_post(metrics)
    metrics_by_window: dict[str, dict[str, Any]] = {}
    for bucket in sorted(latest_by_bucket):
        post_ids: list[str] = []
        totals: Counter[str] = Counter()
        for record in latest_by_bucket[bucket]:
            post_id = record.get("post_id")
            if isinstance(post_id, str) and post_id and post_id not in post_ids:
                post_ids.append(post_id)
            values = record.get("metrics")
            if isinstance(values, dict):
                for key, value in values.items():
                    if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool):
                        totals[key] += value
        # record_count counts the latest-per-post snapshots summed into
        # totals: exactly one measurement per post per window bucket.
        metrics_by_window[bucket] = {
            "record_count": len(latest_by_bucket[bucket]),
            "post_ids": post_ids,
            "totals": dict(sorted(totals.items())),
        }
    gaps: list[str] = []
    if not published:
        gaps.append("No publication records exist in this review period.")
    if not feedback:
        gaps.append("No structured draft-feedback records exist in this review period.")
    if not metrics:
        gaps.append("No metric snapshots exist in this review period.")
    if published and any(not record.get("pillar") for record in published):
        gaps.append(
            "Post-archive entries do not yet all carry a pillar tag; "
            "do not infer which topic pillar performed best."
        )
    archive_timestamps = [
        timestamp
        for record in published_records
        if (timestamp := parse_timestamp(record.get("published_at"))) is not None
    ]
    if archive_timestamps:
        newest_archive = max(archive_timestamps)
        if newest_archive.date() < end:
            missing_days = (end - newest_archive.date()).days
            gaps.append(
                f"Archive has no posts after {newest_archive.date().isoformat()}; "
                f"{missing_days} days missing from the review window."
            )

    return {
        "id": f"review-{end:%Y%m%d}",
        "created_at": now.isoformat(timespec="seconds"),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "published": {
            "count": len(published),
            "formats": dict(sorted(format_counts.items())),
            "post_ids": [
                record["post_id"]
                for record in published
                if isinstance(record.get("post_id"), str)
            ],
        },
        "feedback": {
            "count": len(feedback),
            "outcomes": dict(sorted(outcome_counts.items())),
            # Verbatim user-stated reasons/constraints: evidence, not inference.
            "user_stated_evidence": {
                "source": "user-stated",
                "by_outcome": collect_feedback_evidence(feedback),
            },
        },
        "metrics": {
            "record_count": len(metrics),
            "by_window": metrics_by_window,
        },
        "evidence_gaps": gaps,
        "recommendations": [],
        "status": "ready-for-review" if not gaps else "needs-more-data",
    }


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(serialized)
        temporary = Path(handle.name)
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a local X-Tiller weekly-review baseline; it never calls X."
    )
    parser.add_argument("--days", type=int, default=7, help="Inclusive review window, from 1 to 31.")
    parser.add_argument("--ending", type=date.fromisoformat, help="Final YYYY-MM-DD date; defaults to today in Asia/Shanghai.")
    parser.add_argument("--output", type=Path, help="JSON output inside the repository.")
    parser.add_argument("--dry-run", action="store_true", help="Print the baseline without writing it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not 1 <= args.days <= 31:
            raise ReviewError("--days must be between 1 and 31")
        repo = find_repo_root()
        now = datetime.now(SHANGHAI)
        end = args.ending or now.date()
        start = end - timedelta(days=args.days - 1)
        review = build_review(
            start=start,
            end=end,
            now=now,
            published_records=load_published_from_posts(repo / "workspace" / "posts"),
            feedback_records=load_jsonl(repo / "workspace" / "feedback" / "ledger.jsonl"),
            metric_records=[
                *load_jsonl(repo / "workspace" / "metrics" / "ledger.jsonl"),
                *load_archive_metric_snapshots(repo / "workspace" / "posts"),
            ],
        )
        output = args.output or repo / "workspace" / "reviews" / f"{review['id']}.json"
        output = output if output.is_absolute() else repo / output
        try:
            output.resolve().relative_to(repo.resolve())
        except ValueError as exc:
            raise ReviewError("--output must stay inside the X-Tiller repository") from exc
        if not args.dry_run:
            atomic_write_json(output, review)
            print(f"[weekly-review] saved: {output}", file=sys.stderr)
        print(json.dumps(review, ensure_ascii=False, indent=2))
        return 0
    except ReviewError as exc:
        print(f"weekly-review error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
