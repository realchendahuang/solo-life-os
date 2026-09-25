#!/usr/bin/env python3
"""Capture one reviewed source item as a deduplicated X-Tiller Candidate Signal."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
TRACKING_PARAMETERS = {"ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid"}


class CandidateError(RuntimeError):
    """A concise candidate-capture failure safe to show to the user."""


def _load_check_registry() -> ModuleType:
    """Import the sibling check_registry module (single source of registry rules)."""
    try:
        import check_registry  # type: ignore[import-not-found]
        return check_registry
    except ImportError:
        pass
    path = Path(__file__).resolve().with_name("check_registry.py")
    spec = importlib.util.spec_from_file_location("xtiller_check_registry", path)
    if spec is None or spec.loader is None:
        raise CandidateError(f"cannot load registry validator {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "profile").is_dir():
            return parent
    raise CandidateError("cannot locate the X-Tiller repository root")


def canonicalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise CandidateError("--url must be a valid HTTPS URL") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise CandidateError("--url must be a valid HTTPS URL")
    kept_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(("https", parsed.netloc.casefold(), path, urlencode(kept_query), ""))


def normalize_timestamp(value: str | None, *, flag: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateError(f"{flag} must be ISO 8601 with a timezone") from exc
    if parsed.tzinfo is None:
        raise CandidateError(f"{flag} must be ISO 8601 with a timezone")
    return parsed.astimezone(SHANGHAI).isoformat(timespec="seconds")


def load_sources(path: Path, repo: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load, validate, and index sources/registry.json via check_registry."""
    check_registry = _load_check_registry()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CandidateError(f"cannot read source registry: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CandidateError(f"source registry JSON is invalid: {exc}") from exc
    rules, warnings = check_registry.load_rules(repo or path.resolve().parents[1])
    for warning in warnings:
        print(f"[source-registry] {warning}", file=sys.stderr)
    errors = check_registry.validate_registry(value, rules)
    if errors:
        raise CandidateError(
            "source registry is invalid: " + "; ".join(errors)
        )
    sources = value.get("sources") if isinstance(value, dict) else None
    if not isinstance(sources, list):
        raise CandidateError("source registry has no sources array")
    return {
        source["id"]: source
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }


def host_matches(child: str, parent: str) -> bool:
    """True when child equals parent or is a subdomain of it (case-insensitive)."""
    child = child.casefold().strip(".")
    parent = parent.casefold().strip(".")
    return bool(child) and bool(parent) and (child == parent or child.endswith("." + parent))


def verify_source_host(url: str, source: dict[str, Any]) -> None:
    """Require --url's host to match (or be a subdomain of) the registered host."""
    # Aggregators and general RSS feeds contain items linking to arbitrary external domains
    if source.get("source_type") in {"rss", "community-feedback"}:
        return
    source_url = source.get("source_url")
    source_host = urlsplit(source_url).hostname if isinstance(source_url, str) else None
    candidate_host = urlsplit(url.strip()).hostname
    if not source_host:
        raise CandidateError(
            f"registered source {source.get('id')!r} has no usable source_url host"
        )
    if not candidate_host or not host_matches(candidate_host, source_host):
        raise CandidateError(
            f"--url host {candidate_host or 'unknown'!r} does not match registered "
            f"source host {source_host!r} for {source.get('id')!r}"
        )


def content_hash(*, title: str, author: str | None, excerpt: str) -> str:
    material = "\n".join([title.strip(), author or "", excerpt.strip()])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_candidate(args: argparse.Namespace, now: datetime, source: dict[str, Any]) -> dict[str, Any]:
    title = args.title.strip()
    excerpt = args.excerpt.strip()
    if not title:
        raise CandidateError("--title must not be empty")
    if not excerpt:
        raise CandidateError("--excerpt must not be empty")
    canonical_url = canonicalize_url(args.url)
    verify_source_host(args.url, source)
    author = args.author.strip() if args.author and args.author.strip() else None
    digest = content_hash(title=title, author=author, excerpt=excerpt)
    source_type = source.get("source_type")
    if not isinstance(source_type, str) or not source_type.strip():
        raise CandidateError(
            f"registered source {source.get('id')!r} has no source_type; fix the registry"
        )
    return {
        "id": f"candidate-{now:%Y%m%d-%H%M%S}-{digest[:10]}",
        "source_id": source["id"],
        "source_url": args.url.strip(),
        "canonical_url": canonical_url,
        "source_type": source_type,
        "title": title,
        "author": author,
        "published_at": normalize_timestamp(args.published_at, flag="--published-at"),
        "fetched_at": now.isoformat(timespec="seconds"),
        "excerpt": excerpt,
        "content_hash": digest,
        "verification_status": args.verification_status,
        "suggested_action": args.suggested_action,
        "tags": list(dict.fromkeys(tag.strip() for tag in args.tag if tag.strip())),
    }


_CACHE_LOCK = threading.Lock()
_URL_CACHE: dict[str, Path] | None = None
_HASH_CACHE: dict[str, Path] | None = None


LEDGER_FILENAME = "candidates.jsonl"


def candidates_ledger_path(directory: Path) -> Path:
    """candidates.jsonl lives next to the (now legacy) per-file directory.

    Callers pass `workspace/candidates/` (the historical directory); the ledger
    sits at `workspace/candidates.jsonl`, one JSON object per line.
    """
    return directory.parent / LEDGER_FILENAME


def _init_candidate_cache(directory: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    global _URL_CACHE, _HASH_CACHE
    with _CACHE_LOCK:
        if _URL_CACHE is not None and _HASH_CACHE is not None:
            return _URL_CACHE, _HASH_CACHE
        url_cache: dict[str, Path] = {}
        hash_cache: dict[str, Path] = {}
        ledger = candidates_ledger_path(directory)
        if ledger.exists():
            for lineno, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    u = data.get("canonical_url")
                    h = data.get("content_hash")
                    # Lines carry no paths; the ledger itself is the address.
                    if u:
                        url_cache[u] = ledger
                    if h:
                        hash_cache[h] = ledger
        _URL_CACHE = url_cache
        _HASH_CACHE = hash_cache
        return _URL_CACHE, _HASH_CACHE


def register_candidate_cache(candidate: dict[str, Any], path: Path) -> None:
    """Register a new candidate in the cache immediately so subsequent checks see it."""
    global _URL_CACHE, _HASH_CACHE
    with _CACHE_LOCK:
        if _URL_CACHE is not None and candidate.get("canonical_url"):
            _URL_CACHE[candidate["canonical_url"]] = path
        if _HASH_CACHE is not None and candidate.get("content_hash"):
            _HASH_CACHE[candidate["content_hash"]] = path


def append_candidate_ledger(directory: Path, candidate: dict[str, Any]) -> Path:
    """Append one candidate to candidates.jsonl and register it in the cache.

    Locking note: `register_candidate_cache` re-acquires `_CACHE_LOCK`, which is
    a plain non-reentrant Lock, so this function must not hold it across the
    call. File append and cache registration each take the lock on their own.
    """
    ledger = candidates_ledger_path(directory)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(candidate, ensure_ascii=False) + "\n"
    with _CACHE_LOCK:
        with open(ledger, "a", encoding="utf-8") as handle:
            handle.write(line)
    register_candidate_cache(candidate, ledger)
    return ledger


def find_duplicate(directory: Path, candidate: dict[str, Any]) -> Path | None:
    if not directory.exists():
        return None
    url_cache, hash_cache = _init_candidate_cache(directory)
    with _CACHE_LOCK:
        canon_url = candidate.get("canonical_url")
        chash = candidate.get("content_hash")
        if canon_url and canon_url in url_cache:
            return url_cache[canon_url]
        if chash and chash in hash_cache:
            return hash_cache[chash]
    return None


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(serialized)
        temporary = Path(handle.name)
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Save one manually reviewed source item as a Candidate Signal."
    )
    parser.add_argument("--source-id", required=True, help="ID from sources/registry.json.")
    parser.add_argument("--url", required=True, help="Original primary-source HTTPS URL.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--excerpt", required=True, help="Short original or faithful source excerpt.")
    parser.add_argument("--author")
    parser.add_argument("--published-at", help="ISO 8601 timestamp with timezone when known.")
    parser.add_argument(
        "--verification-status",
        choices=["unverified", "official-primary", "corroborated", "rejected"],
        default="unverified",
    )
    parser.add_argument("--suggested-action", choices=["brief", "watch", "discard"], default="watch")
    parser.add_argument("--tag", action="append", default=[], help="Repeat for multiple tags.")
    parser.add_argument("--output", type=Path, help="Candidate ledger path inside this repository (default workspace/candidates.jsonl).")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing a candidate file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = find_repo_root()
        sources = load_sources(repo / "sources" / "registry.json", repo)
        source = sources.get(args.source_id)
        if not source:
            raise CandidateError(f"unknown --source-id {args.source_id!r}")
        if not source.get("enabled"):
            raise CandidateError(f"source {args.source_id!r} is disabled in the registry")
        now = datetime.now(SHANGHAI)
        candidate = build_candidate(args, now, source)
        candidates_dir = repo / "workspace" / "candidates"
        duplicate = find_duplicate(candidates_dir, candidate)
        if duplicate:
            print(
                json.dumps(
                    {
                        "mode": "duplicate",
                        "candidate": candidate,
                        "existing": str(duplicate.relative_to(repo)),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        output = args.output or candidates_ledger_path(candidates_dir)
        output = output if output.is_absolute() else repo / output
        try:
            output.resolve().relative_to(repo.resolve())
        except ValueError as exc:
            raise CandidateError("--output must stay inside the X-Tiller repository") from exc
        if not args.dry_run:
            append_candidate_ledger(candidates_dir, candidate)
            print(f"[source-registry] appended candidate: {output}", file=sys.stderr)
        print(
            json.dumps(
                {
                    "mode": "dry-run" if args.dry_run else "saved",
                    "candidate": candidate,
                    "output": str(output.relative_to(repo)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except CandidateError as exc:
        print(f"source-registry error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
