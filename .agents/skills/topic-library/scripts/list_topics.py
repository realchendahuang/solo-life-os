#!/usr/bin/env python3
"""Read the X-Tiller topic library, grouped by lifecycle status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topic_store as store  # noqa: E402


def parse_filter(values: list[str] | None, allowed: tuple[str, ...], label: str) -> set[str]:
    if not values:
        return set()
    raw_chosen = {value.strip() for value in ",".join(values).split(",") if value.strip()}
    chosen = set()
    for val in raw_chosen:
        val_norm = store.STATUS_ALIASES.get(val, val) if label == "--status" else val
        chosen.add(val_norm)
    unknown = sorted(chosen - set(allowed))
    if unknown:
        raise store.TopicError(
            f"unknown {label}: {', '.join(unknown)}. Allowed: {', '.join(allowed)}"
        )
    return chosen


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List the X-Tiller topic library by status."
    )
    parser.add_argument("--status", action="append", help="Comma-separated status filter.")
    parser.add_argument("--pillar", action="append", help="Comma-separated pillar id filter.")
    parser.add_argument("--column", action="append", help="Comma-separated column id filter.")
    parser.add_argument("--asset", action="append", help="Comma-separated target asset filter.")
    parser.add_argument("--library", type=Path, help="Alternative library inside this repository.")
    parser.add_argument("--json", action="store_true", help="Print the selection as JSON.")
    return parser


def select(
    topics: list[tuple[Path, dict[str, object]]],
    statuses: set[str],
    pillars: set[str],
    columns: set[str] | None = None,
    assets: set[str] | None = None,
) -> list[dict[str, object]]:
    columns = columns or set()
    assets = assets or set()
    chosen = []
    for _path, record in topics:
        if statuses and record.get("status") not in statuses:
            continue
        if pillars and record.get("pillar_id") not in pillars:
            continue
        if columns and record.get("column_id") not in columns:
            continue
        if assets and record.get("target_asset") not in assets:
            continue
        chosen.append(record)
    # Newest first: the library is read to see what was just added and what is
    # still open, not to walk it chronologically.
    chosen.sort(key=lambda record: str(record.get("created_at", "")), reverse=True)
    return chosen


def render(records: list[dict[str, object]], total: int) -> str:
    if not records:
        if total == 0:
            return (
                f"选题库为空（{store.TOPIC_DIR[0]}/{store.TOPIC_DIR[1]}/）。"
                "用 capture_topic.py 存入第一条选题。"
            )
        return "没有符合筛选条件的选题。"

    counts = {status: 0 for status in store.STATUS_ORDER}
    for record in records:
        status = str(record.get("status"))
        counts[status] = counts.get(status, 0) + 1
    summary = " · ".join(
        f"{status}【{store.STATUS_LABELS.get(status, status)}】 {counts[status]}"
        for status in store.STATUS_ORDER
        if counts[status]
    )
    unwritten = counts.get("candidate", 0)
    lines = [f"选题库 {len(records)} 条（未写 {unwritten}）：{summary}"]

    for status in store.STATUS_ORDER:
        group = [record for record in records if record.get("status") == status]
        if not group:
            continue
        lines.append("")
        label = store.STATUS_LABELS.get(status, status)
        lines.append(f"{status} ({len(group)}) 【{label}】")
        for record in group:
            pillar = record.get("pillar_id") or "-"
            col = f" [{record.get('column_id')}]" if record.get("column_id") else ""
            asset = f" -> {record.get('target_asset')}" if record.get("target_asset") and record.get("target_asset") != "none" else ""
            created = str(record.get("created_at", ""))[:10]
            lines.append(
                f"  {record.get('id')}  [{pillar}]{col}  {record.get('title')}{asset}  ({created})"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = store.find_repo_root()
        statuses = parse_filter(args.status, store.STATUS_ORDER, "--status")
        pillars = parse_filter(args.pillar, store.PILLAR_IDS, "--pillar")
        columns = parse_filter(args.column, store.COLUMN_IDS, "--column")
        assets = parse_filter(args.asset, store.TARGET_ASSETS, "--asset")
        library = store.resolve_library(repo, args.library)
        topics = store.iter_topics(library)
        records = select(topics, statuses, pillars, columns, assets)
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": "listed",
                        "library": store.relative_label(repo, library),
                        "count": len(records),
                        "topics": records,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(render(records, len(topics)))
        return 0
    except store.TopicError as exc:
        print(f"topic-library error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
