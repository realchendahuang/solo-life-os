#!/usr/bin/env python3
"""Collect an X post into workspace/posts/ as a Markdown archive file.

Fetches the post text via the x-fetch skill when a URL is given, or accepts
text directly. Writes one md file with YAML frontmatter per the hit-post
contract: contracts/hit-post.md.

One entry per status id: a URL whose numeric status id already exists in the
archive is skipped, never duplicated. A real --url is required unless the
caller explicitly passes --no-url (only then may post_url stay empty).

Usage:
    python3 archive_hit.py --url https://x.com/.../status/123 [--tags AI实战,CodingAgent]
    python3 archive_hit.py --no-url --text "帖子全文..."
    python3 archive_hit.py --list-file ./urls.txt [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from frontmatter import load_all, next_free_id, validate_post, write

SHANGHAI = ZoneInfo("Asia/Shanghai")
XFETCH = Path(__file__).resolve().parents[2] / "x-fetch" / "scripts" / "fetch_tweet.py"
STATUS_ID_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/[^/\s]+/status/(\d+)")
# x-fetch --text-only decorates the payload: "@handle: " prefix and a trailing
# "点赞: N | 转推: N | 浏览: N" stats line.
STATS_LINE_RE = re.compile(
    r"^(?:点赞|Likes):\s*\d+\s*\|\s*(?:转推|Retweets):\s*\d+\s*\|\s*(?:浏览|Views):\s*\d+\s*$"
)
HANDLE_PREFIX_RE = re.compile(r"^@[A-Za-z0-9_]+:\s?")


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


def strip_text_decorations(raw: str) -> str:
    """Undo x-fetch --text-only formatting, deterministically."""
    lines = raw.replace("\r\n", "\n").strip("\n").split("\n")
    while lines and (not lines[-1].strip() or STATS_LINE_RE.match(lines[-1].strip())):
        lines.pop()
    if lines:
        lines[0] = HANDLE_PREFIX_RE.sub("", lines[0], count=1)
    return "\n".join(lines).strip("\n")


def next_id(posts_dir: Path, kind: str, day: str) -> str:
    prefix = f"{kind}-{day}-"
    existing = {p.stem for p in posts_dir.glob(f"{prefix}*.md")}
    n = 1
    while f"{prefix}{n:03d}" in existing:
        n += 1
    return f"{prefix}{n:03d}"


def existing_by_status(posts_dir: Path) -> dict[str, Path]:
    """Map status id -> archive file for every entry with a real post_url."""
    errors: list[str] = []
    found: dict[str, Path] = {}
    for path, meta, _body in load_all(posts_dir, errors=errors):
        sid = status_id(str(meta.get("post_url") or ""))
        if sid:
            found.setdefault(sid, path)
    for err in errors:
        print(f"skipped unreadable file: {err}", file=sys.stderr)
    return found


def fetch_text(url: str) -> str:
    """Fetch a single post via x-fetch (venv-free shim), decorations removed."""
    if not XFETCH.exists():
        raise SystemExit("x-fetch script not found; use --text or --no-url instead")
    result = subprocess.run(
        [sys.executable, str(XFETCH), "--url", url, "--text-only"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise SystemExit(f"x-fetch failed: {result.stderr[:400]}")
    out = strip_text_decorations(result.stdout)
    if not out:
        raise SystemExit(f"x-fetch returned nothing for {url}")
    return out


def parse_metrics(raw: str | None) -> dict[str, int] | None:
    if not raw:
        return None
    metrics: dict[str, int] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        try:
            metrics[key.strip()] = int(value.strip())
        except ValueError:
            continue
    return metrics or None


def build_meta(args: argparse.Namespace, post_id: str, url: str) -> dict:
    meta = {
        "id": post_id,
        "kind": "hit",
        "post_url": url,
        "collected_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "channel": "unknown",
    }
    if args.posted_at:
        meta["posted_at"] = args.posted_at
    if args.pillar:
        meta["pillar"] = args.pillar
    if args.tags:
        meta["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.structure:
        meta["structure"] = args.structure
    if args.hook:
        meta["hook"] = args.hook
    metrics = parse_metrics(args.metrics)
    if metrics:
        meta["metrics"] = metrics
    return meta


def archive_one(posts_dir: Path, args: argparse.Namespace, url: str, text: str) -> Path:
    day = datetime.now(SHANGHAI).strftime("%Y%m%d")
    meta_template = build_meta(args, "hit-00000000-000", url)
    validate_post(meta_template)
    body = text.strip("\n") + "\n\n## 我的批注\n\n（为什么这条值得学/为什么它能爆？）\n"
    # claim first, then fill in the real id: the exclusive create is what stops a
    # concurrent run from picking the same number and overwriting this post.
    post_id, target = next_free_id(posts_dir, f"hit-{day}-")
    meta = {**meta_template, "id": post_id}
    validate_post(meta)
    write(target, meta, body)
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="X post URL to fetch text from")
    ap.add_argument("--text", help="Post text directly (skip fetching; requires --no-url)")
    ap.add_argument("--no-url", action="store_true",
                    help="archive without a post URL (post_url stays empty; cannot dedupe)")
    ap.add_argument("--list-file", help="File with one URL per line")
    ap.add_argument("--posted-at", help="Original posted_at (ISO8601)")
    ap.add_argument("--pillar", help="Content pillar, e.g. AI实战")
    ap.add_argument("--tags", help="Comma-separated tags")
    ap.add_argument("--structure", help="opinion|list|story|thread|quote")
    ap.add_argument("--hook", help="Opening hook sentence")
    ap.add_argument("--metrics", help="views=51200,likes=842,...")
    ap.add_argument("--dry-run", action="store_true", help="print planned archive files without writing")
    args = ap.parse_args()

    if args.no_url and (args.url or args.list_file):
        print("--no-url cannot be combined with --url or --list-file", file=sys.stderr)
        return 2
    if args.url and args.text:
        print("pass --url or --text, not both (URL is used for provenance/fetching)", file=sys.stderr)
        return 2

    posts_dir = find_root() / "workspace" / "posts"
    jobs: list[tuple[str, str]] = []
    if args.list_file:
        lines = Path(args.list_file).read_text(encoding="utf-8").splitlines()
        jobs = [(ln.strip(), "") for ln in lines if ln.strip() and not ln.startswith("#")]
    elif args.url:
        jobs = [(args.url, "")]
    elif args.text:
        if not args.no_url:
            print("--text requires --url for provenance; pass --no-url to archive without it",
                  file=sys.stderr)
            return 2
        jobs = [("", args.text)]
    else:
        print("need --url, --text (with --no-url), or --list-file", file=sys.stderr)
        return 2

    for url, _text in jobs:
        if url and not status_id(url):
            print(f"not an X status URL with a numeric id: {url!r} "
                  f"(use --no-url --text to archive without a URL)", file=sys.stderr)
            return 2

    existing = existing_by_status(posts_dir)
    written: list[Path] = []
    skipped = 0
    for url, text in jobs:
        sid = status_id(url) if url else None
        if sid and sid in existing:
            print(f"skipped {url}: already archived as {existing[sid].name}")
            skipped += 1
            continue
        if args.dry_run:
            planned = next_id(posts_dir, "hit", datetime.now(SHANGHAI).strftime("%Y%m%d"))
            if url and not text:
                print(f"dry-run: would fetch {url} -> {planned}.md")
            else:
                print(f"dry-run: would save {planned}.md")
            if args.no_url:
                print("  note: post_url will be empty (--no-url); dedupe by status id unavailable")
            continue
        if url and not text:
            print(f"fetching {url} ...")
            text = fetch_text(url)
        target = archive_one(posts_dir, args, url, text)
        if sid:
            existing[sid] = target
        written.append(target)
        print(f"saved {target}")
        if args.no_url:
            print("note: post_url is empty (--no-url); this entry cannot be deduped by status id")
    mode = " (dry-run, nothing written)" if args.dry_run else ""
    print(f"done: {len(written)} post(s) archived, {skipped} skipped{mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
