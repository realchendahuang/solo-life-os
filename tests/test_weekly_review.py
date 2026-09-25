from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def load_module(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WEEKLY_REVIEW = load_module(
    "x_tiller_weekly_review_contract",
    ".agents/skills/weekly-review/scripts/build_weekly_review.py",
)
FEEDBACK = load_module(
    "x_tiller_feedback_contract",
    ".agents/skills/post-drafter/scripts/record_feedback.py",
)


def build_review(**overrides: object) -> dict:
    kwargs: dict[str, object] = {
        "start": date(2026, 9, 12),
        "end": date(2026, 9, 18),
        "now": datetime(2026, 9, 18, 12, 0, tzinfo=SHANGHAI),
        "published_records": [],
        "feedback_records": [],
        "metric_records": [],
    }
    kwargs.update(overrides)
    return WEEKLY_REVIEW.build_review(**kwargs)


class LatestSnapshotTests(unittest.TestCase):
    def test_two_snapshots_of_one_post_in_one_window_keep_only_latest(self) -> None:
        review = build_review(
            metric_records=[
                {
                    "recorded_at": "2026-09-16T09:00:00+08:00",
                    "metric_window": "24h",
                    "post_id": "100",
                    "metrics": {"impressions": 100, "likes": 4},
                },
                {
                    "recorded_at": "2026-09-16T15:00:00+08:00",
                    "metric_window": "24h",
                    "post_id": "100",
                    "metrics": {"impressions": 180, "likes": 9},
                },
            ]
        )
        self.assertEqual(
            review["metrics"]["by_window"],
            {
                "24h": {
                    "record_count": 1,
                    "post_ids": ["100"],
                    "totals": {"impressions": 180, "likes": 9},
                }
            },
        )

    def test_snapshots_without_recorded_at_fall_back_to_ledger_order(self) -> None:
        # build_review only considers dated records, so exercise the dedupe
        # helper directly for the undated fallback.
        selected = WEEKLY_REVIEW.latest_snapshots_by_post(
            [
                {
                    "metric_window": "24h",
                    "post_id": "100",
                    "metrics": {"impressions": 100},
                },
                {
                    "metric_window": "24h",
                    "post_id": "100",
                    "metrics": {"impressions": 180},
                },
            ]
        )
        self.assertEqual(len(selected["24h"]), 1)
        self.assertEqual(selected["24h"][0]["metrics"], {"impressions": 180})

    def test_distinct_posts_in_one_window_are_still_summed(self) -> None:
        review = build_review(
            metric_records=[
                {
                    "recorded_at": "2026-09-16T09:00:00+08:00",
                    "metric_window": "24h",
                    "post_id": "100",
                    "metrics": {"impressions": 100},
                },
                {
                    "recorded_at": "2026-09-16T09:00:00+08:00",
                    "metric_window": "24h",
                    "post_id": "200",
                    "metrics": {"impressions": 20},
                },
            ]
        )
        self.assertEqual(
            review["metrics"]["by_window"]["24h"],
            {
                "record_count": 2,
                "post_ids": ["100", "200"],
                "totals": {"impressions": 120},
            },
        )


class CustomWindowTests(unittest.TestCase):
    def test_different_custom_windows_never_merge(self) -> None:
        review = build_review(
            metric_records=[
                {
                    "recorded_at": "2026-09-16T16:00:00+08:00",
                    "metric_window": "custom",
                    "window_start": "2026-09-15T10:00:00+08:00",
                    "window_end": "2026-09-16T10:00:00+08:00",
                    "post_id": "111",
                    "metrics": {"impressions": 120},
                },
                {
                    "recorded_at": "2026-09-17T09:00:00+08:00",
                    "metric_window": "custom",
                    "window_start": "2026-09-16T10:00:00+08:00",
                    "window_end": "2026-09-17T10:00:00+08:00",
                    "post_id": "222",
                    "metrics": {"impressions": 75},
                },
            ]
        )
        by_window = review["metrics"]["by_window"]
        self.assertEqual(
            sorted(by_window),
            [
                "custom:2026-09-15T10:00:00+08:00..2026-09-16T10:00:00+08:00",
                "custom:2026-09-16T10:00:00+08:00..2026-09-17T10:00:00+08:00",
            ],
        )
        self.assertEqual(
            by_window["custom:2026-09-15T10:00:00+08:00..2026-09-16T10:00:00+08:00"]["totals"],
            {"impressions": 120},
        )
        self.assertEqual(
            by_window["custom:2026-09-16T10:00:00+08:00..2026-09-17T10:00:00+08:00"]["totals"],
            {"impressions": 75},
        )

    def test_repeat_snapshot_inside_one_custom_window_keeps_latest(self) -> None:
        window = {
            "metric_window": "custom",
            "window_start": "2026-09-15T10:00:00+08:00",
            "window_end": "2026-09-16T10:00:00+08:00",
            "post_id": "111",
        }
        review = build_review(
            metric_records=[
                dict(window, recorded_at="2026-09-16T11:00:00+08:00",
                     metrics={"impressions": 120}),
                dict(window, recorded_at="2026-09-16T12:00:00+08:00",
                     metrics={"impressions": 140}),
            ]
        )
        self.assertEqual(
            review["metrics"]["by_window"][
                "custom:2026-09-15T10:00:00+08:00..2026-09-16T10:00:00+08:00"
            ],
            {
                "record_count": 1,
                "post_ids": ["111"],
                "totals": {"impressions": 140},
            },
        )


class FeedbackEvidenceTests(unittest.TestCase):
    def test_user_reasons_and_constraints_reach_the_review(self) -> None:
        review = build_review(
            feedback_records=[
                {
                    "recorded_at": "2026-09-16T10:00:00+08:00",
                    "outcome": "edited",
                    "reason": "Too long, do not include code snippets in X posts",
                    "constraints": ["Keep it short", "Attach only a single URL"],
                },
                {
                    "recorded_at": "2026-09-17T10:00:00+08:00",
                    "outcome": "edited",
                    "reason": "开头缺少钩子不容易吸引人",
                    "constraints": ["开头必须有抓人注意力的钩子"],
                },
            ]
        )
        evidence = review["feedback"]["user_stated_evidence"]
        self.assertEqual(evidence["source"], "user-stated")
        edited = evidence["by_outcome"]["edited"]
        self.assertEqual(
            edited["reasons"],
            ["开头缺少钩子不容易吸引人", "Too long, do not include code snippets in X posts"],
        )
        self.assertEqual(
            edited["constraints"],
            ["开头必须有抓人注意力的钩子", "Keep it short", "Attach only a single URL"],
        )

    def test_reasons_are_deduplicated_and_limited(self) -> None:
        records = [
            {
                "recorded_at": f"2026-09-17T10:{index:02d}:00+08:00",
                "outcome": "rejected",
                "reason": f"reason {index}",
                "constraints": [],
            }
            for index in range(12)
        ]
        records.append(
            {
                "recorded_at": "2026-09-17T11:00:00+08:00",
                "outcome": "rejected",
                "reason": "reason 11",
                "constraints": [],
            }
        )
        review = build_review(feedback_records=records)
        reasons = review["feedback"]["user_stated_evidence"]["by_outcome"]["rejected"]["reasons"]
        self.assertEqual(len(reasons), 10)
        self.assertEqual(len(set(reasons)), 10)
        self.assertEqual(reasons[0], "reason 11")


class PostFormatTests(unittest.TestCase):
    def test_missing_structure_does_not_fabricate_a_thread_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts_dir = Path(tmp) / "posts"
            posts_dir.mkdir()
            (posts_dir / "post-20260915-001.md").write_text(
                "---\n"
                "id: post-20260915-001\n"
                "kind: published\n"
                "post_url: https://x.com/realchendahuang/status/2099671384922419433\n"
                "posted_at: '2026-09-15T01:27:22Z'\n"
                "---\n\n正文\n",
                encoding="utf-8",
            )
            records = WEEKLY_REVIEW.load_published_from_posts(posts_dir)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["thread_size"])
        review = build_review(published_records=records)
        self.assertEqual(review["published"]["formats"], {"unknown": 1})

    def test_explicit_structure_still_yields_a_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts_dir = Path(tmp) / "posts"
            posts_dir.mkdir()
            (posts_dir / "post-20260915-002.md").write_text(
                "---\n"
                "id: post-20260915-002\n"
                "kind: published\n"
                "post_url: https://x.com/realchendahuang/status/2099671384922419434\n"
                "posted_at: '2026-09-15T02:00:00Z'\n"
                "structure: thread\n"
                "---\n\n正文\n",
                encoding="utf-8",
            )
            records = WEEKLY_REVIEW.load_published_from_posts(posts_dir)
        self.assertEqual(records[0]["thread_size"], 2)
        review = build_review(published_records=records)
        self.assertEqual(review["published"]["formats"], {"thread": 1})


