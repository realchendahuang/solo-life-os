#!/usr/bin/env python3
"""Triage and inspect candidates in `workspace/candidates/` by Blueprint, action, or query.

Allows the user and agent to quickly scan high-hit signals captured from official
changelogs, RSS feeds, and X-fetch, and select which candidates to promote into topics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import presented_store as ps


class TriageError(RuntimeError):
    """User-facing candidate triage error."""


def effective_published_at(candidate: dict[str, Any]) -> str:
    """The publish time worth showing, or "" when there is none.

    Records written before 2026-09-20 stored the fetch time whenever a feed date could not
    be parsed, so `published_at == fetched_at` there is a fabrication, not a coincidence.
    Treat that pair as "unknown" rather than displaying a fake publish date: 1272 of the
    1506 rows collected on 2026-09-19 have exactly this shape.
    """
    published = str(candidate.get("published_at") or "").strip()
    fetched = str(candidate.get("fetched_at") or "").strip()
    if not published:
        return ""
    if fetched and published == fetched:
        return ""
    return published


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "contracts").is_dir():
            return parent
    raise TriageError("cannot locate X-Tiller repository root")


def load_candidates(candidates_dir: Path) -> list[dict[str, Any]]:
    """Read candidates from the JSONL ledger, falling back to legacy per-file dirs.

    `candidates_dir` is `workspace/candidates/`; the ledger lives one level up at
    `workspace/candidates.jsonl`. Legacy per-file JSON (pre 2026-09-24) is still
    readable so nothing goes dark during the migration window.
    """
    candidates: list[dict[str, Any]] = []
    ledger = candidates_dir.parent / "candidates.jsonl"
    if ledger.exists():
        for lineno, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("id", "").startswith("candidate-"):
                data["_file_path"] = f"{ledger.relative_to(ledger.parents[2] if len(ledger.parents) > 2 else ledger.anchor)}:{lineno}"
                candidates.append(data)
    elif candidates_dir.is_dir():
        for path in candidates_dir.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("id", "").startswith("candidate-"):
                    data["_file_path"] = str(path)
                    candidates.append(data)
            except Exception:
                continue
    candidates.sort(
        key=lambda x: str(x.get("published_at") or x.get("fetched_at") or ""),
        reverse=True,
    )
    return candidates


def filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    action: str | None = None,
    blueprint: str | None = None,
    source: str | None = None,
    query: str | None = None,
    unseen_only: bool = False,
    ledger: dict[str, Any] | None = None,
    topic_cids: set[str] | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    bp_tag = f"blueprint:{blueprint.upper()}" if blueprint else None
    query_lower = query.lower() if query else None
    source_lower = source.lower() if source else None

    for c in candidates:
        cid = c.get("id", "")
        if unseen_only and ledger is not None and topic_cids is not None:
            if ps.is_seen(cid, ledger, topic_cids):
                continue

        if action and action != "all" and c.get("suggested_action") != action:
            continue
        if bp_tag and bp_tag not in c.get("tags", []):
            continue
        if source_lower and source_lower not in c.get("source_id", "").lower():
            continue
        if query_lower:
            text = f"{c.get('title', '')} {c.get('excerpt', '')}".lower()
            if query_lower not in text:
                continue
        filtered.append(c)
    return filtered


def format_blueprint_tags(tags: list[str]) -> str:
    bp_parts = []
    for t in tags:
        if t.startswith("blueprint:"):
            letter = t.split(":", 1)[1]
            bp_parts.append(f"Blueprint {letter}")
        elif t.startswith("friction:") or t.startswith("tool:") or t.startswith("angle:"):
            bp_parts.append(t)
    return ", ".join(bp_parts) if bp_parts else "none"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Triage and inspect candidates in workspace/candidates/."
    )
    parser.add_argument(
        "--action",
        choices=["brief", "watch", "discard", "all"],
        default=None,
        help="Filter by suggested_action (defaults to 'all' in broad mode, otherwise None).",
    )
    parser.add_argument(
        "--blueprint",
        choices=["A", "B", "C", "D", "E"],
        help="Filter candidates matching specific Hit-Playbook Blueprint (A-E).",
    )
    parser.add_argument(
        "--source",
        help="Filter candidates by source ID (e.g. 'v2ex-tech-feed', 'github-changelog').",
    )
    parser.add_argument(
        "--query",
        "-q",
        help="Search keyword in title or excerpt.",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=0,
        help="Maximum candidates to display (default 0 for unlimited, or specify N for top N).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON array instead of human-readable summary.",
    )
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Display editorial daily digest grouped by Hit-Playbook Blueprints (A-E).",
    )
    parser.add_argument(
        "--include-seen",
        action="store_true",
        help="Include candidates that were already presented, dismissed, or promoted.",
    )
    parser.add_argument(
        "--mark-presented",
        action="store_true",
        help="Mark displayed candidates as presented in workspace/candidates/presented_ledger.json.",
    )
    parser.add_argument(
        "--dismiss",
        nargs="+",
        metavar="CANDIDATE_ID",
        help="Permanently dismiss one or more candidate IDs.",
    )
    parser.add_argument(
        "--broad",
        action="store_true",
        help="Broad discovery mode: include both brief and watch items without restrictive keyword filtering.",
    )
    return parser


def render_digest(
    all_candidates: list[dict[str, Any]],
    per_blueprint: int = 5,
    *,
    unseen_only: bool = True,
    ledger: dict[str, Any] | None = None,
    topic_cids: set[str] | None = None,
    mark_presented: bool = False,
    repo: Path | None = None,
) -> None:
    blueprints = [
        ("B", "Blueprint B: 算账与极端 ROI (成本/省钱/价格战/额度)"),
        ("A", "Blueprint A: 祛魅·踩坑·实测反差 (翻车/降智/漏洞/故障)"),
        ("E", "Blueprint E: 神器·微型交付·单点突破 (做了一个/开源工具/Harness)"),
        ("D", "Blueprint D: 路线争议与选型站队 (争论/评测/为什么不用)"),
    ]
    brief_candidates = [c for c in all_candidates if c.get("suggested_action") == "brief"]
    if unseen_only and ledger is not None and topic_cids is not None:
        brief_candidates = [c for c in brief_candidates if not ps.is_seen(c.get("id", ""), ledger, topic_cids)]

    print("=" * 80)
    print(f"X-Tiller Hit-Playbook Fresh Candidate Digest ({len(brief_candidates)} high-potential unseen items)")
    print("=" * 80)

    displayed_cids = []
    title_map = {}
    for bp_code, bp_name in blueprints:
        tag = f"blueprint:{bp_code}"
        matches = [c for c in brief_candidates if tag in c.get("tags", [])]
        print(f"\n【{bp_name}】— {len(matches)} 条新鲜候选")
        if not matches:
            print("  (暂无该蓝图新鲜候选)")
            continue
        for idx, c in enumerate(matches[:per_blueprint], 1):
            cid = c.get("id", "")
            sid = c.get("source_id", "")
            title = c.get("title", "")
            url = c.get("canonical_url") or c.get("source_url", "")
            if cid:
                displayed_cids.append(cid)
                title_map[cid] = title
            print(f"  {idx}. [{cid}] ({sid})")
            print(f"     {title}")
            print(f"     {url}")

    if mark_presented and displayed_cids and repo:
        ps.mark_presented(repo, displayed_cids, title_map)
        print(f"\n[triage-candidates] marked {len(displayed_cids)} digest candidate(s) as presented.", file=sys.stderr)

    print("\n" + "=" * 80)
    print("Promote command: python3 .agents/skills/source-registry/scripts/promote_candidate.py --candidate-id <ID>")
    print("=" * 80)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = find_repo_root()
        if args.dismiss:
            ps.mark_dismissed(repo, args.dismiss)
            print(f"[triage-candidates] permanently dismissed {len(args.dismiss)} candidate(s): {', '.join(args.dismiss)}")
            return 0

        candidates_dir = repo / "workspace" / "candidates"
        all_candidates = load_candidates(candidates_dir)
        ledger = ps.load_ledger(repo)
        topic_cids = ps.get_topic_candidate_ids(repo)
        unseen_only = not args.include_seen

        if args.digest:
            render_digest(
                all_candidates,
                per_blueprint=args.limit if args.limit > 0 else 5,
                unseen_only=unseen_only,
                ledger=ledger,
                topic_cids=topic_cids,
                mark_presented=args.mark_presented,
                repo=repo,
            )
            return 0

        effective_action = args.action
        if args.broad and effective_action is None:
            effective_action = "all"

        seen_excluded = sum(1 for c in all_candidates if ps.is_seen(c.get("id", ""), ledger, topic_cids)) if unseen_only else 0
        matched = filter_candidates(
            all_candidates,
            action=effective_action,
            blueprint=args.blueprint,
            source=args.source,
            query=args.query,
            unseen_only=unseen_only,
            ledger=ledger,
            topic_cids=topic_cids,
        )

        display_list = matched[: args.limit] if args.limit > 0 else matched

        if args.json:
            print(json.dumps(display_list, ensure_ascii=False, indent=2))
            if args.mark_presented and display_list:
                cids = [c["id"] for c in display_list if c.get("id")]
                title_map = {c["id"]: c.get("title", "") for c in display_list if c.get("id")}
                ps.mark_presented(repo, cids, title_map)
            return 0

        print("=" * 80)
        seen_note = f" ({seen_excluded} previously seen/promoted excluded)" if unseen_only else ""
        print(
            f"X-Tiller Candidates: {len(matched)} fresh candidates{seen_note} (out of {len(all_candidates)} total)"
        )
        if args.blueprint:
            print(f"Filter Blueprint: Blueprint {args.blueprint.upper()}")
        if effective_action:
            print(f"Filter Action: {effective_action}")
        if args.source:
            print(f"Filter Source: {args.source}")
        if args.query:
            print(f"Search Query: {args.query}")
        if args.broad:
            print("Mode: Broad Discovery (all non-spam items included)")
        print("=" * 80)

        if not display_list:
            print("No matching fresh candidates found (all items have been presented or filtered).")
            print("Use --include-seen to review previously presented candidates.")
            return 0

        for idx, c in enumerate(display_list, 1):
            cid = c.get("id", "unknown")
            sid = c.get("source_id", "unknown")
            action = c.get("suggested_action", "watch")
            pub = effective_published_at(c)
            if not pub:
                pub = str(c.get("fetched_at") or "")
                pub_label = f"{pub[:16]} (fetched; publish date unknown)"
            else:
                pub_label = pub[:16]
            title = c.get("title", "(no title)")
            url = c.get("canonical_url") or c.get("source_url", "")
            bp_str = format_blueprint_tags(c.get("tags", []))
            excerpt = (c.get("excerpt") or "").strip()
            if len(excerpt) > 160:
                excerpt = excerpt[:157] + "..."

            print(f"[{idx}] {cid} ({sid} · {pub_label})")
            print(f"    Action:     {action.upper()}")
            print(f"    Hit Tags:   {bp_str}")
            print(f"    Title:      {title}")
            print(f"    URL:        {url}")
            print(f"    Excerpt:    {excerpt}")
            print("-" * 80)

        if args.mark_presented and display_list:
            cids = [c["id"] for c in display_list if c.get("id")]
            title_map = {c["id"]: c.get("title", "") for c in display_list if c.get("id")}
            ps.mark_presented(repo, cids, title_map)
            print(f"\n[triage-candidates] marked {len(cids)} displayed candidate(s) as presented in presented_ledger.json", file=sys.stderr)

        print("\nNext step: run promote_candidate.py --candidate-id <ID> to advance into topic library.")
        return 0
    except TriageError as exc:
        print(f"[triage-candidates] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
