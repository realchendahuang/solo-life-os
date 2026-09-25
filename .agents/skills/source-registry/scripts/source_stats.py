#!/usr/bin/env python3
"""Calculate ingestion efficiency, hit-playbook coverage, and topic conversion per data source.

Helps @realchendahuang and the agent evaluate which registered sources produce the
highest signal-to-noise ratio and which sources can be safely retired or tuned.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


class StatsError(RuntimeError):
    """User-facing source stats error."""


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "contracts").is_dir():
            return parent
    raise StatsError("cannot locate X-Tiller repository root")


def load_registry(repo: Path) -> list[dict[str, Any]]:
    path = repo / "sources" / "registry.json"
    if not path.is_file():
        raise StatsError(f"registry file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("sources", [])


def collect_promoted_source_counts(repo: Path) -> dict[str, int]:
    promoted_counts: dict[str, int] = defaultdict(int)
    topics_dir = repo / "workspace" / "topics"
    if not topics_dir.is_dir():
        return promoted_counts

    # Promoted tracking now reads candidates.jsonl: a candidate id promoted into a
    # topic is marked in presented_ledger via mark_promoted; source attribution is
    # in the candidate record itself.
    ledger = topics_dir.parent / "candidates.jsonl"
    promoted_ids: set[str] = set()
    if topics_dir.is_dir():
        for path in topics_dir.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for token in text.split():
                if token.startswith("candidate-"):
                    promoted_ids.add(token.strip("(),.：;:'\""))
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = data.get("source_id")
            cid = data.get("id")
            if sid and cid and cid in promoted_ids:
                promoted_counts[sid] += 1
    return promoted_counts


def analyze_sources(repo: Path) -> list[dict[str, Any]]:
    sources = load_registry(repo)
    candidates_dir = repo / "workspace" / "candidates"
    promoted_counts = collect_promoted_source_counts(repo)

    stats_map: dict[str, dict[str, Any]] = {}
    for s in sources:
        sid = s["id"]
        stats_map[sid] = {
            "source_id": sid,
            "name": s.get("name", sid),
            "priority": s.get("priority", "P1"),
            "source_type": s.get("source_type", "rss"),
            "enabled": s.get("enabled", True),
            "total_candidates": 0,
            "brief_count": 0,
            "watch_count": 0,
            "discard_count": 0,
            "blueprints": {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0},
            "promoted_topics": promoted_counts.get(sid, 0),
        }

    if candidates_dir.is_dir():
        for p in candidates_dir.rglob("*.json"):
            try:
                cand = json.loads(p.read_text(encoding="utf-8"))
                sid = cand.get("source_id")
                if not sid or sid not in stats_map:
                    continue

                entry = stats_map[sid]
                entry["total_candidates"] += 1
                action = cand.get("suggested_action", "watch")
                if action == "brief":
                    entry["brief_count"] += 1
                elif action == "watch":
                    entry["watch_count"] += 1
                elif action == "discard":
                    entry["discard_count"] += 1

                tags = cand.get("tags") or []
                for bp in ["A", "B", "C", "D", "E"]:
                    if f"blueprint:{bp}" in tags:
                        entry["blueprints"][bp] += 1
            except Exception:
                continue

    result_list = list(stats_map.values())
    result_list.sort(key=lambda x: (x["promoted_topics"], x["brief_count"], x["total_candidates"]), reverse=True)
    return result_list


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Display data source efficiency, hit coverage, and topic conversion scorecard."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON analysis.",
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Only display sources that have generated at least 1 candidate.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = find_repo_root()
        stats = analyze_sources(repo)

        if args.active_only:
            stats = [s for s in stats if s["total_candidates"] > 0]

        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
            return 0

        print("=" * 105)
        print("X-Tiller Source Ingestion & Hit Conversion Scorecard")
        print("=" * 105)
        print(
            f"{'Source ID':<36} {'Priority':<9} {'Candidates':<12} {'Brief-Ratio':<13} {'Blueprints (B/A/E/D)':<23} {'Topics'}"
        )
        print("-" * 105)

        for s in stats:
            sid = s["source_id"]
            if len(sid) > 34:
                sid = sid[:31] + "..."
            pri = s["priority"]
            total = s["total_candidates"]
            brief = s["brief_count"]
            ratio_str = f"{int(brief / total * 100)}%" if total > 0 else "0%"
            bp = s["blueprints"]
            bp_str = f"{bp['B']}/{bp['A']}/{bp['E']}/{bp['D']}"
            topics = s["promoted_topics"]

            print(f"{sid:<36} {pri:<9} {total:<12} {ratio_str:<13} {bp_str:<23} {topics}")

        print("=" * 105)
        print(
            "Metrics note: Blueprints (B/A/E/D) = Cost & ROI / Reality Check / Breakout Tool / Debate coverage."
        )
        print("Run triage_candidates.py --digest to view candidate details by blueprint.")
        return 0
    except StatsError as exc:
        print(f"[source-stats] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
