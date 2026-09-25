#!/usr/bin/env python3
"""Copy an already-final X post to the clipboard and open the X compose page
for manual pasting. YAML frontmatter and Verification notes / Feedback / Notes
sections are never copied. No browser automation, no publishing.

Usage:
    python3 fill_clipboard.py --file workspace/drafts/FINAL.md [--no-open]

Extraction is shared with intent_open.py via the draft_text module (heading
lines are stripped except inside fenced code blocks, hashtag lines are kept).
For multi-part thread drafts use `intent_open.py --thread --part N`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draft_text  # noqa: E402

# resolve the X-Tiller repo root: <root>/.agents/skills/publish-x/scripts/
REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_URL = "https://x.com/compose/post"


def _resolve_path(value: str) -> Path:
    """Explicit path, cwd-relative path, else repo-root-relative path."""
    path = Path(value)
    if path.is_absolute():
        return path
    cwd = Path.cwd()
    candidate = cwd / value
    return candidate if candidate.exists() else REPO_ROOT / value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="Path to the final markdown draft")
    ap.add_argument(
        "--no-open",
        action="store_true",
        help="Copy to clipboard only; do not open the X compose page",
    )
    args = ap.parse_args(argv)

    path = _resolve_path(args.file)
    if not path.exists():
        print(f"error: draft not found: {path}", file=sys.stderr)
        return 2
    try:
        meta, body = draft_text.load_draft(path)
    except draft_text.DraftError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    posts = draft_text.publishable_posts(meta, body)
    if not posts:
        print("error: no publishable text found in the draft body", file=sys.stderr)
        return 2
    if len(posts) > 1:
        print(
            f"error: draft has {len(posts)} post sections; use "
            "intent_open.py --thread --part N for threads",
            file=sys.stderr,
        )
        return 2
    text = posts[0]

    if sys.platform != "darwin":
        print(
            "warning: clipboard/browser helpers are macOS-only; "
            "copy the text below manually:",
            file=sys.stderr,
        )
        print(text)
        return 0

    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"error: pbcopy failed: {exc}", file=sys.stderr)
        return 3
    print(
        f"clipboard: weighted {draft_text.weighted_length(text)}/"
        f"{draft_text.MAX_WEIGHT} ({len(text)} chars, "
        f"{len(text.splitlines())} lines)"
    )

    if not args.no_open:
        try:
            subprocess.run(["open", COMPOSE_URL], check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"error: could not open the compose page: {exc}", file=sys.stderr)
            return 3
        print(f"opened: {COMPOSE_URL}")
    print("next: switch to the X tab, Cmd+V, review, then click Post yourself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
