#!/usr/bin/env python3
"""Validate X-Tiller's intentionally small, tracked source registry.

Enums and limits are read from ``contracts/source-registry.schema.json`` when
that file is readable, so the contract stays the single source of truth. If the
schema is missing or unreadable, the built-in fallbacks below are used and a
warning is printed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


# Built-in fallbacks. Mirror contracts/source-registry.schema.json; the schema
# wins whenever it can be read.
BUILTIN_SOURCE_TYPES = {
    "official-changelog",
    "official-blog",
    "github-releases",
    "rss",
    "community-feedback",
    "personal-evidence",
}
BUILTIN_FETCH_MODES = {"web-search", "github-releases", "rss", "manual"}
BUILTIN_PRIORITIES = {"P0", "P1", "P2", "P3"}
BUILTIN_CADENCES = {"on-demand", "daily", "weekly"}
BUILTIN_SOURCE_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{2,63}$"
BUILTIN_REQUIRED_FIELDS = {
    "id",
    "name",
    "source_url",
    "source_type",
    "fetch_mode",
    "pillars",
    "priority",
    "cadence",
    "event_filters",
    "enabled",
    "notes",
}
BUILTIN_MAX_SOURCES = 200
BUILTIN_MAX_ENABLED = 200
BUILTIN_VERSION = 1

SCHEMA_RELATIVE_PATH = Path("contracts") / "source-registry.schema.json"


class RegistryError(RuntimeError):
    """A concise source-registry validation failure."""


def builtin_rules() -> dict[str, Any]:
    return {
        "source_types": set(BUILTIN_SOURCE_TYPES),
        "fetch_modes": set(BUILTIN_FETCH_MODES),
        "priorities": set(BUILTIN_PRIORITIES),
        "cadences": set(BUILTIN_CADENCES),
        "source_id_pattern": BUILTIN_SOURCE_ID_PATTERN,
        "required_fields": set(BUILTIN_REQUIRED_FIELDS),
        "max_sources": BUILTIN_MAX_SOURCES,
        "max_enabled": BUILTIN_MAX_ENABLED,
        "version": BUILTIN_VERSION,
    }


def _enum(source_props: dict[str, Any], key: str, fallback: set[str]) -> set[str]:
    entry = source_props.get(key)
    if isinstance(entry, dict):
        values = entry.get("enum")
        if isinstance(values, list) and values and all(
            isinstance(item, str) for item in values
        ):
            return set(values)
    return set(fallback)


def rules_from_schema(schema: object, rules: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Derive validation rules from the contract schema; returns (rules, warnings)."""
    resolved = dict(rules if rules is not None else builtin_rules())
    warnings: list[str] = []
    if not isinstance(schema, dict):
        return resolved, ["registry schema is not a JSON object; using built-in rules"]
    sources = schema.get("properties", {}).get("sources")
    if not isinstance(sources, dict):
        return resolved, ["registry schema has no sources property; using built-in rules"]
    source_props = sources.get("items", {}).get("properties")
    if not isinstance(source_props, dict):
        return resolved, [
            "registry schema has no sources[].properties; using built-in rules"
        ]

    resolved["source_types"] = _enum(
        source_props, "source_type", resolved["source_types"]
    )
    resolved["fetch_modes"] = _enum(
        source_props, "fetch_mode", resolved["fetch_modes"]
    )
    resolved["priorities"] = _enum(source_props, "priority", resolved["priorities"])
    resolved["cadences"] = _enum(source_props, "cadence", resolved["cadences"])

    item = sources.get("items")
    if isinstance(item, dict):
        required = item.get("required")
        if isinstance(required, list) and required and all(
            isinstance(entry, str) for entry in required
        ):
            resolved["required_fields"] = set(required)

    id_entry = source_props.get("id")
    if isinstance(id_entry, dict) and isinstance(id_entry.get("pattern"), str):
        resolved["source_id_pattern"] = id_entry["pattern"]

    max_items = sources.get("maxItems")
    if isinstance(max_items, int) and not isinstance(max_items, bool) and max_items > 0:
        resolved["max_sources"] = max_items
        # Optional forward-compatible keyword; absent means "same as max_sources".
        resolved["max_enabled"] = max_items

    version_entry = schema.get("properties", {}).get("version")
    if isinstance(version_entry, dict) and "const" in version_entry:
        resolved["version"] = version_entry["const"]

    return resolved, warnings


