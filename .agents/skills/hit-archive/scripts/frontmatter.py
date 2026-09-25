#!/usr/bin/env python3
"""Read/write Markdown files with YAML frontmatter (std lib + pyyaml).

The body is the post text and is always preserved byte-for-byte: `dump`
rewrites the frontmatter and writes exactly one blank separator line, never
touching the body itself (contracts/hit-post.md: 正文永远原样保留).
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

# Closing `---`, its newline, and at most ONE blank separator line. Consuming
# only the separator keeps leading whitespace of the body intact.
_FRONTMATTER_RE = re.compile(
    r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n(?:\r?\n)?",
    re.DOTALL,
)

REQUIRED_KEYS = ("id", "kind", "post_url", "collected_at")

# Every key that appears in workspace/posts/*.md or that the archive writers
# legitimately produce (see contracts/hit-post.md).
ALLOWED_KEYS = {
    "id",
    "kind",
    "post_url",
    "collected_at",
    "posted_at",
    "channel",
    "draft_id",
    "pillar",
    "tags",
    "structure",
    "hook",
    "metrics",
    "verdict",
    "source",
    "site_title",
    "in_reply_to_status_id_str",
}

_ID_RE = re.compile(r"^(?:hit-site|hit|post)-\d{8}-\d{3}$")
_STATUS_URL_RE = re.compile(r"^https://x\.com/[^/\s]+/status/\d+$")
_KINDS = {"hit", "published"}
#: Which id prefix each kind must use. `hit`/`hit-site` are the documented prefix for a
#: benchmark post and `post` for one of our own; letting them cross-contaminate is how
#: `stats.py --kind hit` silently counted our own posts as benchmarks.
_KIND_PREFIXES = {"hit": ("hit", "hit-site"), "published": ("post",)}
_CHANNELS = {"intent", "buffer", "unknown"}
_STRUCTURES = {"opinion", "list", "story", "thread", "quote"}
_VERDICTS = {"good", "meh", "bad"}
_TIMESTAMP_TYPES = (str, date, datetime)


class FrontmatterError(RuntimeError):
    pass


def load(path: Path) -> tuple[dict[str, Any], str]:
    """Return (metadata, body) for a markdown file with YAML frontmatter."""
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise FrontmatterError(f"no YAML frontmatter in {path}")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as err:
        raise FrontmatterError(f"{path}: {err}") from err
    if not isinstance(meta, dict):
        raise FrontmatterError(f"frontmatter is not a mapping: {path}")
    body = text[match.end() :]
    return meta, body


def dump(meta: dict[str, Any], body: str) -> str:
    """Serialize (meta, body) to a markdown file with YAML frontmatter.

    The body is written verbatim after exactly one blank separator line, so
    repeated load -> dump cycles are byte-stable.
    """
    yaml_text = yaml.safe_dump(
        meta,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=200,
    ).rstrip()
    header = f"---\n{yaml_text}\n---\n"
    if not body:
        return header
    return f"{header}\n{body}"


def write(path: Path, meta: dict[str, Any], body: str) -> None:
    """Write a post file atomically (temp file + rename).

    The archive body is the verbatim post text per contracts/hit-post.md, so a crash or
    full disk mid-write must not truncate it — several callers also rewrite many files in
    one batch (`--all`, tag_hit_posts). Same pattern topic_store.atomic_write uses.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(dump(meta, body))
        temporary = Path(handle.name)
    temporary.replace(path)


def claim_path(posts_dir: Path, post_id: str) -> Path | None:
    """Atomically reserve `post_id`; return its path, or None when already taken.

    Ids are allocated by scanning for the first free number, which two concurrent runs
    can compute identically — the loser then overwrites the winner's post with no error.
    O_EXCL makes the claim itself the lock: the file exists from this moment, so the next
    allocator skips that number even before the body is written.
    """
    posts_dir.mkdir(parents=True, exist_ok=True)
    target = posts_dir / f"{post_id}.md"
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None
    os.close(fd)
    return target


def next_free_id(posts_dir: Path, prefix: str) -> tuple[str, Path]:
    """First unclaimed `prefix-NNN` id, together with its reserved path.

    Pairs with claim_path(): callers must write to the returned path (or delete it on
    failure) because the empty file is the reservation.
    """
    n = 1
    while True:
        post_id = f"{prefix}{n:03d}"
        claimed = claim_path(posts_dir, post_id)
        if claimed is not None:
            return post_id, claimed
        n += 1


