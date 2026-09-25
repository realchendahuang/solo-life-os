from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from datetime import date
from pathlib import Path
from types import ModuleType
from unittest import mock
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAPTURE = load_module(
    "x_tiller_capture",
    ".agents/skills/idea-capture/scripts/capture_idea.py",
)
SOURCE_REGISTRY = load_module(
    "x_tiller_source_registry",
    ".agents/skills/source-registry/scripts/check_registry.py",
)
CANDIDATE_CAPTURE = load_module(
    "x_tiller_candidate_capture",
    ".agents/skills/source-registry/scripts/capture_candidate.py",
)
WEEKLY_REVIEW = load_module(
    "x_tiller_weekly_review",
    ".agents/skills/weekly-review/scripts/build_weekly_review.py",
)
FEEDBACK = load_module(
    "x_tiller_feedback",
    ".agents/skills/post-drafter/scripts/record_feedback.py",
)
METRICS = load_module(
    "x_tiller_metrics",
    ".agents/skills/weekly-review/scripts/record_metrics.py",
)
BACKFILL = load_module(
    "x_tiller_hit_backfill",
    ".agents/skills/hit-archive/scripts/backfill_metrics.py",
)
FRONTMATTER = load_module(
    "x_tiller_frontmatter",
    ".agents/skills/hit-archive/scripts/frontmatter.py",
)
SOCIALDATA = load_module(
    "x_tiller_socialdata",
    ".agents/skills/hit-archive/scripts/socialdata_history.py",
)
TOPIC_STORE = load_module(
    "topic_store",
    ".agents/skills/topic-library/scripts/topic_store.py",
)
# The topic-library CLIs import their shared store as a top-level `topic_store`
# module via sys.path (the same pattern as hit-archive's `frontmatter`). Register
# this instance under that name so it is the one they get: otherwise the tests
# hold a second copy of the module and `assertRaises` compares two different
# TopicError classes.
sys.modules["topic_store"] = TOPIC_STORE
TOPIC_CAPTURE = load_module(
    "x_tiller_topic_capture",
    ".agents/skills/topic-library/scripts/capture_topic.py",
)
TOPIC_LIST = load_module(
    "x_tiller_topic_list",
    ".agents/skills/topic-library/scripts/list_topics.py",
)
TOPIC_UPDATE = load_module(
    "x_tiller_topic_update",
    ".agents/skills/topic-library/scripts/update_topic.py",
)