def load_rules(repo: Path) -> tuple[dict[str, Any], list[str]]:
    """Load rules from the contract schema, falling back to the built-ins."""
    rules = builtin_rules()
    path = repo / SCHEMA_RELATIVE_PATH
    if not path.is_file():
        return rules, [f"{SCHEMA_RELATIVE_PATH} not found; using built-in rules"]
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return rules, [
            f"{SCHEMA_RELATIVE_PATH} unreadable ({exc}); using built-in rules"
        ]
    return rules_from_schema(schema, rules)


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "profile").is_dir():
            return parent
    raise RegistryError("cannot locate the X-Tiller repository root")


def is_https_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.hostname)


def is_nonempty_string_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def validate_registry(
    value: object, rules: dict[str, Any] | None = None
) -> list[str]:
    """Return human-readable errors; an empty list means the registry is usable.

    ``rules`` defaults to the built-in fallbacks; callers that have the repo
    should pass rules from :func:`load_rules` so the contract schema wins.
    """
    rules = rules if isinstance(rules, dict) else builtin_rules()
    source_types = rules["source_types"]
    fetch_modes = rules["fetch_modes"]
    priorities = rules["priorities"]
    cadences = rules["cadences"]
    required_fields = rules["required_fields"]
    source_id_pattern = re.compile(rules["source_id_pattern"])
    max_sources = rules["max_sources"]
    max_enabled = rules.get("max_enabled", max_sources)

    errors: list[str] = []
    if not isinstance(value, dict):
        return ["registry must be a JSON object"]
    if set(value) != {"version", "sources"}:
        errors.append("registry must contain exactly version and sources")
    if value.get("version") != rules.get("version", BUILTIN_VERSION):
        errors.append(f"registry version must equal {rules.get('version', BUILTIN_VERSION)}")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        return errors + ["sources must be a non-empty array"]
    if len(sources) > max_sources:
        errors.append(f"sources may not contain more than {max_sources} entries")

    ids: set[str] = set()
    urls: set[str] = set()
    enabled = 0
    for position, source in enumerate(sources, start=1):
        prefix = f"sources[{position}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = required_fields - set(source)
        unexpected = set(source) - required_fields
        if missing:
            errors.append(f"{prefix} is missing fields: {', '.join(sorted(missing))}")
        if unexpected:
            errors.append(f"{prefix} has unsupported fields: {', '.join(sorted(unexpected))}")

        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id_pattern.fullmatch(source_id):
            errors.append(f"{prefix}.id must be a lowercase slug of 3 to 64 characters")
        elif source_id in ids:
            errors.append(f"{prefix}.id duplicates {source_id!r}")
        else:
            ids.add(source_id)

        name = source.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}.name must be a non-empty string")
        source_url = source.get("source_url")
        if not is_https_url(source_url):
            errors.append(f"{prefix}.source_url must be an HTTPS URL")
        elif source_url in urls:
            errors.append(f"{prefix}.source_url duplicates {source_url!r}")
        else:
            urls.add(source_url)

        if source.get("source_type") not in source_types:
            errors.append(f"{prefix}.source_type is invalid")
        if source.get("fetch_mode") not in fetch_modes:
            errors.append(f"{prefix}.fetch_mode is invalid")
        if source.get("priority") not in priorities:
            errors.append(f"{prefix}.priority is invalid")
        if source.get("cadence") not in cadences:
            errors.append(f"{prefix}.cadence is invalid")
        if not is_nonempty_string_list(source.get("pillars")):
            errors.append(f"{prefix}.pillars must be a non-empty string array")
        if not is_nonempty_string_list(source.get("event_filters")):
            errors.append(f"{prefix}.event_filters must be a non-empty string array")
        if not isinstance(source.get("enabled"), bool):
            errors.append(f"{prefix}.enabled must be a boolean")
        elif source["enabled"]:
            enabled += 1
        if not isinstance(source.get("notes"), str):
            errors.append(f"{prefix}.notes must be a string")

    if enabled > max_enabled:
        errors.append(f"no more than {max_enabled} sources may be enabled")
    return errors


