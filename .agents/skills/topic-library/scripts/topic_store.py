#!/usr/bin/env python3
"""Shared store for the X-Tiller topic library (`workspace/topics/`).

One Markdown file per topic. YAML frontmatter carries the machine fields; the
body holds the user's statement and backlinks as plain text. The library is
an append-and-advance record, not a second evidence layer: published posts in
`workspace/posts/` carry the full text, and a topic only carries their URLs as
post_urls (filled in batches from official exports; the draft-file workflow
was retired 2026-09-24 — writing happens in conversation).

Duplicate detection is deliberately conservative. Re-submitting the same topic
is the normal way a library rots, but refusing a genuinely new topic that
happens to share a long prefix (a product name, a series title) is worse than
letting a near-duplicate through, because the refusal is what the user sees and
has to argue with. Exact wording always matches; fuzzy matching needs both
titles to be long enough to be meaningful.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


try:
    import yaml  # PyYAML, the repository's only third-party dependency
except ImportError as _yaml_exc:  # pragma: no cover - surfaced with a clear message
    yaml = None
    _YAML_IMPORT_ERROR = _yaml_exc


SHANGHAI = ZoneInfo("Asia/Shanghai")

TOPIC_DIR = ("workspace", "topics")

#: Fuzzy-match cutoff on normalized titles; see the module docstring.
DUPLICATE_THRESHOLD = 0.9

#: Normalized titles shorter than this are only compared for exact equality.
MIN_FUZZY_LENGTH = 12

_ID_DIGEST_LENGTH = 10

#: Canonical pillar ids, copied from profile/content-pillars.md.
PILLAR_IDS = (
    "ai-coding-agents",
    "indie-dev",
    "ai-productivity",
    "insight-income",
    "language-learning",
)

#: Canonical editorial column ids, matching docs/content-matrix-architecture.md.
COLUMN_IDS = (
    "opc-handbook",
    "hacker-craft",
    "digital-sovereignty",
    "tech-debates",
    "ai-humanity",
)

#: Canonical derivative asset target types.
TARGET_ASSETS = (
    "repo",
    "ebook",
    "campaign",
    "monetization",
    "none",
)

#: Lifecycle order, used for grouping and for "what is still unwritten" reads.
#: briefed/drafted retired 2026-09-24 with the draft-file workflow; kept here so
#: legacy entries carrying those statuses still load and advance.
STATUS_ORDER = ("candidate", "briefed", "drafted", "parked", "published", "dropped")

#: Statuses the simplified pipeline actually writes. New entries only ever
#: carry one of these four.
ACTIVE_STATUS_ORDER = ("candidate", "parked", "published", "dropped")

#: User-facing creator-friendly labels (全三字看板: 待写库, 素材库, 已发布, 已弃用).
STATUS_LABELS: dict[str, str] = {
    "candidate": "待写库",
    "parked": "素材库",
    "published": "已发布",
    "dropped": "已弃用",
    "briefed": "已立意",
    "drafted": "已起草",
}

#: CLI argument aliases mapping natural Chinese names to canonical store status strings.
STATUS_ALIASES: dict[str, str] = {
    "待写库": "candidate",
    "待写": "candidate",
    "待发": "candidate",
    "候选": "candidate",
    "candidate": "candidate",
    "素材库": "parked",
    "素材": "parked",
    "灵感库": "parked",
    "暂存": "parked",
    "parked": "parked",
    "已发布": "published",
    "已发": "published",
    "发布": "published",
    "published": "published",
    "已弃用": "dropped",
    "弃用": "dropped",
    "排除": "dropped",
    "dropped": "dropped",
    "已立意": "briefed",
    "briefed": "briefed",
    "已起草": "drafted",
    "drafted": "drafted",
}

#: Characters that survive normalization: digits, latin letters, CJK.
_SIGNIFICANT_RE = re.compile(r"[0-9a-z\u4e00-\u9fff]+")

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)


class TopicError(RuntimeError):
    """A concise topic-library failure safe to show to the user."""


def _require_yaml() -> Any:
    if yaml is None:
        raise TopicError(
            "PyYAML is required to read the Markdown topic library "
            f"(import failed: {_YAML_IMPORT_ERROR}); run: pip install PyYAML"
        )
    return yaml


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "contracts").is_dir():
            return parent
    raise TopicError("cannot locate the X-Tiller repository root")


def topics_dir(repo: Path) -> Path:
    return repo.joinpath(*TOPIC_DIR)


def resolve_library(repo: Path, value: Path | None) -> Path:
    """The library directory to use: `workspace/topics/` unless overridden.

    `--library` exists so tests can exercise a real write round trip inside a
    throwaway directory instead of the live library. The target must stay
    inside the repository.
    """
    if value is None:
        return topics_dir(repo)
    path = value if value.is_absolute() else repo / value
    return ensure_within_repo(repo, path, "--library")


def relative_label(repo: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)


def ensure_within_repo(repo: Path, path: Path, label: str) -> Path:
    try:
        path.resolve().relative_to(repo.resolve())
    except ValueError as exc:
        raise TopicError(f"{label} must stay inside the X-Tiller repository") from exc
    return path


def build_id(now: datetime, seed: str) -> str:
    digest = hashlib.sha256(f"{now.isoformat()}|{seed}".encode()).hexdigest()
    return f"topic-{now:%Y%m%d-%H%M%S}-{digest[:_ID_DIGEST_LENGTH]}"


def validate_http_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TopicError(f"invalid source URL: {value}")
    return value


def validate_source_ref(repo: Path, value: str) -> str:
    """A source_ref is a repository-relative path to the artifact it came from."""
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise TopicError(
            f"invalid --source-ref {value!r}: use a repository-relative path "
            f"such as workspace/inbox/idea-20260915-194916-15c63a16ea.md"
        )
    try:
        (repo / candidate).resolve().relative_to(repo.resolve())
    except ValueError as exc:
        raise TopicError(f"invalid --source-ref {value!r}: escapes the repository") from exc
    return value


def normalize_text(value: str) -> str:
    """Case, spacing, and punctuation are not what makes two topics different."""
    return "".join(_SIGNIFICANT_RE.findall(value.lower()))


def load_topic(path: Path) -> dict[str, object]:
    """Parse one Markdown topic file into its flat record dict.

    The frontmatter is the record; the body is prose. Known list fields
    (source_refs, source_urls, notes, brief_ids, draft_ids, post_urls) come
    back as lists even when absent, so callers can append without guards.
    """
    y = _require_yaml()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TopicError(f"cannot read topic {path.name}: {exc}") from exc
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise TopicError(f"cannot read topic {path.name}: no YAML frontmatter")
    try:
        data = y.safe_load(match.group(1)) or {}
    except y.YAMLError as exc:
        raise TopicError(f"cannot read topic {path.name}: bad frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise TopicError(f"cannot read topic {path.name}: frontmatter must be a mapping")
    record: dict[str, object] = dict(data)
    for field in ("source_refs", "source_urls", "notes", "brief_ids", "draft_ids", "post_urls"):
        record.setdefault(field, [])
    # The statement lives in the body; expose it as a field for dedupe and
    # display so callers never need to parse Markdown themselves.
    body = text[match.end():].strip()
    record.setdefault("statement", "")
    if record.get("statement") in (None, "") and body:
        sections = re.split(r"^## ", body, flags=re.MULTILINE)
        record["statement"] = sections[0].strip()
    return record


def _dump_frontmatter(record: dict[str, object]) -> str:
    y = _require_yaml()
    ordered: dict[str, object] = {}
    for key in (
        "id",
        "created_at",
        "updated_at",
        "title",
        "status",
        "source",
        "source_refs",
        "source_urls",
        "pillar_id",
        "column_id",
        "target_asset",
        "thesis",
        "notes",
        "brief_ids",
        "draft_ids",
        "post_urls",
        "dropped_reason",
    ):
        if key in record and record[key] not in (None, [], ""):
            ordered[key] = record[key]
    for key, value in record.items():
        if key not in ordered and value not in (None, [], ""):
            ordered[key] = value
    return y.safe_dump(ordered, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()


def render_topic(record: dict[str, object]) -> str:
    """Serialize a topic record to the Markdown file format."""
    frontmatter = _dump_frontmatter(record)
    body = str(record.get("statement") or "").strip()
    notes = [str(n) for n in (record.get("notes") or []) if str(n).strip()]
    brief_ids = [str(v) for v in (record.get("brief_ids") or [])]
    draft_ids = [str(v) for v in (record.get("draft_ids") or [])]
    post_urls = [str(v) for v in (record.get("post_urls") or [])]
    sections: list[str] = []
    if notes:
        sections.append(
            "## 备注\n\n" + "\n".join(f"- {n}" for n in notes)
        )
    if brief_ids or draft_ids or post_urls:
        lines = [f"- brief: {v}" for v in brief_ids]
        lines += [f"- draft: {v}" for v in draft_ids]
        lines += [f"- post: {v}" for v in post_urls]
        sections.append("## 回链\n\n" + "\n".join(lines))
    parts = [f"---\n{frontmatter}\n---\n"]
    if body:
        parts.append(f"\n{body}\n")
    for section in sections:
        parts.append(f"\n{section}\n")
    return "".join(parts)


def iter_topics(directory: Path) -> list[tuple[Path, dict[str, object]]]:
    """Every readable topic, oldest filename first. A missing directory is empty.

    `workspace/` directories are created on demand (workspace/README.md), so an
    absent library is a normal state, not an error.
    """
    if not directory.is_dir():
        return []
    found: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(directory.glob("*.md")):
        found.append((path, load_topic(path)))
    return found


def find_duplicate(
    topics: list[tuple[Path, dict[str, object]]],
    *,
    title: str,
    statement: str,
    threshold: float = DUPLICATE_THRESHOLD,
) -> tuple[Path, dict[str, object]] | None:
    """The first existing topic that this title/statement repeats, if any."""
    key_title = normalize_text(title)
    key_statement = normalize_text(statement)
    for path, record in topics:
        if key_title and key_title == normalize_text(str(record.get("title", ""))):
            return path, record
        if key_statement and key_statement == normalize_text(str(record.get("statement", ""))):
            return path, record
    for path, record in topics:
        other = normalize_text(str(record.get("title", "")))
        if min(len(key_title), len(other)) < MIN_FUZZY_LENGTH:
            continue
        if difflib.SequenceMatcher(None, key_title, other).ratio() >= threshold:
            return path, record
    return None


def atomic_write(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render_topic(record)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def summarize(record: dict[str, object]) -> dict[str, object]:
    """The compact shape the CLIs print, so a caller does not re-derive it."""
    return {
        "id": record.get("id"),
        "status": record.get("status"),
        "title": record.get("title"),
        "pillar_id": record.get("pillar_id"),
        "column_id": record.get("column_id"),
        "target_asset": record.get("target_asset"),
    }


def truncate_title(statement: str, limit: int = 60) -> str:
    """Fallback label when the caller does not supply one."""
    first_line = statement.strip().splitlines()[0].strip() if statement.strip() else ""
    if len(first_line) <= limit:
        return first_line
    return first_line[:limit].rstrip()


#: Statuses a publish may advance from. `published`/`dropped` are terminal for this
#: operation: a parked topic stays parked and a dropped one is not resurrected by a
#: later post, so the ledger keeps meaning what it says.
#: briefed/drafted retired 2026-09-24. parked stays advanceable: a topic set
#: aside can still be written and shipped later.
ADVANCEABLE_STATUSES = ("candidate", "parked")


def advance_to_published(
    repo: Path,
    *,
    post_url: str,
    topic_id: str | None = None,
    draft_id: str | None = None,
    library: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Record a published post on the topic(s) it came from.

    Returns `(advanced_topic_ids, warnings)`. Callers pass at least one of
    `topic_id` / `draft_id`; with only a draft id, every topic carrying that
    draft is advanced. This is the return half of the draft/status loop:
    without it the library only ever knows about topics that have not shipped.
    """
    directory = library if library is not None else topics_dir(repo)
    advanced: list[str] = []
    warnings: list[str] = []

    for path, record in iter_topics(directory):
        record_id = str(record.get("id") or path.stem)
        if topic_id is not None:
            if record_id != topic_id:
                continue
        else:
            draft_ids = [str(value) for value in (record.get("draft_ids") or [])]
            if not draft_id or draft_id not in draft_ids:
                continue

        urls = [str(value) for value in (record.get("post_urls") or [])]
        if post_url in urls:
            warnings.append(f"{record_id}: post already recorded")
            continue

        status = str(record.get("status") or "candidate")
        if status not in ADVANCEABLE_STATUSES:
            warnings.append(
                f"{record_id}: left at {status} (only "
                f"{'/'.join(ADVANCEABLE_STATUSES)} advance to published)"
            )
            continue

        record["status"] = "published"
        record["post_urls"] = [*urls, post_url]
        record["updated_at"] = datetime.now(SHANGHAI).isoformat(timespec="seconds")
        atomic_write(path, record)
        advanced.append(record_id)

    if topic_id is not None and not advanced:
        missing = directory / f"{topic_id}.md"
        if not missing.is_file():
            warnings.append(f"--topic-id {topic_id!r} does not match any topic in {relative_label(repo, directory)}")
    if topic_id is None and draft_id and not advanced:
        warnings.append(f"no topic lists draft_id {draft_id!r}; topic library not advanced")

    return advanced, warnings