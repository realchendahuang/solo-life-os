#!/usr/bin/env python3
"""Advance one topic in the X-Tiller topic library."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topic_store as store  # noqa: E402


BRIEF_ID_RE = re.compile(r"^brief-")
DRAFT_ID_RE = re.compile(r"^draft-")


def append_unique(existing: list, values: list[str] | None) -> list:
    return list(dict.fromkeys([*existing, *(value.strip() for value in (values or []) if value.strip())]))


def apply_changes(
    record: dict[str, object], args: argparse.Namespace, repo: Path
) -> list[str]:
    """Mutate `record` in place and return the names of the fields that changed."""
    changed: list[str] = []

    def assign(field: str, value: object) -> None:
        if record.get(field) != value:
            record[field] = value
            changed.append(field)

    if args.status:
        assign("status", store.STATUS_ALIASES.get(args.status, args.status))
    if args.title and args.title.strip():
        assign("title", args.title.strip())
    if args.pillar:
        assign("pillar_id", args.pillar)
    if args.column:
        assign("column_id", args.column)
    if args.asset:
        assign("target_asset", args.asset)
    if args.thesis and args.thesis.strip():
        assign("thesis", args.thesis.strip())
    if args.note:
        assign("notes", append_unique(list(record.get("notes") or []), args.note))
    if args.brief_id:
        for value in args.brief_id:
            if not BRIEF_ID_RE.match(value.strip()):
                raise store.TopicError(f"invalid --brief-id {value!r}: expected brief-...")
        assign("brief_ids", append_unique(list(record.get("brief_ids") or []), args.brief_id))
    if args.draft_id:
        for value in args.draft_id:
            if not DRAFT_ID_RE.match(value.strip()):
                raise store.TopicError(f"invalid --draft-id {value!r}: expected draft-...")
        assign("draft_ids", append_unique(list(record.get("draft_ids") or []), args.draft_id))
    if args.post_url:
        for value in args.post_url:
            store.validate_http_url(value.strip())
        assign("post_urls", append_unique(list(record.get("post_urls") or []), args.post_url))
    if args.dropped_reason and args.dropped_reason.strip():
        assign("dropped_reason", args.dropped_reason.strip())

    # The two lifecycle states that would otherwise be unfalsifiable. The
    # contract's if/then rules say the same thing; failing here turns a gate
    # failure into an actionable message at the moment of the transition.
    if record.get("status") == "published" and not record.get("post_urls"):
        raise store.TopicError(
            "status published needs the post itself: pass --post-url "
            "https://x.com/realchendahuang/status/..."
        )
    if record.get("status") == "dropped" and not record.get("dropped_reason"):
        raise store.TopicError(
            "status dropped needs the reason, because the reason is what the "
            "account learns from: pass --dropped-reason \"...\""
        )

    return changed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Advance one topic in the X-Tiller topic library."
    )
    parser.add_argument("--id", required=True, help="Topic id, for example topic-20260919-153012-ab12cd34ef.")
    parser.add_argument(
        "--status",
        choices=(
            "candidate", "parked", "published", "dropped",
            "待写库", "待写", "素材库", "已发布", "已弃用", "待发", "素材", "已发", "弃用"
        ),
        help="Live lifecycle states: 待写库(candidate), 素材库(parked), 已发布(published), 已弃用(dropped).",
    )
    parser.add_argument("--title")
    parser.add_argument("--pillar", choices=store.PILLAR_IDS)
    parser.add_argument("--column", choices=store.COLUMN_IDS, help="Canonical editorial column id.")
    parser.add_argument("--asset", choices=store.TARGET_ASSETS, help="Canonical target asset type.")
    parser.add_argument("--thesis", help="The user's own stated position.")
    parser.add_argument("--note", action="append")
    parser.add_argument("--brief-id", action="append")
    parser.add_argument("--draft-id", action="append")
    parser.add_argument("--post-url", action="append")
    parser.add_argument("--dropped-reason")
    parser.add_argument("--library", type=Path, help="Alternative library inside this repository.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = store.find_repo_root()
        library = store.resolve_library(repo, args.library)
        path = library / f"{args.id}.md"
        if not path.is_file():
            raise store.TopicError(
                f"unknown topic id {args.id!r}: no file at {store.relative_label(repo, path)}"
            )
        record = store.load_topic(path)
        changed = apply_changes(record, args, repo)
        if changed:
            record["updated_at"] = datetime.now(store.SHANGHAI).isoformat(timespec="seconds")
        if changed and not args.dry_run:
            store.atomic_write(path, record)
            print(f"[topic-library] updated: {path}", file=sys.stderr)
        mode = "unchanged" if not changed else ("dry-run" if args.dry_run else "updated")
        print(
            json.dumps(
                {
                    "mode": mode,
                    "path": store.relative_label(repo, path),
                    "changed": changed,
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
