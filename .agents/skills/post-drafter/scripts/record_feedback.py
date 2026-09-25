#!/usr/bin/env python3
"""Append one explicit user-feedback record for later X-Tiller review."""

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

import yaml


SHANGHAI = ZoneInfo("Asia/Shanghai")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class FeedbackError(RuntimeError):
    """A concise feedback-recording failure safe to show to the user."""


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "profile").is_dir():
            return parent
    raise FeedbackError("cannot locate the X-Tiller repository root")


def build_record(
    args: argparse.Namespace, now: datetime, *, draft_resolved: bool = False
) -> dict[str, object]:
    draft_id = args.draft_id.strip()
    if not draft_id:
        raise FeedbackError("--draft-id must not be empty")
    reason = args.reason.strip() if args.reason and args.reason.strip() else None
    constraints = list(
        dict.fromkeys(value.strip() for value in args.constraint if value.strip())
    )
    return {
        "id": f"feedback-{now:%Y%m%d-%H%M%S}-{uuid4().hex[:8]}",
        "recorded_at": now.isoformat(timespec="seconds"),
        "draft_id": draft_id,
        "outcome": args.outcome,
        "reason": reason,
        "constraints": constraints,
        "draft_resolved": draft_resolved,
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
        raise FeedbackError(f"cannot write feedback ledger: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record explicit user feedback for a selected X-Tiller draft."
    )
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--outcome", required=True, choices=["edited", "approved", "rejected"])
    parser.add_argument("--reason", help="User-stated reason; omit when no reason was given.")
    parser.add_argument("--constraint", action="append", default=[], help="Repeat for user-stated constraints.")
    parser.add_argument("--ledger", type=Path, help="Feedback JSONL inside this repository.")
    parser.add_argument("--dry-run", action="store_true", help="Print the record without writing it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = find_repo_root()
        ledger = args.ledger or repo / "workspace" / "feedback" / "ledger.jsonl"
        ledger = ledger if ledger.is_absolute() else repo / ledger
        try:
            ledger.resolve().relative_to(repo.resolve())
        except ValueError as exc:
            raise FeedbackError("--ledger must stay inside the X-Tiller repository") from exc
        draft_id = args.draft_id.strip()
        if not draft_id:
            raise FeedbackError("--draft-id must not be empty")
        # Draft-file workflow retired 2026-09-24: drafts are no longer files, so
        # every draft_id records with draft_resolved=false. It is loose
        # bookkeeping only — the reason and constraints are what matter.
        draft_resolved = False
        record = build_record(args, datetime.now(SHANGHAI), draft_resolved=draft_resolved)
        if not args.dry_run:
            append_jsonl(ledger, record)
            print(f"[post-drafter] saved feedback: {ledger}", file=sys.stderr)
        print(
            json.dumps(
                {
                    "mode": "dry-run" if args.dry_run else "saved",
                    "ledger": str(ledger.relative_to(repo)),
                    "feedback": record,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except FeedbackError as exc:
        print(f"post-drafter error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