class StaleArchiveTests(unittest.TestCase):
    def test_stale_archive_produces_an_evidence_gap(self) -> None:
        review = build_review(
            published_records=[
                {
                    "published_at": "2026-09-09T10:00:00+08:00",
                    "post_id": "100",
                    "thread_size": 1,
                    "pillar": "AI实战",
                }
            ]
        )
        gaps = " | ".join(review["evidence_gaps"])
        self.assertIn("no posts after 2026-09-09", gaps)
        self.assertIn("9 days missing", gaps)
        self.assertEqual(review["status"], "needs-more-data")

    def test_fresh_archive_produces_no_staleness_gap(self) -> None:
        review = build_review(
            published_records=[
                {
                    "published_at": "2026-09-18T09:00:00+08:00",
                    "post_id": "100",
                    "thread_size": 1,
                    "pillar": "AI实战",
                }
            ]
        )
        self.assertFalse(
            any("no posts after" in gap for gap in review["evidence_gaps"])
        )


class ArchiveMetricSnapshotTests(unittest.TestCase):
    """The review must read metrics the archive already holds.

    Before this, `build_weekly_review` read only workspace/metrics/ledger.jsonl, so a
    fully populated archive still produced "No metric snapshots exist in this period".
    """

    ARCHIVE = (
        "---\n"
        "id: post-20260918-001\n"
        "kind: published\n"
        "post_url: https://x.com/realchendahuang/status/123456789\n"
        "collected_at: '2026-09-18T10:00:00+08:00'\n"
        "posted_at: '2026-09-18T09:00:00+08:00'\n"
        "metrics:\n"
        "  views: 1200\n"
        "  likes: 34\n"
        "  reposts: 5\n"
        "  replies: 2\n"
        "  bookmarks: 9\n"
        "---\n\n"
        "正文\n"
    )

    def test_archive_metrics_become_their_own_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp) / "posts"
            posts.mkdir(parents=True)
            (posts / "post-20260918-001.md").write_text(self.ARCHIVE, encoding="utf-8")
            snapshots = WEEKLY_REVIEW.load_archive_metric_snapshots(posts)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["metric_window"], WEEKLY_REVIEW.ARCHIVE_METRIC_WINDOW)
        self.assertEqual(snapshots[0]["post_id"], "123456789")
        self.assertEqual(snapshots[0]["metrics"]["views"], 1200)

    def test_archive_snapshots_never_merge_into_a_stated_window(self) -> None:
        review = build_review(
            published_records=[
                {"published_at": "2026-09-18T09:00:00+08:00", "post_id": "123", "pillar": "insight-income"}
            ],
            metric_records=[
                {
                    "recorded_at": "2026-09-18T12:00:00+08:00",
                    "post_id": "123",
                    "metric_window": WEEKLY_REVIEW.ARCHIVE_METRIC_WINDOW,
                    "metrics": {"views": 100},
                },
                {
                    "recorded_at": "2026-09-18T12:30:00+08:00",
                    "post_id": "123",
                    "metric_window": "24h",
                    "metrics": {"views": 500},
                },
            ],
        )
        by_window = review["metrics"]["by_window"]
        self.assertEqual(by_window[WEEKLY_REVIEW.ARCHIVE_METRIC_WINDOW]["totals"]["views"], 100)
        self.assertEqual(by_window["24h"]["totals"]["views"], 500)
        self.assertEqual(review["metrics"]["record_count"], 2)

    def test_archive_metrics_remove_the_no_metric_gap(self) -> None:
        review = build_review(
            published_records=[
                {"published_at": "2026-09-18T09:00:00+08:00", "post_id": "123", "pillar": "insight-income"}
            ],
            metric_records=[
                {
                    "recorded_at": "2026-09-18T12:00:00+08:00",
                    "post_id": "123",
                    "metric_window": WEEKLY_REVIEW.ARCHIVE_METRIC_WINDOW,
                    "metrics": {"views": 100},
                }
            ],
        )
        self.assertFalse(
            any("No metric snapshots" in gap for gap in review["evidence_gaps"]),
            review["evidence_gaps"],
        )

    def test_entries_without_metrics_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp) / "posts"
            posts.mkdir(parents=True)
            (posts / "post-20260918-002.md").write_text(
                self.ARCHIVE.replace(
                    "metrics:\n  views: 1200\n  likes: 34\n  reposts: 5\n  replies: 2\n  bookmarks: 9\n",
                    "",
                ).replace("post-20260918-001", "post-20260918-002"),
                encoding="utf-8",
            )
            self.assertEqual(WEEKLY_REVIEW.load_archive_metric_snapshots(posts), [])


