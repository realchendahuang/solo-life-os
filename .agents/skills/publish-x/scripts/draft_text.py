#!/usr/bin/env python3
"""Shared draft-text handling for the publish-x scripts (stdlib + PyYAML).

Extracts the publishable text from a markdown draft: YAML frontmatter is never
part of the output, `Verification notes` / `Feedback` / `Notes` sections are
dropped, thread drafts split into one text per `## Post N` section, and X's
weighted length rules (280 weighted units; CJK/fullwidth char = 2, URL = 23)
are applied. No network access, no browser, no clipboard.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

MAX_WEIGHT = 280
URL_WEIGHT = 23
PREVIEW_EDGE = 80

# Leading YAML frontmatter block, same shape as hit-archive/scripts/frontmatter.py.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
# Section headings. The whitespace after the hashes is optional here so that
# `##Post 1` still delimits a section (heading *lines* are only stripped when
# they match _HEADING_RE, i.e. `# ` with a space).
_POST_HEADING_RE = re.compile(r"^#{1,6}\s*Post(?:\s*(\d+))?\s*$", re.IGNORECASE)
_DROP_HEADING_RE = re.compile(
    r"^#{1,6}\s*(?:Verification\s+notes|Feedback|Notes)\s*$", re.IGNORECASE
)
_HEADING_RE = re.compile(r"^#{1,6}\s")
_FENCE_RE = re.compile(r"^\s*```")
_URL_RE = re.compile(r"https?://\S+")

# Twitter/X "weighted length" heavy ranges: CJK, kana, hangul, fullwidth forms
# and supplementary CJK ideographs. Every other character counts 1.
_HEAVY_RANGES = (
    (0x1100, 0x115F),    # Hangul Jamo
    (0x2E80, 0xA4CF),    # CJK radicals, kangxi, kana, hangul, ideographs
    (0xAC00, 0xD7A3),    # Hangul syllables
    (0xF900, 0xFAFF),    # CJK compatibility ideographs
    (0xFE30, 0xFE4F),    # CJK compatibility forms
    (0xFF00, 0xFF60),    # fullwidth forms
    (0xFFE0, 0xFFE6),    # fullwidth signs
    (0x20000, 0x3FFFD),  # CJK extensions B+
)


class DraftError(Exception):
    """Raised when a draft file cannot be parsed."""


def load_draft(path: str | Path) -> tuple[dict, str]:
    """Return (frontmatter metadata, body) for a draft markdown file.

    A draft without leading YAML frontmatter (legacy draft) returns
    ({}, whole text) so callers can treat it as an unapproved single post.
    """
    text = Path(path).read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise DraftError(f"invalid YAML frontmatter in {path}: {exc}") from exc
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise DraftError(f"frontmatter is not a mapping in {path}")
    return meta, text[match.end():]


def publishable_posts(meta: dict, body: str) -> list[str]:
    """Split a draft body into publishable post texts.

    Sections start at `Post` headings (`## Post`, `## Post 1`, ...). From a
    `Verification notes`, `Feedback`, or `Notes` heading, everything up to the
    next `Post` heading (or the end of the body) is dropped, so notes can never
    leak into the published text. Markdown heading lines (`#{1,6}` followed by
    whitespace) are stripped — except inside fenced code blocks, and except
    hashtag lines such as `#AI 编程工具 又更新了。`. With no `Post` heading the
    whole body is one post.
    """
    # meta is accepted for a stable signature; splitting depends on the body.
    segments: list[list[str]] = [[]]
    saw_post = False
    dropping = False
    in_fence = False
    current: list[str] | None = segments[0]

    def add(line: str) -> None:
        if dropping or current is None:
            return
        current.append(line)

    for line in body.splitlines():
        if _FENCE_RE.match(line):
            if not dropping:
                in_fence = not in_fence
                add(line)
            continue
        if not in_fence:
            if _POST_HEADING_RE.match(line):
                segments.append([])
                current = segments[-1]
                saw_post = True
                dropping = False
                continue
            if _DROP_HEADING_RE.match(line):
                dropping = True
                current = None
                continue
            if _HEADING_RE.match(line):
                # A plain heading line is stripped and does not end a section.
                continue
        add(line)

    parts = segments[1:] if saw_post else segments
    posts = []
    for lines in parts:
        text = "\n".join(lines).strip()
        if text:
            posts.append(text)
    if saw_post:
        return posts
    return posts[:1]


def weighted_length(text: str) -> int:
    """Return X's weighted count: CJK/fullwidth = 2, URL = 23, other = 1."""
    urls = _URL_RE.findall(text)
    total = sum(2 if _is_heavy(char) else 1 for char in _URL_RE.sub("", text))
    return total + len(urls) * URL_WEIGHT


def preview(text: str) -> str:
    """Return `weighted N/280` plus the first/last 80 chars (… when cut)."""
    if len(text) <= PREVIEW_EDGE * 2:
        shown = text
    else:
        shown = f"{text[:PREVIEW_EDGE]}…{text[-PREVIEW_EDGE:]}"
    return f"weighted {weighted_length(text)}/{MAX_WEIGHT} | {shown}"


def _is_heavy(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in _HEAVY_RANGES)
