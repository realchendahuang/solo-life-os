"""Validate every checked-in artifact against its contract schema.

The repo's contracts are the machine-readable hand-off format between skills
(AGENTS.md). Until now the quality gate only ran `json.tool` on the schema
files, which proves they are parseable JSON and nothing else, so nothing
caught drift between a schema and the artifacts it governs.

`jsonschema` is deliberately not a dependency: this module implements the
small subset the contracts actually use (type, required, properties,
additionalProperties, enum/const, items, minItems/maxItems, minLength,
minProperties, minimum/maximum, pattern, format, allOf, if/then, anyOf/oneOf).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import unittest
import urllib.parse

try:
    import yaml
except ImportError:
    yaml = None
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


class SchemaError(AssertionError):
    """Raised when a value does not satisfy a schema."""


def _type_ok(value, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    raise SchemaError(f"unsupported schema type: {expected}")


def _json_equal(a, b) -> bool:
    """Compare enum/const members with JSON semantics (1 != True)."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def validate(value, schema: dict, path: str = "$") -> None:
    if not isinstance(schema, dict):
        raise SchemaError(f"{path}: schema must be an object")

    if "type" in schema:
        types = schema["type"]
        types = types if isinstance(types, list) else [types]
        if not any(_type_ok(value, t) for t in types):
            raise SchemaError(
                f"{path}: expected type {types}, got {type(value).__name__}"
            )

    if "const" in schema and not _json_equal(value, schema["const"]):
        raise SchemaError(f"{path}: expected const {schema['const']!r}, got {value!r}")

    if "enum" in schema:
        if not any(_json_equal(value, option) for option in schema["enum"]):
            raise SchemaError(f"{path}: {value!r} not in enum {schema['enum']}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaError(f"{path}: shorter than minLength {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise SchemaError(f"{path}: does not match pattern {schema['pattern']!r}")
        fmt = schema.get("format")
        if fmt == "date-time":
            try:
                parsed = dt.datetime.fromisoformat(value)
            except ValueError as exc:
                raise SchemaError(f"{path}: not a valid date-time ({exc})")
            if parsed.tzinfo is None:
                raise SchemaError(f"{path}: date-time must carry a timezone offset")
        elif fmt == "date":
            try:
                dt.date.fromisoformat(value)
            except ValueError as exc:
                raise SchemaError(f"{path}: not a valid date ({exc})")
        elif fmt == "uri":
            parsed = urllib.parse.urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                raise SchemaError(f"{path}: not an absolute URI")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaError(f"{path}: above maximum {schema['maximum']}")

    for sub in schema.get("allOf", []):
        validate(value, sub, path)

    if "if" in schema:
        try:
            validate(value, schema["if"], path)
            branch_ok = True
        except SchemaError:
            branch_ok = False
        branch = schema.get("then") if branch_ok else schema.get("else")
        if isinstance(branch, dict):
            validate(value, branch, path)

    for key in ("anyOf", "oneOf"):
        if key in schema:
            matches = 0
            last_error = None
            for sub in schema[key]:
                try:
                    validate(value, sub, path)
                    matches += 1
                except SchemaError as exc:
                    last_error = exc
            if key == "anyOf" and matches == 0:
                raise SchemaError(f"{path}: no anyOf branch matched ({last_error})")
            if key == "oneOf" and matches != 1:
                raise SchemaError(f"{path}: expected exactly one oneOf match, got {matches}")

    if isinstance(value, dict):
        for field in schema.get("required", []):
            if field not in value:
                raise SchemaError(f"{path}: missing required field {field!r}")
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            raise SchemaError(f"{path}: fewer than minProperties {schema['minProperties']}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}")
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    raise SchemaError(f"{path}: unexpected field {key!r}")
                if isinstance(extra, dict):
                    validate(item, extra, f"{path}.{key}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaError(f"{path}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaError(f"{path}: more than maxItems {schema['maxItems']}")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                validate(item, items, f"{path}[{index}]")


def load_schema(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def iter_artifacts() -> list[tuple[str, str, object]]:
    """(schema file, human label, parsed value) for every available artifact.

    Runtime artifacts live under `workspace/`, which is git-ignored because it
    holds personal drafts and metrics — a clean checkout legitimately contains
    only `sources/registry.json`. Every artifact that IS present must validate;
    absence is not a failure, which is why this returns whatever exists rather
    than a fixed list.
    """
    found: list[tuple[str, str, object]] = []

    for path in sorted((ROOT / "workspace" / "inbox").glob("*.json")):
        found.append(("idea.schema.json", str(path.relative_to(ROOT)), json.loads(path.read_text(encoding="utf-8"))))

    for path in sorted((ROOT / "workspace" / "topics").glob("*.json")):
        found.append(("topic.schema.json", str(path.relative_to(ROOT)), json.loads(path.read_text(encoding="utf-8"))))

    for path in sorted((ROOT / "workspace" / "signals").glob("*.json")):
        found.append(("signal.schema.json", str(path.relative_to(ROOT)), json.loads(path.read_text(encoding="utf-8"))))

    candidates_ledger = ROOT / "workspace" / "candidates.jsonl"
    if candidates_ledger.exists():
        for number, line in enumerate(candidates_ledger.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip():
                found.append(("candidate-signal.schema.json", f"{candidates_ledger.relative_to(ROOT)}:{number}", json.loads(line)))

    ledger = ROOT / "workspace" / "feedback" / "ledger.jsonl"
    if ledger.exists():
        for number, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip():
                found.append(("feedback.schema.json", f"{ledger.relative_to(ROOT)}:{number}", json.loads(line)))

    for name, schema in (("metrics", "metric-snapshot.schema.json"), ("reviews", "weekly-review.schema.json")):
        for path in sorted((ROOT / "workspace" / name).glob("*.json*")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if line.strip():
                    label = str(path.relative_to(ROOT)) if path.suffix == ".json" else f"{path.relative_to(ROOT)}:{number}"
                    found.append((schema, label, json.loads(line)))

    found.append(("source-registry.schema.json", "sources/registry.json", json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))))
    return found


class ContractValidationTests(unittest.TestCase):
    def test_every_schema_declares_a_dialect_and_describes_an_object(self) -> None:
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("$schema", schema, "schemas must declare their dialect")
                self.assertEqual(schema["type"], "object")

    def test_every_artifact_satisfies_its_contract(self) -> None:
        artifacts = iter_artifacts()
        # sources/registry.json is tracked, so at least it is always present.
        # Everything else is git-ignored runtime data and may be absent on a
        # clean checkout (CI); present artifacts are still all validated.
        self.assertGreaterEqual(len(artifacts), 1, "no artifact was discovered at all")
        for schema_name, label, value in artifacts:
            with self.subTest(artifact=label):
                validate(value, load_schema(schema_name), path=label)

    def test_validator_rejects_known_bad_shapes(self) -> None:
        """A validator that never fails is worthless; prove it bites."""
        idea_schema = load_schema("idea.schema.json")
        valid_idea = {
            "id": "idea-20260917-000000-00000000",
            "captured_at": "2026-09-17T00:00:00+08:00",
            "idea": "原始想法",
            "intent": "preserve",
            "possible_pillar": "AI and Coding Agents",
            "source_urls": [],
            "notes": [],
            "status": "captured",
        }
        validate(valid_idea, idea_schema)
        with self.assertRaises(SchemaError):
            validate({k: v for k, v in valid_idea.items() if k != "idea"}, idea_schema)
        with self.assertRaises(SchemaError):
            validate(dict(valid_idea, status="not-a-real-status"), idea_schema)
        with self.assertRaises(SchemaError):
            validate(dict(valid_idea, captured_at="not-a-timestamp"), idea_schema)
        with self.assertRaises(SchemaError):
            validate(dict(valid_idea, surprise=True), idea_schema)

    def test_topic_library_schema_bites(self) -> None:
        """The topic contract has to hold the lifecycle honest on its own.

        `update_topic.py` refuses the same two transitions, but a hand-edited
        file under workspace/topics/ never passes through that script, and the
        library is what later questions ("did I already cover this?") are
        answered from.
        """
        schema = load_schema("topic.schema.json")
        topic = {
            "id": "topic-20260919-153012-ab12cd34ef",
            "created_at": "2026-09-19T15:30:12+08:00",
            "updated_at": "2026-09-19T15:30:12+08:00",
            "title": "Git Worktree × 多 Agent 并行",
            "statement": "Git Worktree 在 AI 并行开发里到底值不值得用",
            "status": "candidate",
            "source": "user",
            "source_refs": [],
            "source_urls": [],
            "pillar_id": "ai-coding-agents",
            "column_id": "hacker-craft",
            "target_asset": "repo",
            "thesis": None,
            "notes": [],
            "brief_ids": [],
            "draft_ids": [],
            "post_urls": [],
            "dropped_reason": None,
        }
        validate(topic, schema)
        # An unassigned pillar/column/asset and an unstated position are legitimate states.
        validate(dict(topic, pillar_id=None, column_id=None, target_asset=None, thesis=None), schema)
        # "published" without the post, and "dropped" without the reason, are the
        # two claims the library must not be able to make without evidence.
        with self.assertRaises(SchemaError):
            validate(dict(topic, status="published"), schema)
        validate(dict(topic, status="published", post_urls=["https://x.com/realchendahuang/status/123"]), schema)
        with self.assertRaises(SchemaError):
            validate(dict(topic, status="dropped"), schema)
        validate(dict(topic, status="dropped", dropped_reason="与已发帖观点重复"), schema)
        # Backlinks are ids, not free text, so they stay joinable.
        with self.assertRaises(SchemaError):
            validate(dict(topic, brief_ids=["选题简报一"]), schema)
        with self.assertRaises(SchemaError):
            validate(dict(topic, pillar_id="ai-coding"), schema)
        with self.assertRaises(SchemaError):
            validate(dict(topic, statement=""), schema)

    def test_boolean_is_not_an_integer(self) -> None:
        with self.assertRaises(SchemaError):
            validate(True, {"type": "integer"})
        with self.assertRaises(SchemaError):
            validate(1, {"type": "boolean"})


class LinkageTests(unittest.TestCase):
    """Cross-artifact references, which per-file schemas structurally cannot check.

    A topic holding a `brief_ids` entry for a brief that was deleted passes every
    schema in this repository; the reference only resolves when files are compared.
    These tests use a scratch tree and a tiny collector so they run identically on
    a clean checkout.
    """

    @staticmethod
    def _collect(root: Path) -> tuple[list[str], dict[str, int]]:
        """Dangling backlinks reported, orphan topic count.

        Deliberately minimal replacement for the retired scripts/quality_gate.py
        linkage check: topics/*.md carry brief_ids / post_urls in frontmatter
        (legacy draft_ids are historical references only — draft files were
        retired 2026-09-24 and never checked); posts are workspace/posts/*.md
        with a post_url field.
        """
        import yaml

        topics_dir = root / "workspace" / "topics"
        posts_dir = root / "workspace" / "posts"

        post_urls = set()
        for path in posts_dir.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            if m:
                try:
                    data = yaml.safe_load(m.group(1)) or {}
                except Exception:
                    data = {}
                url = str(data.get("post_url") or "").strip()
                if url:
                    post_urls.add(url)

        dangling: list[str] = []
        orphans = 0
        for path in topics_dir.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            if not m:
                continue
            try:
                fm = yaml.safe_load(m.group(1)) or {}
            except Exception:
                continue
            for brief_id in fm.get("brief_ids") or []:
                if not (root / "workspace" / "briefs" / f"{brief_id}.json").exists():
                    dangling.append(f"{path.name}: brief {brief_id} missing")
            for url in fm.get("post_urls") or []:
                if url not in post_urls:
                    dangling.append(f"{path.name}: {url} has no archive entry")
            briefs = fm.get("brief_ids") or []
            urls = fm.get("post_urls") or []
            if not (briefs or urls):
                orphans += 1
        return dangling, {"topics": orphans}

    def _write_topic(self, root: Path, topic: dict) -> None:
        import sys as _sys

        scripts = ROOT / ".agents" / "skills" / "topic-library" / "scripts"
        if str(scripts) not in _sys.path:
            _sys.path.insert(0, str(scripts))
        import topic_store as store

        directory = root / "workspace" / "topics"
        directory.mkdir(parents=True, exist_ok=True)
        store.atomic_write(directory / f"{topic['id']}.md", topic)

    def test_missing_brief_is_reported_draft_ids_ignored(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace" / "posts").mkdir(parents=True)
            (root / "workspace" / "feedback").mkdir(parents=True)
            self._write_topic(
                root,
                {
                    "id": "topic-1",
                    "brief_ids": ["brief-missing"],
                    "draft_ids": ["draft-missing"],
                    "post_urls": ["https://x.com/realchendahuang/status/123"],
                },
            )
            dangling, _orphans = self._collect(root)
        joined = " | ".join(dangling)
        self.assertIn("brief-missing", joined)
        # draft_ids are legacy references; draft files no longer exist to check.
        self.assertNotIn("draft-missing", joined)
        self.assertIn("no archive entry", joined)

    def test_resolvable_references_produce_no_findings(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace" / "topics").mkdir(parents=True)
            briefs = root / "workspace" / "briefs"
            briefs.mkdir(parents=True)
            (briefs / "brief-1.json").write_text(
                json.dumps({"id": "brief-1"}), encoding="utf-8"
            )
            posts = root / "workspace" / "posts"
            posts.mkdir(parents=True)
            (posts / "post-20260920-001.md").write_text(
                "---\n"
                "id: post-20260920-001\n"
                "kind: published\n"
                "post_url: https://x.com/realchendahuang/status/123\n"
                "collected_at: '2026-09-20T10:00:00+08:00'\n"
                "draft_id: draft-1\n"
                "---\n\n正文\n",
                encoding="utf-8",
            )
            self._write_topic(
                root,
                {
                    "id": "topic-1",
                    "brief_ids": ["brief-1"],
                    "draft_ids": ["draft-1"],
                    "post_urls": ["https://x.com/realchendahuang/status/123"],
                },
            )
            dangling, orphans = self._collect(root)
        self.assertEqual(dangling, [])
        self.assertEqual(orphans["topics"], 0)

    def test_archived_post_pointing_at_a_missing_draft_is_not_reported(self) -> None:
        """draft_id references no longer resolve against anything (retired 2026-09-24)."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace" / "topics").mkdir(parents=True)
            posts = root / "workspace" / "posts"
            posts.mkdir(parents=True)
            (posts / "post-20260920-001.md").write_text(
                "---\n"
                "id: post-20260920-001\n"
                "kind: published\n"
                "post_url: https://x.com/realchendahuang/status/123\n"
                "collected_at: '2026-09-20T10:00:00+08:00'\n"
                "draft_id: draft-vanished\n"
                "---\n\n正文\n",
                encoding="utf-8",
            )
            self._write_topic(
                root,
                {
                    "id": "topic-1",
                    "draft_ids": ["draft-vanished"],
                    "post_urls": ["https://x.com/realchendahuang/status/123"],
                },
            )
            dangling, _orphans = self._collect(root)
        self.assertEqual(dangling, [])

    def test_orphan_topics_are_counted_not_failed(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("posts", "feedback"):
                (root / "workspace" / name).mkdir(parents=True)
            self._write_topic(root, {"id": "topic-lonely", "brief_ids": []})
            dangling, orphans = self._collect(root)
        self.assertEqual(dangling, [])
        self.assertEqual(orphans["topics"], 1)


if __name__ == "__main__":
    unittest.main()
