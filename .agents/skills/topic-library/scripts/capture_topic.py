#!/usr/bin/env python3
"""Add one topic to the X-Tiller topic library (`workspace/topics/`)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topic_store as store  # noqa: E402


def build_record(args: argparse.Namespace, now: datetime, repo: Path) -> dict[str, object]:
    statement = args.statement.strip()
    if not statement:
        raise store.TopicError("the topic statement must not be empty")
    title = (args.title or "").strip() or store.truncate_title(statement)
    if not title:
        raise store.TopicError("--title must not be empty")
    source_urls = list(dict.fromkeys(args.source_url or []))
    for url in source_urls:
        store.validate_http_url(url)
    source_refs = list(dict.fromkeys(args.source_ref or []))
    for ref in source_refs:
        store.validate_source_ref(repo, ref)
    # Simplified contract (2026-09-24): required core + optional legacy extras.
    # pillar/column/asset are only recorded when explicitly passed.
    record: dict[str, object] = {
        "id": store.build_id(now, f"{title}|{statement}"),
        "created_at": now.isoformat(timespec="seconds"),
        "title": title,
        "statement": statement,
        "status": "candidate",
    }
    if args.source != "user":
        record["source"] = args.source
    if source_refs:
        record["source_refs"] = source_refs
    if source_urls:
        record["source_urls"] = source_urls
    if args.pillar:
        record["pillar_id"] = args.pillar
    if args.column:
        record["column_id"] = args.column
    if args.asset:
        record["target_asset"] = args.asset
    if args.thesis and args.thesis.strip():
        record["thesis"] = args.thesis.strip()
    notes = [note.strip() for note in (args.note or []) if note.strip()]
    if notes:
        record["notes"] = notes
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add one topic to the X-Tiller topic library."
    )
    parser.add_argument("statement", help="The topic in the user's own wording, verbatim.")
    parser.add_argument("--title", help="Short label for scanning; defaults to the statement.")
    parser.add_argument("--pillar", choices=store.PILLAR_IDS, help="Legacy: canonical pillar id.")
    parser.add_argument("--column", choices=store.COLUMN_IDS, help="Legacy: canonical column id.")
    parser.add_argument("--asset", choices=store.TARGET_ASSETS, help="Legacy: target asset type.")
    parser.add_argument(
        "--source",
        choices=["user", "idea", "signal", "candidate", "brief"],
        default="user",
        help="Where the topic came from; 'user' when the user stated it themselves.",
    )
    parser.add_argument("--source-ref", action="append", help="Repository-relative source artifact.")
    parser.add_argument("--source-url", action="append")
    parser.add_argument("--thesis", help="The user's own stated position; omit when there is none.")
    parser.add_argument("--note", action="append")
    parser.add_argument("--library", type=Path, help="Alternative library inside this repository.")
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Store the topic even when the library already holds a matching one.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = store.find_repo_root()
        now = datetime.now(store.SHANGHAI)
        record = build_record(args, now, repo)
        library = store.resolve_library(repo, args.library)
        target = library / f"{record['id']}.md"

        duplicate = store.find_duplicate(
            store.iter_topics(library),
            title=str(record["title"]),
            statement=str(record["statement"]),
        )
        if duplicate and not args.allow_duplicate:
            path, existing = duplicate
            print(
                f"topic-library: already in the library as {existing.get('id')} "
                f"({existing.get('status')}): {existing.get('title')!r}\n"
                f"  file: {store.relative_label(repo, path)}\n"
                f"  update it with update_topic.py, or re-run with --allow-duplicate "
                f"to store this wording as a separate entry.",
                file=sys.stderr,
            )
            return 2

        if not args.dry_run:
            store.atomic_write(target, record)
            print(f"[topic-library] saved: {target}", file=sys.stderr)
        print(
            json.dumps(
                {
                    "mode": "dry-run" if args.dry_run else "saved",
                    "path": store.relative_label(repo, target),
                    "topic": record,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except store.TopicError as exc:
        print(f"topic-library error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