def validate_post(meta: dict[str, Any], path: Path | None = None) -> None:
    """Raise FrontmatterError if meta violates contracts/hit-post.md."""
    where = f"{path}: " if path is not None else ""
    if not isinstance(meta, dict):
        raise FrontmatterError(f"{where}frontmatter is not a mapping")

    errors: list[str] = []
    for key in meta:
        if key not in ALLOWED_KEYS:
            errors.append(f"unknown key {key!r}")
    for key in REQUIRED_KEYS:
        value = meta.get(key)
        # post_url may be empty only for the explicit --no-url archive path.
        if value is None or (isinstance(value, str) and not value.strip() and key != "post_url"):
            errors.append(f"missing required key {key!r}")

    def bad_type(key: str, expected: str) -> None:
        if key in meta and meta[key] is not None and not isinstance(meta[key], expected):
            errors.append(f"{key!r} must be {expected}, got {type(meta[key]).__name__}")

    for key in ("id", "kind"):
        bad_type(key, str)
    value = meta.get("id")
    if isinstance(value, str) and value and not _ID_RE.match(value):
        errors.append(f"'id' must look like post-YYYYMMDD-NNN, got {value!r}")
    if isinstance(meta.get("kind"), str) and meta["kind"] and meta["kind"] not in _KINDS:
        errors.append(f"'kind' must be one of {sorted(_KINDS)}, got {meta['kind']!r}")
    kind = meta.get("kind")
    if isinstance(value, str) and isinstance(kind, str) and (prefixes := _KIND_PREFIXES.get(kind)):
        prefix = value.split("-", 1)[0]
        if prefix and prefix not in prefixes:
            errors.append(
                f"'id' prefix {prefix!r} does not match kind {kind!r} "
                f"(expected {'/'.join(prefixes)}-YYYYMMDD-NNN)"
            )

    url = meta.get("post_url")
    if url is not None and not isinstance(url, str):
        errors.append(f"'post_url' must be a string, got {type(url).__name__}")
    elif isinstance(url, str) and url and not _STATUS_URL_RE.match(url.split("?")[0].rstrip("/")):
        errors.append(
            "'post_url' must be a real X status URL "
            f"(https://x.com/<user>/status/<numeric id>), got {url!r}"
        )

    for key in ("collected_at", "posted_at"):
        value = meta.get(key)
        if value is None:
            continue
        if not isinstance(value, _TIMESTAMP_TYPES):
            errors.append(f"{key!r} must be a date-time string")
            continue
        if isinstance(value, str) and value.strip():
            # A string that merely exists is not a timestamp: `--posted-at foo` used to be
            # accepted into the archive, where every later range query silently ignored it.
            try:
                datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{key!r} must be ISO 8601, got {value!r}")
    for key in ("draft_id", "pillar", "hook", "source", "site_title", "in_reply_to_status_id_str"):
        bad_type(key, str)
    if isinstance(meta.get("channel"), str) and meta["channel"] and meta["channel"] not in _CHANNELS:
        errors.append(f"'channel' must be one of {sorted(_CHANNELS)}, got {meta['channel']!r}")
    if isinstance(meta.get("structure"), str) and meta["structure"] and meta["structure"] not in _STRUCTURES:
        errors.append(f"'structure' must be one of {sorted(_STRUCTURES)}, got {meta['structure']!r}")
    if isinstance(meta.get("verdict"), str) and meta["verdict"] and meta["verdict"] not in _VERDICTS:
        errors.append(f"'verdict' must be one of {sorted(_VERDICTS)}, got {meta['verdict']!r}")
    tags = meta.get("tags")
    if tags is not None and not isinstance(tags, list):
        errors.append(f"'tags' must be a list, got {type(tags).__name__}")
    metrics = meta.get("metrics")
    if metrics is not None and not isinstance(metrics, dict):
        errors.append(f"'metrics' must be a mapping, got {type(metrics).__name__}")

    if errors:
        raise FrontmatterError(where + "; ".join(errors))


def load_all(
    posts_dir: Path, *, errors: list[str] | None = None
) -> list[tuple[Path, dict[str, Any], str]]:
    """Load every *.md in posts_dir as (path, meta, body), skipping README.

    Unreadable files (no frontmatter, malformed YAML, non-mapping) are skipped
    but never silently: pass an ``errors`` list to collect them, or read
    ``load_all.errors`` afterwards. Returns only successfully loaded records.
    """
    report = errors if errors is not None else []
    results = []
    for path in sorted(posts_dir.glob("*.md")):
        if path.name.startswith("README"):
            continue
        try:
            meta, body = load(path)
        except FrontmatterError as err:
            report.append(str(err))
            continue
        results.append((path, meta, body))
    load_all.errors = report
    return results


#: Errors from the most recent load_all() call (paths + reason).
load_all.errors = []  # type: ignore[attr-defined]
