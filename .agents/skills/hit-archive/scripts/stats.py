#!/usr/bin/env python3
"""Aggregate workspace/posts/*.md frontmatter into a CSV report + summary.

Scan all hit/post archive files (contract: contracts/hit-post.md), write a
flat CSV table to workspace/stats/ and print a compact summary.

Usage:
    python3 stats.py                          # all posts
    python3 stats.py --kind hit               # only historical hits
    python3 stats.py --since 2026-09-01       # posted_at >= date (Asia/Shanghai)
    python3 stats.py --until 2026-09-10       # posted_at <= date (Asia/Shanghai)
    python3 stats.py --top 5                  # print top-N by likes
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from frontmatter import load_all

SHANGHAI = ZoneInfo("Asia/Shanghai")
COLUMNS = [
    "id",
    "kind",
    "source",
    "post_url",
    "posted_at",
    "collected_at",
    "channel",
    "draft_id",
    "pillar",
    "tags",
    "structure",
    "hook",
    "views",
    "likes",
    "reposts",
    "replies",
    "quotes",
    "bookmarks",
    "link_clicks",
    "verdict",
]
COVERAGE_FIELDS = ("pillar", "structure", "hook", "verdict", "draft_id")


def find_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "profile").is_dir():
            return parent
    raise SystemExit("cannot locate the X-Tiller repository root")


def metrics_of(meta: dict) -> dict:
    """Return the metrics mapping, tolerating hand-edited non-dict values."""
    metrics = meta.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def row_of(meta: dict) -> dict:
    metrics = metrics_of(meta)
    tags = meta.get("tags") or []
    return {
        "id": meta.get("id", ""),
        "kind": meta.get("kind", ""),
        "source": meta.get("source", "") or "",
        "post_url": meta.get("post_url", ""),
        "posted_at": meta.get("posted_at", "") or "",
        "collected_at": meta.get("collected_at", "") or "",
        "channel": meta.get("channel", "") or "",
        "draft_id": meta.get("draft_id", "") or "",
        "pillar": meta.get("pillar", "") or "",
        "tags": "|".join(tags) if isinstance(tags, list) else str(tags or ""),
        "structure": meta.get("structure", "") or "",
        "hook": meta.get("hook", "") or "",
        "views": metrics.get("views", ""),
        "likes": metrics.get("likes", ""),
        "reposts": metrics.get("reposts", ""),
        "replies": metrics.get("replies", ""),
        "quotes": metrics.get("quotes", ""),
        "bookmarks": metrics.get("bookmarks", ""),
        "link_clicks": metrics.get("link_clicks", ""),
        "verdict": meta.get("verdict", "") or "",
    }


def to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_day(raw: str, flag: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{flag} must be YYYY-MM-DD, got {raw!r}") from None


def posted_day(meta: dict) -> date | None:
    """Shanghai-local posting date, or None when posted_at is missing/invalid."""
    raw = meta.get("posted_at")
    if isinstance(raw, datetime):
        moment = raw
    elif isinstance(raw, date):
        return raw
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI).date()


def in_range(meta: dict, since: date | None, until: date | None) -> bool:
    """True when the post's Shanghai posting date falls inside [since, until]."""
    if since is None and until is None:
        return True
    day = posted_day(meta)
    if day is None:
        return False
    if since is not None and day < since:
        return False
    if until is not None and day > until:
        return False
    return True


def coverage_line(records: list[tuple[Path, dict]]) -> str:
    """One-line data-coverage summary: how filled the learning fields are."""
    total = len(records)
    parts = []
    for field in COVERAGE_FIELDS:
        filled = sum(1 for _path, meta in records if str(meta.get(field) or "").strip())
        pct = (100 * filled / total) if total else 0
        parts.append(f"{field} {filled}/{total} ({pct:.0f}%)")
    return "data coverage: " + " ".join(parts)


def prune_snapshots(stats_dir: Path, *, keep: int, current: Path) -> list[Path]:
    """Delete the oldest `posts-*.csv` snapshots beyond `keep`, sparing `current`.

    Reporting used to leave every run's snapshot behind — thirteen files by 2026-09-19,
    including stale pre-backfill copies that no longer matched the archive. Analytics
    exports (`analytics_*.csv`, hand-supplied) are never touched.
    """
    if keep <= 0:
        return []
    snapshots = sorted(stats_dir.glob("posts-*.csv"))
    if len(snapshots) <= keep:
        return []
    removed: list[Path] = []
    for path in snapshots[:-keep] if current in snapshots[-keep:] else snapshots[: len(snapshots) - keep]:
        if path == current:
            continue
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            print(f"could not remove old snapshot {path}: {exc}", file=sys.stderr)
    if removed:
        print(f"pruned {len(removed)} old snapshot(s); keeping {keep}")
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", choices=["hit", "published"], help="filter by kind")
    ap.add_argument("--since", type=lambda raw: parse_day(raw, "--since"), help="posted_at >= YYYY-MM-DD (Asia/Shanghai)")
    ap.add_argument("--until", type=lambda raw: parse_day(raw, "--until"), help="posted_at <= YYYY-MM-DD (Asia/Shanghai)")
    ap.add_argument("--top", type=int, help="print top-N by likes")
    ap.add_argument("--no-csv", action="store_true", help="summary only")
    ap.add_argument(
        "--keep",
        type=int,
        default=5,
        help="How many posts-*.csv snapshots to keep in workspace/stats/ (default 5; 0 = keep all).",
    )
    args = ap.parse_args()

    root = find_root()
    posts_dir = root / "workspace" / "posts"
    stats_dir = root / "workspace" / "stats"
    if not posts_dir.is_dir():
        print(f"no posts dir yet: {posts_dir}")
        return 0

    errors: list[str] = []
    records = []
    for path, meta, _body in load_all(posts_dir, errors=errors):
        if args.kind and meta.get("kind") != args.kind:
            continue
        if not in_range(meta, args.since, args.until):
            continue
        records.append((path, meta))

    if errors:
        print(f"skipped {len(errors)} unreadable file(s):", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
    if records:
        print(coverage_line(records), file=sys.stderr)

    rows = [row_of(meta) for _path, meta in records]

    if rows and not args.no_csv:
        stats_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S")
        out = stats_dir / f"posts-{stamp}.csv"
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"csv: {out} ({len(rows)} rows)")
        prune_snapshots(stats_dir, keep=args.keep, current=out)

    # summary
    total = len(rows)
    if total == 0:
        print("no posts match")
        return 0
    likes = [to_int(r["likes"]) for r in rows]
    views = [to_int(r["views"]) for r in rows]
    likes_known = [v for v in likes if v is not None]
    views_known = [v for v in views if v is not None]
    print(f"posts: {total}")
    if views_known:
        print(f"views: sum={sum(views_known)} avg={sum(views_known)//len(views_known)}")
    if likes_known:
        print(f"likes: sum={sum(likes_known)} avg={sum(likes_known)//len(likes_known)}")
    if args.top and likes_known:
        top = sorted(rows, key=lambda r: to_int(r["likes"]) or 0, reverse=True)[: args.top]
        print("top by likes:")
        for r in top:
            print(f"  {r['likes']:>6} {r['id']} {r['post_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