def load_registry(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry JSON is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistryError("registry must be a JSON object")
    return value


def probe_single_source(source: dict[str, Any], known_feeds: dict[str, str], user_agent: str) -> dict[str, Any]:
    import time
    import urllib.request
    sid = source.get("id", "unknown")
    source_type = source.get("source_type")
    fetch_mode = source.get("fetch_mode")

    if fetch_mode == "manual":
        return {
            "source_id": sid,
            "status": "ok",
            "probe_url": source.get("source_url"),
            "http_code": 200,
            "latency_ms": 0,
            "note": "manual / on-demand ingest",
        }

    url = known_feeds.get(sid) or source.get("source_url")
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = resp.read(1024 * 16)
            latency = int((time.perf_counter() - start) * 1000)
            return {
                "source_id": sid,
                "status": "ok",
                "probe_url": url,
                "http_code": resp.status,
                "latency_ms": latency,
                "bytes_read": len(data),
            }
    except Exception as exc:  # noqa: BLE001
        latency = int((time.perf_counter() - start) * 1000)
        return {
            "source_id": sid,
            "status": "failed",
            "probe_url": url,
            "error": str(exc),
            "latency_ms": latency,
        }


def probe_sources(sources: list[dict[str, Any]]) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import poll_registry
        known_feeds = poll_registry.KNOWN_FEEDS
        user_agent = poll_registry.USER_AGENT
    except Exception:
        known_feeds = {}
        user_agent = "Mozilla/5.0 X-Tiller/1.0"

    enabled = [s for s in sources if s.get("enabled", True)]
    results = []
    with ThreadPoolExecutor(max_workers=min(8, len(enabled) or 1)) as executor:
        future_map = {
            executor.submit(probe_single_source, s, known_feeds, user_agent): s
            for s in enabled
        }
        for future in as_completed(future_map):
            results.append(future.result())

    results.sort(key=lambda r: r.get("source_id", ""))
    failed = [r for r in results if r.get("status") == "failed"]
    return {
        "mode": "probed",
        "total_probed": len(results),
        "reachable": len(results) - len(failed),
        "failed_count": len(failed),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the X-Tiller source registry.")
    parser.add_argument(
        "--file",
        type=Path,
        help="Registry file inside this repository; defaults to sources/registry.json.",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Concurrently probe live connectivity and latency of all enabled sources.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = find_repo_root()
        rules, warnings = load_rules(repo)
        for warning in warnings:
            print(f"source-registry warning: {warning}", file=sys.stderr)
        path = args.file or repo / "sources" / "registry.json"
        path = path if path.is_absolute() else repo / path
        try:
            path.resolve().relative_to(repo.resolve())
        except ValueError as exc:
            raise RegistryError("--file must stay inside the X-Tiller repository") from exc
        registry = load_registry(path)
        errors = validate_registry(registry, rules)
        if errors:
            raise RegistryError("; ".join(errors))
        sources = registry["sources"]
        priorities = sorted(rules["priorities"])

        if args.probe:
            probe_summary = probe_sources(sources)
            print(json.dumps(probe_summary, ensure_ascii=False, indent=2))
            return 1 if probe_summary["failed_count"] > 0 else 0

        print(
            json.dumps(
                {
                    "mode": "checked",
                    "registry": str(path.relative_to(repo)),
                    "sources": len(sources),
                    "enabled": sum(source["enabled"] for source in sources),
                    "rules_source": "schema" if not warnings else "builtin",
                    "max_sources": rules["max_sources"],
                    "priorities": {
                        priority: sum(source["priority"] == priority for source in sources)
                        for priority in priorities
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except RegistryError as exc:
        print(f"source-registry error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