class RecordFeedbackTests(unittest.TestCase):
    def test_unresolvable_draft_id_records_as_unresolved(self) -> None:
        """Draft-file workflow retired 2026-09-24: every draft_id records as unresolved.

        The ledger no longer joins draft ids to files — drafts are conversation
        outputs now. The row still records, with draft_resolved: false.
        """
        argv = [
            "python3",
            str(ROOT / ".agents/skills/post-drafter/scripts/record_feedback.py"),
            "--draft-id",
            "draft-20260903-code-mode",
            "--outcome",
            "rejected",
            "--reason",
            "测试未解析草稿",
            "--dry-run",
        ]
        allowed = subprocess.run(argv, cwd=ROOT, check=False, capture_output=True, text=True)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        payload = json.loads(allowed.stdout)
        self.assertIs(False, payload["feedback"]["draft_resolved"])

    def test_resolvable_draft_id_is_recorded_as_resolved(self) -> None:
        self.skipTest("draft-file workflow retired 2026-09-24; all ids record unresolved")


class ExistingSingleRecordBehaviorTests(unittest.TestCase):
    """Re-implements the old single-record assertion; the old test file is owned elsewhere."""

    def test_single_record_review_is_unchanged(self) -> None:
        review = build_review(
            start=date(2026, 8, 27),
            end=date(2026, 9, 2),
            now=datetime(2026, 9, 2, 9, 0, tzinfo=SHANGHAI),
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
            {
                "24h": {
                    "record_count": 1,
                    "post_ids": ["123"],
                    "totals": {"impressions": 100, "likes": 4},
                }
            },
        )
        self.assertEqual(review["status"], "needs-more-data")
        self.assertTrue(any("pillar" in gap for gap in review["evidence_gaps"]))


if __name__ == "__main__":
    unittest.main()
