#!/usr/bin/env python3
"""Open an X Web Intent URL for already-final post text.

Two input modes:
- `--file`: a markdown draft (legacy; frontmatter and Verification notes /
  Feedback / Notes sections are never emitted).
- `--text`: the final post text passed directly (conversation workflow,
  2026-09-24) — no draft file exists at all.

Either way the script checks X's weighted 280 limit, url-encodes the text,
opens x.com/intent/post?text=... in the user's default browser, and also
copies the same text to the clipboard as a paste fallback. Thread drafts are
prepared one part per run (`--thread --part N`) and are never concatenated.
No browser automation, no publishing.

Usage:
    python3 intent_open.py --text "帖子正文" [--no-open] [--dry-run]
    python3 intent_open.py --file workspace/drafts/FINAL.md [--no-open] [--dry-run]
    python3 intent_open.py --file workspace/drafts/THREAD.md --thread --part 2
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draft_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
INTENT_BASE = "https://x.com/intent/post?text="
URL_DISPLAY = 90


def _resolve_path(value: str) -> Path:
    """Explicit path, cwd-relative path, else repo-root-relative path."""
    path = Path(value)
    if path.is_absolute():
        return path
    cwd = Path.cwd()
    candidate = cwd / value
    return candidate if candidate.exists() else REPO_ROOT / value


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--file",
        help="Path to the final markdown draft (legacy mode)",
    )
    ap.add_argument(
        "--text",
        help="The final post text itself (conversation workflow; no draft file)",
    )
    ap.add_argument(
        "--no-open",
        action="store_true",
        help="Print the intent URL only; do not open the browser",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print everything; never touch the clipboard or the browser",
    )
    ap.add_argument(
        "--allow-unapproved",
        action="store_true",
        help="Allow drafts without frontmatter status 'approved' (legacy drafts)",
    )
    ap.add_argument(
        "--allow-over-limit",
        action="store_true",
        help="Warn instead of refusing above X's weighted 280 limit (long posts / X Premium)",
    )
    ap.add_argument(
        "--thread",
        action="store_true",
        help="Allow a multi-part draft; only one part is prepared per run",
    )
    ap.add_argument(
        "--part",
        type=int,
        default=1,
        help="1-based thread part to prepare (default 1)",
    )
    args = ap.parse_args(argv)

    if args.text is not None and args.file:
        return _fail("pass either --text or --file, not both")
    if args.text is not None:
        # Conversation workflow: the text is final by definition (the user
        # copied it into the composer); approval and section-stripping do not
        # apply. Threads are not supported here — pass each post separately.
        text = args.text.strip()
        if not text:
            return _fail("--text must not be empty")
        posts = [text]
        approval = "conversation text (no draft file)"
        status = "approved"
    else:
        if not args.file:
            return _fail("pass either --text or --file")
        path = _resolve_path(args.file)
        if not path.exists():
            return _fail(f"draft not found: {path}")
        try:
            meta, body = draft_text.load_draft(path)
        except draft_text.DraftError as exc:
            return _fail(str(exc))

        posts = draft_text.publishable_posts(meta, body)
        if not posts:
            return _fail("no publishable text found in the draft body")

        status = meta.get("status")
        if status != "approved" and not args.allow_unapproved:
            detail = (
                f"status is {status!r}"
                if "status" in meta
                else "no frontmatter status (legacy draft)"
            )
            return _fail(
                f"draft is not approved ({detail}); rerun with --allow-unapproved to override"
            )
        approval = "approved" if status == "approved" else "not approved; --allow-unapproved"

    if len(posts) > 1 and not args.thread:
        return _fail(
            f"draft has {len(posts)} post sections; rerun with --thread "
            "(parts are never concatenated)"
        )
    if args.part < 1 or args.part > len(posts):
        return _fail(f"--part must be between 1 and {len(posts)}")

    weights = [draft_text.weighted_length(post) for post in posts]
    over = [
        f"part {index}: weighted {weight}/{draft_text.MAX_WEIGHT}"
        for index, weight in enumerate(weights, 1)
        if weight > draft_text.MAX_WEIGHT
    ]
    if over and not args.allow_over_limit:
        return _fail(
            f"{'; '.join(over)} exceeds X's weighted {draft_text.MAX_WEIGHT} limit; "
            "edit the draft or rerun with --allow-over-limit (long posts / X Premium)"
        )
    if over:
        print(
            f"warning: {'; '.join(over)} exceeds the weighted "
            f"{draft_text.MAX_WEIGHT} limit; continuing because --allow-over-limit",
            file=sys.stderr,
        )

    text = posts[args.part - 1]
    url = INTENT_BASE + urllib.parse.quote(text, safe="")

    source = args.text.strip() if args.text is not None else path
    print(f"source: {source}")
    print(f"approval: {approval}")
    print(f"preview: {draft_text.preview(text)}")
    if len(posts) > 1:
        print(f"thread: {len(posts)} parts, preparing part {args.part} only")
        for index, weight in enumerate(weights, 1):
            marker = "->" if index == args.part else "  "
            print(
                f"{marker} part {index}/{len(posts)}: weighted "
                f"{weight}/{draft_text.MAX_WEIGHT}"
            )
    print(f"===== text (part {args.part}/{len(posts)}) =====")
    print(text)
    print("===== end of text =====")

    if args.dry_run:
        print("dry-run: clipboard and browser untouched")
        print(f"intent URL: {url}")
        print("next: review the text above, then rerun without --dry-run.")
        return 0

    if sys.platform != "darwin":
        print(
            "warning: clipboard/browser helpers are macOS-only; "
            "paste this URL manually:",
            file=sys.stderr,
        )
        print(f"intent URL: {url}")
        print("next: open the URL above, review the composer, and click Post yourself.")
        return 0

    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"error: clipboard copy failed: {exc}", file=sys.stderr)
        print(f"paste this URL manually: {url}", file=sys.stderr)
        return 3
    print(
        f"clipboard: weighted {weights[args.part - 1]}/{draft_text.MAX_WEIGHT} "
        f"({len(text)} chars) paste fallback ready"
    )

    if args.no_open:
        print(f"intent URL: {url}")
    else:
        try:
            subprocess.run(["open", url], check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"error: could not open the browser: {exc}", file=sys.stderr)
            print(f"paste this URL manually: {url}", file=sys.stderr)
            return 3
        suffix = "..." if len(url) > URL_DISPLAY else ""
        print(f"opened in default browser: {url[:URL_DISPLAY]}{suffix}")

    if len(posts) > 1:
        remaining = len(posts) - args.part
        if remaining:
            print(
                f"thread: after this part is posted, reply-chain the remaining "
                f"{remaining} part(s) one by one with --part {args.part + 1}"
            )
        else:
            print("thread: this is the last part; reply-chain it to the previous one.")
    print("next: review the prefilled composer and click Post yourself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
