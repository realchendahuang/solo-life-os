#!/usr/bin/env python3
"""Promote a Candidate Signal from `workspace/candidates/` into `workspace/topics/`.

Connects the ingestion pipeline to the topic library by creating a new Topic
entry with full provenance tracking (source_refs, source_urls) and deduplication.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Import topic_store from topic-library skill
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / ".agents" / "skills" / "topic-library" / "scripts"))
import topic_store as store  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import presented_store as ps  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")


class PromoteError(RuntimeError):
    """User-facing candidate promotion error."""


def find_candidate_file(repo: Path, candidate_id_or_path: str) -> Path:
    target = Path(candidate_id_or_path)
    if target.is_file():
        return target
    candidates_dir = repo / "workspace" / "candidates"
    ledger = candidates_dir.parent / "candidates.jsonl"
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("id") == candidate_id_or_path:
                return ledger
    for p in candidates_dir.rglob("*.json"):
        if p.name == candidate_id_or_path or p.stem == candidate_id_or_path:
            return p
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("id") == candidate_id_or_path:
                return p
        except Exception:
            continue
    raise PromoteError(f"cannot locate candidate matching {candidate_id_or_path!r} under {candidates_dir} or candidates.jsonl")


def infer_pillar(candidate: dict[str, Any]) -> str:
    tags = candidate.get("tags", [])
    sid = candidate.get("source_id", "")
    if any(t in tags for t in ["friction:cost", "tool:breakout"]) or sid in [
        "v2ex-creative-feed",
        "producthunt-today",
        "owenyoung-blog",
        "danluu-blog",
        "paulgraham-essays",
    ]:
        return "indie-dev"
    if any(t in tags for t in ["friction:reality-check", "angle:debate"]) or sid in [
        "claude-code-releases",
        "openchamber-releases",
        "ollama-releases",
        "uv-releases",
        "llamacpp-releases",
        "huggingface-blog",
        "openai-api-changelog",
        "openai-product-release-notes",
        "google-gemini-api-changelog",
    ]:
        return "ai-coding-agents"
    return "ai-productivity"


def infer_column(candidate: dict[str, Any]) -> str:
    tags = candidate.get("tags", [])
    if "angle:debate" in tags or "blueprint:D" in tags:
        return "tech-debates"
    if "tool:breakout" in tags or "blueprint:E" in tags:
        return "hacker-craft"
    if "friction:cost" in tags or "blueprint:B" in tags:
        return "digital-sovereignty"
    return "hacker-craft"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Promote a Candidate Signal into the Topic Library."
    )
    parser.add_argument(
        "--candidate-id",
        required=True,
        help="ID or path of the candidate to promote.",
    )
    parser.add_argument(
        "--title",
        help="Custom short label for topic; defaults to candidate title.",
    )
    parser.add_argument(
        "--statement",
        help="Verbatim statement of the topic; defaults to candidate title.",
    )
    parser.add_argument(
        "--thesis",
        help="User stated position/thesis on the topic (optional).",
    )
    parser.add_argument(
        "--pillar",
        choices=["ai-coding-agents", "indie-dev", "ai-productivity", "insight-income", "language-learning"],
        help="Override inferred content pillar id.",
    )
    parser.add_argument(
        "--column",
        choices=["opc-handbook", "hacker-craft", "digital-sovereignty", "tech-debates", "ai-humanity"],
        help="Override inferred editorial column id.",
    )
    parser.add_argument(
        "--asset",
        choices=["repo", "ebook", "campaign", "monetization", "none"],
        default="none",
        help="Canonical target asset type (default 'none').",
    )
    parser.add_argument(
        "--library",
        type=Path,
        help="Alternative topic library directory (default workspace/topics/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect generated topic JSON without writing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = store.find_repo_root()
        library = store.resolve_library(repo, args.library)
        candidate_path = find_candidate_file(repo, args.candidate_id)
        candidate_data = json.loads(candidate_path.read_text(encoding="utf-8"))

        now = datetime.now(SHANGHAI)
        title = (args.title or candidate_data.get("title", "")).strip()
        statement = (args.statement or title).strip()
        if not title or not statement:
            raise PromoteError("candidate has empty title and no --statement was supplied")

        pillar = args.pillar or infer_pillar(candidate_data)
        column = args.column or infer_column(candidate_data)

        # Deduplication check against existing topics in library
        existing_topics = store.iter_topics(library)
        dup = store.find_duplicate(existing_topics, title=title, statement=statement)
        if dup:
            dup_path, dup_rec = dup
            raise PromoteError(
                f"topic already exists in library: {dup_rec.get('id')} ({dup_path.name})"
            )

        rel_candidate_ref = str(candidate_path.relative_to(repo))
        canonical_url = candidate_data.get("canonical_url") or candidate_data.get("source_url")
        source_urls = [canonical_url] if canonical_url else []

        hit_tags_note = ", ".join(candidate_data.get("tags", []))
        topic_record: dict[str, Any] = {
            "id": store.build_id(now, f"{title}|{statement}"),
            "created_at": now.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
            "title": title,
            "statement": statement,
            "status": "candidate",
            "source": "candidate",
            "source_refs": [rel_candidate_ref],
            "source_urls": source_urls,
            "pillar_id": pillar,
            "column_id": column,
            "target_asset": args.asset,
            "thesis": args.thesis.strip() if args.thesis and args.thesis.strip() else None,
            "notes": [
                f"Promoted from candidate {candidate_data.get('id')} ({candidate_data.get('source_id')}). Tags: {hit_tags_note}"
            ],
            "brief_ids": [],
            "draft_ids": [],
            "post_urls": [],
            "dropped_reason": None,
        }

        topic_file = library / f"{topic_record['id']}.md"
        if not args.dry_run:
            store.atomic_write(topic_file, topic_record)
            if candidate_data.get("id"):
                ps.mark_promoted(repo, candidate_data["id"], title)
            print(f"[promote-candidate] saved topic: {topic_file}", file=sys.stderr)

        print(
            json.dumps(
                {
                    "mode": "dry-run" if args.dry_run else "promoted",
                    "topic": topic_record,
                    "candidate_id": candidate_data.get("id"),
                    "candidate_ref": rel_candidate_ref,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (PromoteError, store.TopicError) as exc:
        print(f"[promote-candidate] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
