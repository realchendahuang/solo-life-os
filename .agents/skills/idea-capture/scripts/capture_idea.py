#!/usr/bin/env python3
"""Capture a verbatim idea as a timestamped X-Tiller inbox record."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

try:
    import yaml
except ImportError as _yaml_exc:
    yaml = None
    _YAML_IMPORT_ERROR = _yaml_exc


SHANGHAI = ZoneInfo("Asia/Shanghai")


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "contracts").is_dir():
            return parent
    raise RuntimeError("cannot locate the X-Tiller repository root")


def valid_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_record(args: argparse.Namespace, now: datetime) -> dict[str, object]:
    idea = args.idea.strip()
    if not idea:
        raise ValueError("idea must not be empty")
    urls = list(dict.fromkeys(args.source_url or []))
    invalid = [url for url in urls if not valid_url(url)]
    if invalid:
        raise ValueError(f"invalid source URL: {invalid[0]}")
    digest = hashlib.sha256(f"{now.isoformat()}|{idea}".encode()).hexdigest()[:10]
    return {
        "id": f"idea-{now:%Y%m%d-%H%M%S}-{digest}",
        "captured_at": now.isoformat(timespec="seconds"),
        "idea": idea,
        "intent": args.intent.strip() if args.intent and args.intent.strip() else None,
        "possible_pillar": (
            args.pillar.strip() if args.pillar and args.pillar.strip() else None
        ),
        "source_urls": urls,
        "notes": [note.strip() for note in (args.note or []) if note.strip()],
        "status": "captured",
    }


def render_idea(record: dict[str, object]) -> str:
    """Serialize an inbox idea as Markdown: frontmatter + verbatim idea body."""
    frontmatter = {
        k: v for k, v in record.items()
        if k != "idea" and v not in (None, [], "")
    }
    body = str(record.get("idea") or "").strip()
    sections: list[str] = []
    notes = [str(n) for n in (record.get("notes") or [])]
    urls = [str(u) for u in (record.get("source_urls") or [])]
    if notes:
        sections.append("## 备注\n\n" + "\n".join(f"- {n}" for n in notes))
    if urls:
        sections.append("## 来源\n\n" + "\n".join(f"- {u}" for u in urls))
    parts = ["---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip() + "\n---\n", f"\n{body}\n"]
    parts += [f"\n{section}\n" for section in sections]
    return "".join(parts)


def atomic_write(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(render_idea(record))
        temporary = Path(handle.name)
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a verbatim X-Tiller idea.")
    parser.add_argument("idea", help="The user's original wording.")
    parser.add_argument("--intent")
    parser.add_argument("--pillar")
    parser.add_argument("--source-url", action="append")
    parser.add_argument("--note", action="append")
    parser.add_argument("--output", type=Path, help="Custom path inside the repository.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = find_repo_root()
        now = datetime.now(SHANGHAI)
        record = build_record(args, now)
        if args.output:
            target = args.output if args.output.is_absolute() else repo / args.output
        else:
            target = repo / "workspace" / "inbox" / f"{record['id']}.md"
        try:
            target.resolve().relative_to(repo.resolve())
        except ValueError as exc:
            raise ValueError("--output must stay inside the X-Tiller repository") from exc

        if not args.dry_run:
            atomic_write(target, record)
            print(f"[idea-capture] saved: {target}", file=sys.stderr)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"idea-capture error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