class IdeaCaptureTests(unittest.TestCase):
    def test_preserves_original_idea(self) -> None:
        args = argparse.Namespace(
            idea="  模型和 Harness 不是一回事  ",
            intent=None,
            pillar="AI and Coding Agents",
            source_url=["https://x.com/example/status/123"],
            note=[],
        )
        now = datetime(2026, 8, 30, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        record = CAPTURE.build_record(args, now)
        self.assertEqual(record["idea"], "模型和 Harness 不是一回事")
        self.assertEqual(record["status"], "captured")
        self.assertTrue(record["id"].startswith("idea-20260830-160000-"))

    def test_rejects_invalid_source_url(self) -> None:
        args = argparse.Namespace(
            idea="一个有效点子",
            intent=None,
            pillar=None,
            source_url=["not-a-url"],
            note=[],
        )
        now = datetime(2026, 8, 30, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with self.assertRaises(ValueError):
            CAPTURE.build_record(args, now)


class XFetchTests(unittest.TestCase):
    def test_help_runs_without_third_party_dependencies(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(ROOT / ".agents/skills/x-fetch/scripts/fetch_tweet.py"),
                "--help",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--text-only", result.stdout)
        self.assertIn("--ledger", result.stdout)


class SourceRegistryTests(unittest.TestCase):
    def test_tracked_registry_passes_local_validation(self) -> None:
        registry = SOURCE_REGISTRY.load_registry(ROOT / "sources" / "registry.json")
        self.assertEqual(SOURCE_REGISTRY.validate_registry(registry), [])

    def test_rejects_duplicate_ids_and_non_https_urls(self) -> None:
        source = {
            "id": "openai-api-changelog",
            "name": "OpenAI API Changelog",
            "source_url": "https://developers.openai.com/api/docs/changelog",
            "source_type": "official-changelog",
            "fetch_mode": "web-search",
            "pillars": ["AI and Coding Agents"],
            "priority": "P0",
            "cadence": "daily",
            "event_filters": ["model availability"],
            "enabled": True,
            "notes": "Primary source.",
        }
        invalid = {
            "version": 1,
            "sources": [
                source,
                dict(source, source_url="http://example.com"),
                dict(source, id="BAD"),
            ],
        }
        errors = SOURCE_REGISTRY.validate_registry(invalid)
        self.assertTrue(any("duplicates" in error for error in errors))
        self.assertTrue(any("HTTPS URL" in error for error in errors))
        self.assertTrue(any("lowercase slug" in error for error in errors))

    def test_cli_reports_registry_summary(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(ROOT / ".agents/skills/source-registry/scripts/check_registry.py"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["mode"], "checked")
        # Track the real registry size so curating sources never reddens the gate.
        tracked = json.loads((ROOT / "sources" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["sources"], len(tracked["sources"]))

    def test_candidate_canonicalizes_tracking_urls_and_hashes_content(self) -> None:
        args = argparse.Namespace(
            url="https://developers.openai.com/api/docs/changelog/?utm_source=x&version=2#latest",
            title="A specific change",
            excerpt="Faithful source excerpt.",
            author="OpenAI",
            published_at="2026-09-02T10:00:00+08:00",
            verification_status="official-primary",
            suggested_action="watch",
            tag=["api", "release", "api"],
        )
        source = SOURCE_REGISTRY.load_registry(ROOT / "sources" / "registry.json")["sources"][0]
        now = datetime(2026, 9, 2, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        candidate = CANDIDATE_CAPTURE.build_candidate(args, now, source)
        self.assertEqual(
            candidate["canonical_url"],
            "https://developers.openai.com/api/docs/changelog?version=2",
        )
        self.assertEqual(candidate["tags"], ["api", "release"])
        self.assertEqual(candidate["verification_status"], "official-primary")

    def test_candidate_rejects_non_https_url(self) -> None:
        with self.assertRaises(CANDIDATE_CAPTURE.CandidateError):
            CANDIDATE_CAPTURE.canonicalize_url("http://example.com/change")


class WeeklyReviewTests(unittest.TestCase):
    def test_builds_cautious_review_from_matching_records(self) -> None:
        now = datetime(2026, 9, 2, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        review = WEEKLY_REVIEW.build_review(
            start=date(2026, 8, 27),
            end=date(2026, 9, 2),
            now=now,
            published_records=[
                {
                    "published_at": "2026-09-01T10:00:00+08:00",
                    "post_id": "123",
                    "thread_size": 1,
                },
                {
                    "published_at": "2026-08-20T10:00:00+08:00",
                    "post_id": "older",
                    "thread_size": 2,
                },
            ],
            feedback_records=[
                {"recorded_at": "2026-09-01T09:00:00+08:00", "outcome": "edited"}
            ],
            metric_records=[
                {
                    "recorded_at": "2026-09-01T12:00:00+08:00",
                    "metric_window": "24h",
                    "post_id": "123",
                    "metrics": {"impressions": 100, "likes": 4},
                }
            ],
        )
        self.assertEqual(review["published"]["count"], 1)
        self.assertEqual(review["published"]["formats"], {"single": 1})
        self.assertEqual(review["feedback"]["outcomes"], {"edited": 1})
        self.assertEqual(
            review["metrics"]["by_window"],
            {"24h": {"record_count": 1, "post_ids": ["123"], "totals": {"impressions": 100, "likes": 4}}},
        )
        self.assertEqual(review["status"], "needs-more-data")
        self.assertTrue(any("pillar" in gap for gap in review["evidence_gaps"]))

    def test_loads_published_records_from_post_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts_dir = Path(tmp) / "posts"
            posts_dir.mkdir()
            (posts_dir / "post-20260901-001.md").write_text(
                "---\n"
                "id: post-20260901-001\n"
                "kind: published\n"
                "post_url: https://x.com/realchendahuang/status/2097730017417679038\n"
                "posted_at: '2026-09-01T10:00:00+08:00'\n"
                "---\n\n正文\n",
                encoding="utf-8",
            )
            (posts_dir / "post-20260901-002.md").write_text(
                "---\n"
                "id: post-20260901-002\n"
                "kind: published\n"
                "post_url: https://x.com/realchendahuang/status/2097730017417679039\n"
                "posted_at: '2026-09-01T11:00:00+08:00'\n"
                "pillar: AI实战\n"
                "structure: thread\n"
                "---\n\n正文\n",
                encoding="utf-8",
            )
            (posts_dir / "hit-20260628-001.md").write_text(
                "---\n"
                "id: hit-20260628-001\n"
                "kind: hit\n"
                "post_url: https://x.com/realchendahuang/status/1234567890\n"
                "posted_at: '2026-06-28T00:00:00+08:00'\n"
                "---\n\n正文\n",
                encoding="utf-8",
            )
            (posts_dir / "post-20260901-003.md").write_text(
                "---\n"
                "id: post-20260901-003\n"
                "kind: published\n"
                "post_url: https://x.com/realchendahuang/status/2097730017417679040\n"
                "---\n\n无发布时间的帖子\n",
                encoding="utf-8",
            )
            (posts_dir / "notes.txt").write_text("not markdown\n", encoding="utf-8")
            records = WEEKLY_REVIEW.load_published_from_posts(posts_dir)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["post_id"], "2097730017417679038")
        # No structure field means the size is unknown, not a fabricated single.
        self.assertIsNone(records[0]["thread_size"])
        self.assertEqual(records[1]["post_id"], "2097730017417679039")
        self.assertEqual(records[1]["thread_size"], 2)

    def test_cli_rejects_invalid_review_window(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(ROOT / ".agents/skills/weekly-review/scripts/build_weekly_review.py"),
                "--days",
                "0",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--days must be between 1 and 31", result.stderr)


class FeedbackTests(unittest.TestCase):
    def test_preserves_only_explicit_feedback(self) -> None:
        args = argparse.Namespace(
            draft_id="draft-20260902-example",
            outcome="edited",
            reason="  Too much setup before the conclusion  ",
            constraint=["Lead with the judgment", "Lead with the judgment", ""],
        )
        now = datetime(2026, 9, 2, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        record = FEEDBACK.build_record(args, now)
        self.assertEqual(record["reason"], "Too much setup before the conclusion")
        self.assertEqual(record["constraints"], ["Lead with the judgment"])
        self.assertEqual(record["outcome"], "edited")

    def test_feedback_cli_rejects_ledger_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "feedback.jsonl"
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / ".agents/skills/post-drafter/scripts/record_feedback.py"),
                    "--draft-id",
                    "draft-test",
                    "--outcome",
                    "rejected",
                    "--ledger",
                    str(ledger),
                    "--dry-run",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--ledger must stay", result.stderr)


class MetricTests(unittest.TestCase):
    def test_records_windowed_metrics_without_inference(self) -> None:
        args = argparse.Namespace(
            post_id="1234567890",
            metric_window="24h",
            window_start="2026-09-01T10:00:00+08:00",
            window_end="2026-09-02T10:00:00+08:00",
            source="x-analytics",
            impressions=1200,
            likes=34,
            replies=None,
            reposts=None,
            quotes=None,
            bookmarks=None,
            profile_visits=None,
            link_clicks=None,
            note="Recorded from the account analytics view.",
        )
        now = datetime(2026, 9, 2, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        record = METRICS.build_record(args, now)
        self.assertEqual(record["post_url"], "https://x.com/realchendahuang/status/1234567890")
        self.assertEqual(record["metrics"], {"impressions": 1200, "likes": 34})
        self.assertEqual(record["metric_window"], "24h")

    def test_rejects_metric_window_with_non_increasing_times(self) -> None:
        args = argparse.Namespace(
            post_id="1234567890",
            metric_window="24h",
            window_start="2026-09-02T10:00:00+08:00",
            window_end="2026-09-02T10:00:00+08:00",
            source="user-provided",
            impressions=1,
            likes=None,
            replies=None,
            reposts=None,
            quotes=None,
            bookmarks=None,
            profile_visits=None,
            link_clicks=None,
            note=None,
        )
        with self.assertRaises(METRICS.MetricError):
            METRICS.build_record(args, datetime(2026, 9, 2, tzinfo=ZoneInfo("Asia/Shanghai")))


class BackfillMetricsTests(unittest.TestCase):
    def test_maps_fetch_fields_to_contract_keys(self) -> None:
        tweet = {
            "views": 15853,
            "likes": 44,
            "retweets": 2,
            "replies_count": 45,
            "bookmarks": 10,
        }
        self.assertEqual(
            BACKFILL.extract_metrics(tweet),
            {"views": 15853, "likes": 44, "reposts": 2, "replies": 45, "bookmarks": 10},
        )

    def test_extract_metrics_drops_non_integers(self) -> None:
        tweet = {"views": "1.6万", "likes": 3}
        self.assertEqual(BACKFILL.extract_metrics(tweet), {"likes": 3})

    def test_parses_twitter_created_at(self) -> None:
        self.assertEqual(
            BACKFILL.parse_created_at("Sat Sep 05 02:15:18 +0000 2026"),
            "2026-09-05T02:15:18+00:00",
        )
        self.assertIsNone(BACKFILL.parse_created_at("unknown"))

    def test_split_main_body_keeps_annotations_intact(self) -> None:
        body = "帖子全文\n\n## 我的批注\n\n（想法）\n\n## 数据回采\n- 2026-09-09 snapshot: views=1\n"
        main, tail = BACKFILL.split_main_body(body)
        self.assertEqual(main, "帖子全文")
        self.assertTrue(tail.startswith("## 我的批注"))
        self.assertIn("views=1", tail)

    def test_recycle_line_is_idempotent(self) -> None:
        now = datetime(2026, 9, 9, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        line = BACKFILL.recycle_line(now, {"views": 100, "likes": 3})
        self.assertEqual(line, "- 2026-09-09 20:00 snapshot: views=100 likes=3")
        once, appended = BACKFILL.append_recycle("正文\n", line)
        self.assertTrue(appended)
        self.assertIn("## 数据回采", once)
        twice, appended_again = BACKFILL.append_recycle(once, line)
        self.assertFalse(appended_again)
        self.assertEqual(twice, once)

    def test_backfill_file_merges_metrics_and_fills_posted_at(self) -> None:
        path = Path("post-x.md")
        payload = {
            "tweet": {
                "text": "原样全文",
                "created_at": "Sat Sep 05 02:15:18 +0000 2026",
                "views": 100,
                "likes": 3,
            }
        }
        meta, body, changes = BACKFILL.backfill_file(
            path,
            {"id": "post-x", "kind": "published"},
            "摘要版正文\n\n## 我的批注\n\n（占位）\n",
            payload,
            sync_text=True,
            now=datetime(2026, 9, 9, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertEqual(meta["metrics"], {"views": 100, "likes": 3})
        self.assertEqual(meta["posted_at"], "2026-09-05T02:15:18+00:00")
        self.assertTrue(body.startswith("原样全文\n\n## 我的批注"))
        self.assertIn("## 数据回采", body)
        self.assertTrue(any("verbatim-synced" in change for change in changes))

    def test_backfill_file_reports_fetch_failure_without_touching_body(self) -> None:
        meta, body, changes = BACKFILL.backfill_file(
            Path("post-x.md"),
            {"id": "post-x"},
            "原正文",
            {"error_code": "rate_limited"},
            sync_text=True,
            now=datetime(2026, 9, 9, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertEqual(body, "原正文")
        self.assertEqual(changes, ["fetch failed (rate_limited)"])


class PostArchiveTests(unittest.TestCase):
    """The archive is the fact source for reports; keep its invariants checked."""

    def test_checked_in_archive_entries_carry_numeric_status_urls(self) -> None:
        posts_dir = ROOT / "workspace" / "posts"
        if not posts_dir.is_dir():
            self.skipTest("post archive is not present in this checkout")
        entries = sorted(posts_dir.glob("*.md"))
        self.assertTrue(entries, "post archive should not be empty")
        for path in entries:
            with self.subTest(post=path.name):
                meta, _ = FRONTMATTER.load(path)
                self.assertEqual(
                    meta.get("id"), path.stem, "frontmatter id must match the filename"
                )
                self.assertIn(meta.get("kind"), {"hit", "published"})
                self.assertTrue(meta.get("collected_at"))
                url = (meta.get("post_url") or "").split("?")[0].rstrip("/")
                match = re.match(r"https://x\.com/[^/]+/status/(\d+)$", url)
                self.assertIsNotNone(
                    match,
                    f"{path.name}: post_url must be an x.com status URL with a "
                    f"numeric id, got {meta.get('post_url')!r}",
                )


class TopicLibraryTests(unittest.TestCase):
    """The library is the dedupe and backlog ledger; keep its rules honest."""

    def _args(self, *argv: str) -> argparse.Namespace:
        return TOPIC_CAPTURE.build_parser().parse_args(list(argv))

    def _update_args(self, *argv: str) -> argparse.Namespace:
        return TOPIC_UPDATE.build_parser().parse_args(list(argv))

    def test_capture_keeps_the_statement_verbatim(self) -> None:
        args = self._args(
            "  模型和 Harness 不能混为一谈，Plan 模式尤其明显  ",
            "--pillar",
            "ai-coding-agents",
        )
        now = datetime(2026, 9, 19, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        record = TOPIC_CAPTURE.build_record(args, now, ROOT)
        self.assertEqual(record["statement"], "模型和 Harness 不能混为一谈，Plan 模式尤其明显")
        self.assertEqual(record["status"], "candidate")
        # Simplified contract (2026-09-24): defaults are omitted, not written.
        self.assertNotIn("source", record)
        self.assertTrue(str(record["id"]).startswith("topic-20260919-153000-"))
        self.assertNotIn("updated_at", record)
        # No title given: the label falls back to the statement's first line.
        self.assertEqual(record["title"], record["statement"])
        # Unstated positions and unassigned tags are omitted, never invented.
        self.assertNotIn("thesis", record)
        self.assertNotIn("column_id", record)
        self.assertNotIn("target_asset", record)

        # With column and asset specified
        args_with_column = self._args(
            "OPC 公司报税实战",
            "--column",
            "opc-handbook",
            "--asset",
            "ebook",
        )
        record_with_column = TOPIC_CAPTURE.build_record(args_with_column, now, ROOT)
        self.assertEqual(record_with_column["column_id"], "opc-handbook")
        self.assertEqual(record_with_column["target_asset"], "ebook")

    def test_capture_rejects_invalid_sources(self) -> None:
        now = datetime(2026, 9, 19, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        with self.assertRaises(TOPIC_STORE.TopicError):
            TOPIC_CAPTURE.build_record(
                self._args("有个选题", "--source-url", "not-a-url"), now, ROOT
            )
        with self.assertRaises(TOPIC_STORE.TopicError):
            TOPIC_CAPTURE.build_record(
                self._args("有个选题", "--source-ref", "../../etc/passwd"), now, ROOT
            )

    def test_duplicate_detection_ignores_case_spacing_and_punctuation(self) -> None:
        now = datetime(2026, 9, 19, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        first = TOPIC_CAPTURE.build_record(
            self._args("Git Worktree 在 AI 并行开发里到底值不值得用", "--title", "Git Worktree × 多 Agent 并行"),
            now,
            ROOT,
        )
        stored = [(Path("topic-one.json"), first)]
        # Same title modulo case and punctuation, and same statement modulo
        # spacing: both are the same topic, not two.
        for args in (
            self._args("另一条完全不同的说法", "--title", "git worktree × 多 Agent 并行"),
            self._args("Git  Worktree 在 AI 并行开发里，到底值不值得用"),
        ):
            candidate = TOPIC_CAPTURE.build_record(args, now, ROOT)
            match = TOPIC_STORE.find_duplicate(
                stored,
                title=str(candidate["title"]),
                statement=str(candidate["statement"]),
            )
            self.assertIsNotNone(match)
        # A short title must not fuzzy-match a longer unrelated one, and a
        # different topic must pass: a false duplicate hides real work.
        other = TOPIC_CAPTURE.build_record(
            self._args("Cloudflare 那套穷鬼全家桶怎么配", "--title", "穷鬼全家桶"),
            now,
            ROOT,
        )
        self.assertIsNone(
            TOPIC_STORE.find_duplicate(
                stored, title=str(other["title"]), statement=str(other["statement"])
            )
        )
        self.assertIsNone(
            TOPIC_STORE.find_duplicate(stored, title="Codex 的配额", statement="Codex 的配额到底怎么算")
        )

    def test_update_advances_status_and_appends_backlinks_once(self) -> None:
        record = TOPIC_CAPTURE.build_record(
            self._args("Git Worktree 值不值得用", "--title", "Git Worktree"),
            datetime(2026, 9, 19, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            ROOT,
        )
        args = self._update_args(
            "--id",
            "topic-20260919-153012-ab12cd34ef",
            "--status",
            "parked",
            "--brief-id",
            "brief-20260919-git-worktree",
            "--note",
            "先写机制那条",
        )
        changed = TOPIC_UPDATE.apply_changes(record, args, ROOT)
        self.assertEqual(record["status"], "parked")
        self.assertEqual(record["brief_ids"], ["brief-20260919-git-worktree"])
        self.assertEqual(record["notes"], ["先写机制那条"])
        self.assertIn("status", changed)
        # Re-running the same update must not duplicate the backlink.
        TOPIC_UPDATE.apply_changes(record, args, ROOT)
        self.assertEqual(record["brief_ids"], ["brief-20260919-git-worktree"])
        self.assertEqual(record["notes"], ["先写机制那条"])

        # Update column and asset
        col_args = self._update_args(
            "--id",
            "topic-20260919-153012-ab12cd34ef",
            "--column",
            "hacker-craft",
            "--asset",
            "repo",
        )
        col_changed = TOPIC_UPDATE.apply_changes(record, col_args, ROOT)
        self.assertEqual(record["column_id"], "hacker-craft")
        self.assertEqual(record["target_asset"], "repo")
        self.assertIn("column_id", col_changed)
        self.assertIn("target_asset", col_changed)

    def test_update_requires_evidence_for_terminal_states(self) -> None:
        record = TOPIC_CAPTURE.build_record(
            self._args("一条选题"),
            datetime(2026, 9, 19, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            ROOT,
        )
        with self.assertRaises(TOPIC_STORE.TopicError):
            TOPIC_UPDATE.apply_changes(
                record, self._update_args("--id", "topic-x", "--status", "published"), ROOT
            )
        with self.assertRaises(TOPIC_STORE.TopicError):
            TOPIC_UPDATE.apply_changes(
                record, self._update_args("--id", "topic-x", "--status", "dropped"), ROOT
            )
        TOPIC_UPDATE.apply_changes(
            record,
            self._update_args(
                "--id",
                "topic-x",
                "--status",
                "published",
                "--post-url",
                "https://x.com/realchendahuang/status/2097730017417679038",
            ),
            ROOT,
        )
        self.assertEqual(record["status"], "published")
        self.assertEqual(len(record["post_urls"]), 1)

    def test_update_rejects_malformed_backlink_ids(self) -> None:
        record = TOPIC_CAPTURE.build_record(
            self._args("一条选题"),
            datetime(2026, 9, 19, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            ROOT,
        )
        with self.assertRaises(TOPIC_STORE.TopicError):
            TOPIC_UPDATE.apply_changes(
                record, self._update_args("--id", "topic-x", "--brief-id", "简报一"), ROOT
            )

    def test_list_filters_and_counts_unwritten(self) -> None:
        def topic(title: str, status: str, pillar: str | None) -> tuple[Path, dict]:
            return (
                Path(f"{title}.json"),
                {
                    "id": f"topic-{title}",
                    "title": title,
                    "status": status,
                    "pillar_id": pillar,
                    "created_at": "2026-09-19T15:30:12+08:00",
                },
            )

        topics = [
            topic("a", "candidate", "ai-coding-agents"),
            topic("b", "briefed", "indie-dev"),
            topic("c", "published", "ai-coding-agents"),
            topic("d", "parked", None),
        ]
        self.assertEqual(
            [record["title"] for record in TOPIC_LIST.select(topics, set(), set())],
            ["a", "b", "c", "d"],
        )
        self.assertEqual(
            [record["title"] for record in TOPIC_LIST.select(topics, {"candidate", "briefed"}, set())],
            ["a", "b"],
        )
        self.assertEqual(
            [record["title"] for record in TOPIC_LIST.select(topics, set(), {"ai-coding-agents"})],
            ["a", "c"],
        )
        rendered = TOPIC_LIST.render(TOPIC_LIST.select(topics, set(), set()), len(topics))
        # Only live candidates count toward the unwritten queue; legacy
        # briefed/drafted entries are readable but no longer "unwritten".
        self.assertIn("选题库 4 条（未写 1）", rendered)
        self.assertIn("parked (1)", rendered)
        # An absent library is a normal state and must say how to start one.
        self.assertIn("选题库为空", TOPIC_LIST.render([], 0))

    def test_cli_round_trip_writes_a_contract_shaped_file(self) -> None:
        library = Path(tempfile.mkdtemp(dir=ROOT / "workspace", prefix=".tmp-topic-test."))
        try:
            captured = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".agents/skills/topic-library/scripts/capture_topic.py"),
                    "CLI 往返校验用选题",
                    "--title",
                    "CLI 往返校验",
                    "--pillar",
                    "indie-dev",
                    "--library",
                    str(library),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(captured.returncode, 0, captured.stderr)
            payload = json.loads(captured.stdout)
            self.assertEqual(payload["mode"], "saved")
            import topic_store as _store  # loaded earlier in this module
            written = _store.load_topic(library / f"{payload['topic']['id']}.md")
            self.assertEqual(written["statement"], "CLI 往返校验用选题")
            self.assertNotIn("source", written)  # simplified contract: defaults omitted

            # The same statement again is refused rather than duplicated.
            again = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".agents/skills/topic-library/scripts/capture_topic.py"),
                    "CLI 往返校验用选题",
                    "--library",
                    str(library),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(again.returncode, 2)
            self.assertIn("already in the library", again.stderr)

            listed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".agents/skills/topic-library/scripts/list_topics.py"),
                    "--library",
                    str(library),
                    "--json",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(json.loads(listed.stdout)["count"], 1)

            updated = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".agents/skills/topic-library/scripts/update_topic.py"),
                    "--id",
                    str(written["id"]),
                    "--status",
                    "parked",
                    "--draft-id",
                    "draft-20260919-cli-round-trip",
                    "--library",
                    str(library),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)
            self.assertEqual(json.loads(updated.stdout)["mode"], "updated")
            final = TOPIC_STORE.load_topic(library / f"{written['id']}.md")
            self.assertEqual(final["status"], "parked")
            self.assertEqual(final["draft_ids"], ["draft-20260919-cli-round-trip"])
            self.assertGreaterEqual(final["updated_at"], final["created_at"])

            # A library outside the repository is refused, like every other
            # writer in this repo.
            outside = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".agents/skills/topic-library/scripts/capture_topic.py"),
                    "越界写入",
                    "--library",
                    "/tmp",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(outside.returncode, 2)
            self.assertIn("must stay inside", outside.stderr)
        finally:
            shutil.rmtree(library, ignore_errors=True)


class SocialDataHistoryTests(unittest.TestCase):
    def test_maps_fields_to_contract_metrics(self) -> None:
        tweet = {
            "views_count": 32377,
            "favorite_count": 977,
            "retweet_count": 78,
            "reply_count": 156,
            "quote_count": 11,
            "bookmark_count": 19,
        }
        self.assertEqual(
            SOCIALDATA.parse_metrics(tweet),
            {"views": 32377, "likes": 977, "reposts": 78,
             "replies": 156, "quotes": 11, "bookmarks": 19},
        )

    def test_prefers_note_tweet_text_then_full_text(self) -> None:
        note = {"note_tweet": {"note_tweet_results": {"text": "长文正文"}}}
        self.assertEqual(SOCIALDATA.tweet_text(note), "长文正文")
        plain = {"full_text": "短帖正文", "text": None}
        self.assertEqual(SOCIALDATA.tweet_text(plain), "短帖正文")

    def test_parses_created_at_and_classifies_tweets(self) -> None:
        tweet = {"tweet_created_at": "Wed Sep 09 03:19:28 +0000 2026"}
        self.assertEqual(SOCIALDATA.parse_posted_at(tweet), "2026-09-09T03:19:28+00:00")
        iso = {"tweet_created_at": "2026-09-09T16:54:51.000000Z"}
        self.assertEqual(SOCIALDATA.parse_posted_at(iso), "2026-09-09T16:54:51+00:00")
        self.assertTrue(SOCIALDATA.is_pure_retweet(
            {"retweeted_status": {"id_str": "999", "full_text": "原文"}}))
        self.assertTrue(SOCIALDATA.is_reply({"in_reply_to_status_id_str": "123"}))
        self.assertFalse(SOCIALDATA.is_reply({"quoted_status_id_str": "123"}))


class FlywheelImprovementsTests(unittest.TestCase):
    def test_triage_topics_scoring_and_blueprint(self) -> None:
        triage_mod = load_module(
            "x_tiller_triage_topics",
            ".agents/skills/topic-library/scripts/triage_topics.py",
        )
        record = {
            "id": "topic-test-001",
            "title": "Cloudflare 穷鬼全家桶实战",
            "statement": "如何用 Cloudflare 搭建个人知识管理系统？免费额度算账与最佳实践",
            "pillar_id": "indie-dev",
            "status": "candidate",
        }
        res = triage_mod.score_topic(record)
        self.assertGreaterEqual(res["score"], 20)
        self.assertIn(res["blueprint"], {"A", "B", "C", "D", "E"})

    # scaffold_draft.py and scaffold_brief.py retired 2026-09-24: writing and
    # angle selection happen in conversation and produce no artifact files.

    def test_audit_post_feedback_constraints(self) -> None:
        audit_mod = load_module(
            "x_tiller_audit_post",
            ".agents/skills/hit-playbook/scripts/audit_post.py",
        )
        bad_text = "今天在工位上班，感觉总的来说这个“方案”不错。\n```python\nprint(1)\n```"
        res = audit_mod.audit_text(bad_text)
        fail_msgs = [msg for status, msg in res["findings"] if status == "FAIL"]
        warn_msgs = [msg for status, msg in res["findings"] if status == "WARN"]
        self.assertTrue(any("社畜" in m or "打工" in m for m in fail_msgs))
        self.assertTrue(any("引号" in m for m in fail_msgs))
        self.assertTrue(any("代码块" in m for m in warn_msgs))

    def test_audit_post_exits_nonzero_on_fail_with_flag(self) -> None:
        """Without this the audit could never gate anything: a FAIL still returned exit 0."""
        audit_mod = load_module(
            "x_tiller_audit_post_gate",
            ".agents/skills/hit-playbook/scripts/audit_post.py",
        )
        bad_text = "今天在工位上班，感觉总的来说这个方案不错。"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for argv, expected in (
                (["audit_post.py", "--text", bad_text], 0),
                (["audit_post.py", "--text", bad_text, "--fail-on-fail"], 2),
            ):
                with self.subTest(flag=argv[-1]):
                    with mock.patch.object(sys, "argv", argv):
                        try:
                            audit_mod.main()
                        except SystemExit as exc:
                            self.assertEqual(exc.code, expected)
                        else:
                            self.assertEqual(expected, 0, "expected SystemExit(2)")

    def test_audit_post_reports_a_corrupt_ledger_line(self) -> None:
        """A bad ledger line must not silently drop the user's earlier constraints."""
        audit_mod = load_module(
            "x_tiller_audit_post_ledger",
            ".agents/skills/hit-playbook/scripts/audit_post.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "workspace" / "feedback"
            ledger.mkdir(parents=True)
            (ledger / "ledger.jsonl").write_text(
                '{"id": "a", "draft_id": "d1", "constraints": ["不要社畜字眼"]}\n'
                "this is not json\n",
                encoding="utf-8",
            )
            # audit_text derives the repo root as parents[4] of its own __file__, so the
            # fixture is reached by pointing __file__ deep enough under the temp root.
            fake_file = str(root / "a" / "b" / "c" / "d" / "audit_post.py")
            with mock.patch.object(audit_mod, "__file__", fake_file):
                res = audit_mod.audit_text("一段普通正文。")
            self.assertTrue(res["ledger_warnings"], res)
            self.assertIn("不要社畜字眼", res["active_constraints"])


if __name__ == "__main__":
    unittest.main()
