#!/usr/bin/env python3
"""Prune stale or unreferenced candidates from `workspace/candidates.jsonl`.

The pool is a single JSONL ledger (one JSON object per line) since the
2026-09-24 plain-text migration; the per-file `workspace/candidates/` directory
is retired.

Safety model:
- evidence lock: any candidate whose id, canonical_url, or source_url appears in
  a `workspace/topics/*.md` file is never pruned;
- `promoted` rows are never pruned — they are the lineage record for topics;
- `dismissed` rows are always eligible (already reviewed and rejected);
- `presented`/other rows become eligible only after `--days` of age;
- bulk deletion (>30% of the pool, or the entire pool) requires `--yes`;
- every deletion writes a manifest to `workspace/runs/` so a sweep can be
  reconstructed.

Note: pruning a row removes its canonical_url from the capture-time dedup
cache, so a still-enabled source could re-ingest the URL. `presented_ledger`
still marks it seen/dismissed, so it cannot be re-presented to the user.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


class PruneError(RuntimeError):
    """User-facing candidate prune error."""


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "contracts").is_dir():
            return parent
    raise PruneError("cannot locate X-Tiller repository root")


def candidates_ledger(repo: Path) -> Path:
    return repo / "workspace" / "candidates.jsonl"


def load_candidates(repo: Path) -> list[dict[str, Any]]:
    ledger = candidates_ledger(repo)
    if not ledger.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def write_candidates(repo: Path, rows: list[dict[str, Any]]) -> None:
    ledger = candidates_ledger(repo)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=ledger.parent, prefix=f".{ledger.name}.", delete=False
    ) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        temporary = Path(handle.name)
    temporary.replace(ledger)


def collect_evidence_locks(repo: Path) -> tuple[set[str], set[str]]:
    """Collect candidate ids and URLs referenced by topic entries."""
    locked_refs: set[str] = set()
    locked_urls: set[str] = set()

    topics_dir = repo / "workspace" / "topics"
    if topics_dir.is_dir():
        for path in topics_dir.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for token in text.replace(",", " ").split():
                if token.startswith("candidate-") or token.startswith("inbox/") or token.startswith("signals/"):
                    locked_refs.add(token)
                    locked_refs.add(Path(token).name)
            for token in text.split():
                if token.startswith(("http://", "https://")):
                    locked_urls.add(token.strip("<>()\"'"))
    return locked_refs, locked_urls


def write_prune_manifest(repo: Path, to_prune: list[tuple[dict[str, Any], str]]) -> Path:
    """Record every row about to be deleted, so an unwanted sweep can be reconstructed."""
    runs_dir = repo / "workspace" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S")
    manifest_path = runs_dir / f"prune-{stamp}.json"
    payload = {
        "pruned_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "count": len(to_prune),
        "entries": [
            {
                "id": row.get("id"),
                "canonical_url": row.get("canonical_url"),
                "source_id": row.get("source_id"),
                "reason": reason,
            }
            for row, reason in to_prune
        ],
    }
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def age_in_days(row: dict[str, Any], now: datetime) -> int:
    fetched_at = row.get("fetched_at") or row.get("created_at") or ""
    try:
        parsed = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        return (now - parsed.astimezone(SHANGHAI)).days
    except Exception:
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely prune stale unreferenced candidates from workspace/candidates.jsonl."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Prune non-dismissed candidates older than N days (default 30).",
    )
    parser.add_argument(
        "--action",
        choices=["discard", "all"],
        default="all",
        help="Prune only dismissed rows or dismissed plus stale rows (default all).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Perform actual deletion (default is dry-run preview).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview prune candidates without deleting (default mode).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm a bulk deletion (more than 30%% of the pool, or the entire pool).",
    )
    return parser


# Refusing tiny windows is the point: `--days 0 --delete` used to be able to erase the whole
# candidate pool, including WebBridge results that cannot be fetched again.
MIN_DAYS = 7
BULK_FRACTION = 0.30


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.days < MIN_DAYS:
            print(
                f"[prune-candidates] error: --days must be at least {MIN_DAYS} "
                f"(got {args.days}); a shorter window would sweep the pool",
                file=sys.stderr,
            )
            return 2

        repo = find_repo_root()
        rows = load_candidates(repo)
        if not rows:
            print(f"[prune-candidates] no candidates at {candidates_ledger(repo)}", file=sys.stderr)
            return 0

        locked_refs, locked_urls = collect_evidence_locks(repo)
        now = datetime.now(SHANGHAI)

        protected = 0
        to_prune: list[tuple[dict[str, Any], str]] = []
        kept: list[dict[str, Any]] = []

        for row in rows:
            cid = str(row.get("id") or "")
            urls = {
                str(row.get("canonical_url") or "").strip(),
                str(row.get("source_url") or "").strip(),
            }
            if cid in locked_refs or urls & locked_urls:
                protected += 1
                kept.append(row)
                continue

            status = str(row.get("status") or "")
            if status == "promoted":
                kept.append(row)
                continue

            dismissed = status == "dismissed"
            stale = age_in_days(row, now) >= args.days
            if args.action == "discard" and not dismissed:
                kept.append(row)
                continue

            if dismissed or stale:
                reason = "dismissed" if dismissed else f"stale ({age_in_days(row, now)}d >= {args.days}d)"
                to_prune.append((row, reason))
            else:
                kept.append(row)

        scanned = len(rows)
        do_delete = args.delete and not args.dry_run
        bulk = bool(to_prune) and (
            len(to_prune) == scanned or len(to_prune) / max(scanned, 1) > BULK_FRACTION
        )

        print("=" * 80)
        print("X-Tiller Candidate Pool Housekeeping Report")
        print("=" * 80)
        print(f"Candidates scanned:    {scanned}")
        print(f"Evidence/promoted locked: {protected} + promoted (never pruned)")
        print(f"Eligible for pruning:  {len(to_prune)}")
        print(f"Execution mode:        {'ACTUAL DELETION' if do_delete else 'DRY-RUN PREVIEW'}")
        print("=" * 80)

        if do_delete and bulk and not args.yes:
            print(
                f"\nRefusing to delete {len(to_prune)} of {scanned} candidates "
                f"(more than {int(BULK_FRACTION * 100)}%): re-run with --yes to confirm.",
                file=sys.stderr,
            )
            return 2

        if to_prune and not do_delete:
            print("\nPreview of top 10 prune candidates:")
            for row, reason in to_prune[:10]:
                print(f"  - {row.get('id')} ({reason}) {(row.get('title_zh') or row.get('title') or '')[:60]}")
            if len(to_prune) > 10:
                print(f"  ... and {len(to_prune) - 10} more.")
            print("\nTo delete these candidates, run with: --delete")
        elif to_prune and do_delete:
            manifest = write_prune_manifest(repo, to_prune)
            write_candidates(repo, kept)
            print(
                f"\nSuccessfully pruned {len(to_prune)} candidates "
                f"({scanned} -> {len(kept)} rows in candidates.jsonl)."
            )
            print(f"Deletion manifest: {manifest.relative_to(repo)}")
        else:
            print("\nCandidate pool is healthy. No stale unreferenced candidates to prune.")

        return 0
    except PruneError as exc:
        print(f"[prune-candidates] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
