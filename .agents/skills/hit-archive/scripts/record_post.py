#!/usr/bin/env python3
"""Record a just-published post into workspace/posts/ as its archive file.

Called by publish-x after the user reports the post went out, or by the user
directly. Creates post-YYYYMMDD-NNN.md with frontmatter per contracts/hit-post.md
(kind: published). Metrics are filled later by re-collection.

One entry per status id: re-running with the same --url is refused instead of
silently creating a duplicate archive file. --dry-run prints the planned write
without touching the archive.

Usage:
    python3 record_post.py --url https://x.com/.../status/123 --channel intent \
        [--draft-id draft-20260903-code-mode] [--text "正文全文"] [--dry-run]

Draft-file workflow retired 2026-09-24: writing happens in conversation, so
--draft-id is optional and no longer validated against workspace/drafts/ (which
is now empty). It is kept for loose bookkeeping only.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from frontmatter import (
    FrontmatterError,
    load,
    next_free_id,
    validate_post,
    write,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
STATUS_ID_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/[^/\s]+/status/(\d+)")


def load_topic_store():
    """Import the topic library's shared store on demand.

    Imported lazily rather than at module scope: a caller that has already put its own
    `topic_store` into sys.modules (the test suite does) must get that instance, or the
    two copies would carry different TopicError classes.
    """
    scripts = Path(__file__).resolve().parents[2] / "topic-library" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import topic_store

    return topic_store


def find_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "profile").is_dir():
            return parent
    raise SystemExit("cannot locate the X-Tiller repository root")


def status_id(url: str) -> str | None:
    """Numeric status id of an X post URL, or None when it has none."""
    match = STATUS_ID_RE.search(url or "")
    return match.group(1) if match else None


def find_existing(posts_dir: Path, sid: str) -> Path | None:
    """Archive file already holding this status id, if any."""
    for path in sorted(posts_dir.glob("*.md")):
        try:
            meta, _body = load(path)
        except FrontmatterError:
            continue
        url_id = status_id(str(meta.get("post_url") or ""))
        if url_id == sid or str(meta.get("id") or "") == sid:
            return path
    return None


def next_id(posts_dir: Path, day: str) -> str:
    prefix = f"post-{day}-"
    existing = {p.stem for p in posts_dir.glob(f"{prefix}*.md")}
    n = 1
    while f"{prefix}{n:03d}" in existing:
        n += 1
    return f"{prefix}{n:03d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True, help="X post URL (must contain /status/<numeric id>)")
    ap.add_argument(
        "--channel",
        required=True,
        choices=["intent", "buffer", "unknown"],
        help="publish channel; use 'unknown' for history imports (no draft required)",
    )
    ap.add_argument("--draft-id", help="loose bookkeeping only; drafts are no longer files (retired 2026-09-24)")
    ap.add_argument("--no-draft", action="store_true",
                    help="deprecated no-op (draft-id is already optional)")
    ap.add_argument("--topic-id",
                    help="advance this topic to published and attach the post URL to it")
    ap.add_argument("--no-topic", action="store_true",
                    help="skip the topic-library update even when --draft-id resolves to a topic")
    ap.add_argument("--text", help="full post text (optional at record time)")
    ap.add_argument("--posted-at", help="ISO8601, defaults to now")
    ap.add_argument("--pillar", help="content pillar")
    ap.add_argument("--tags", help="comma-separated tags")
    ap.add_argument("--structure", help="opinion|list|story|thread|quote")
    ap.add_argument("--hook", help="opening hook sentence")
    ap.add_argument("--dry-run", action="store_true", help="print the planned archive file without writing")
    args = ap.parse_args()

    root = find_root()
    posts_dir = root / "workspace" / "posts"
    sid = status_id(args.url)
    if not sid:
        print(f"--url must be an X status URL with a numeric id, got {args.url!r}", file=sys.stderr)
        return 2

    existing = find_existing(posts_dir, sid)
    if existing is not None:
        print(f"refusing to record a duplicate: status {sid} is already archived as {existing}",
              file=sys.stderr)
        return 2

    if args.no_draft:
        print("warning: recording without --draft-id; draft_id will be empty",
              file=sys.stderr)

    now = datetime.now(SHANGHAI)
    day = f"{now:%Y%m%d}"

    meta: dict = {
        "id": "post-00000000-000",  # placeholder; the real id is assigned below
        "kind": "published",
        "post_url": args.url,
        "posted_at": args.posted_at or now.isoformat(timespec="seconds"),
        "collected_at": now.isoformat(timespec="seconds"),
        "channel": args.channel,
    }
    if args.draft_id:
        meta["draft_id"] = args.draft_id
    if args.pillar:
        meta["pillar"] = args.pillar
    if args.tags:
        meta["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.structure:
        meta["structure"] = args.structure
    if args.hook:
        meta["hook"] = args.hook

    text = (args.text or "").strip("\n")
    annotation = "## 我的批注\n\n（发布后复盘：实际表现 vs 预期，为什么好/坏）\n\n## 数据回采\n"
    body = f"{text}\n\n{annotation}" if text else annotation

    if args.dry_run:
        post_id = next_id(posts_dir, day)
        target = posts_dir / f"{post_id}.md"
        meta["id"] = post_id
        try:
            validate_post(meta, target)
        except FrontmatterError as err:
            print(f"invalid archive entry: {err}", file=sys.stderr)
            return 2
        print(f"dry-run: would record {target}")
        print(f"  status={sid} channel={args.channel} draft_id={meta.get('draft_id', '(none)')}")
        if not meta.get("draft_id"):
            print("  draft_id is empty (pass --draft-id or --topic-id for bookkeeping)")
        if not args.no_topic:
            targets = args.topic_id or args.draft_id or "(none: pass --topic-id)"
            print(f"  would advance topic: {targets}")
        return 0

    # Claim the id by creating the file exclusively: two concurrent record runs used to
    # compute the same free number, and the later write silently replaced the earlier post.
    post_id, target = next_free_id(posts_dir, f"post-{day}-")
    meta["id"] = post_id
    try:
        validate_post(meta, target)
    except FrontmatterError as err:
        target.unlink(missing_ok=True)
        print(f"invalid archive entry: {err}", file=sys.stderr)
        return 2

    write(target, meta, body)
    print(f"recorded: {target}")

    # Keep the topic library in step with reality. A published post is exactly the
    # event the library otherwise never hears about, so recording it walks the same
    # topic forward (unless the caller opts out).
    if not args.no_topic and (args.topic_id or args.draft_id):
        topic_store = load_topic_store()
        try:
            advanced, warnings = topic_store.advance_to_published(
                root, post_url=args.url, topic_id=args.topic_id, draft_id=args.draft_id
            )
        except topic_store.TopicError as err:
            print(f"warning: topic library not updated: {err}", file=sys.stderr)
        else:
            for topic_id in advanced:
                print(f"topic advanced: {topic_id} → published")
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)

    print(f"next: 回采指标时补充 metrics → python3 stats.py 归入报表")
    return 0


if __name__ == "__main__":
    sys.exit(main())
