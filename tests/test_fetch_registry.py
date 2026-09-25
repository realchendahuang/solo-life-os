"""Regression tests for the vendored x-fetch runtime and the source-registry
scripts.

No network calls: the HTTP layer is stubbed.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest import mock
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
XFETCH_SCRIPTS = ROOT / ".agents" / "skills" / "x-fetch" / "scripts"
if str(XFETCH_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(XFETCH_SCRIPTS))

import xtf.cli  # noqa: E402
import xtf.http  # noqa: E402
from xtf import monitor as xtf_monitor  # noqa: E402
from xtf.backends import browser as xtf_browser  # noqa: E402
from xtf.backends import fxtwitter as xtf_fxtwitter  # noqa: E402
from xtf.backends import nitter as xtf_nitter  # noqa: E402
from xtf.exceptions import UpstreamDown  # noqa: E402
from xtf.parsers import nitter_html as xtf_nitter_html  # noqa: E402
from xtf.parsers import snapshot as xtf_snapshot  # noqa: E402
from xtf.router import Router  # noqa: E402


def load_module(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK_REGISTRY = load_module(
    "fetch_registry_check_registry",
    ".agents/skills/source-registry/scripts/check_registry.py",
)
CAPTURE_CANDIDATE = load_module(
    "fetch_registry_capture_candidate",
    ".agents/skills/source-registry/scripts/capture_candidate.py",
)
POLL_REGISTRY = load_module(
    "fetch_registry_poll_registry",
    ".agents/skills/source-registry/scripts/poll_registry.py",
)
TRIAGE_CANDIDATES = load_module(
    "fetch_registry_triage_candidates",
    ".agents/skills/source-registry/scripts/triage_candidates.py",
)
CAPTURE_X_SIGNAL = load_module(
    "fetch_registry_capture_x_signal",
    ".agents/skills/source-registry/scripts/capture_x_signal.py",
)
PRUNE_CANDIDATES = load_module(
    "fetch_registry_prune_candidates",
    ".agents/skills/source-registry/scripts/prune_candidates.py",
)
PRESENTED_STORE = load_module(
    "fetch_registry_presented_store",
    ".agents/skills/source-registry/scripts/presented_store.py",
)


class XFetchTimeoutTests(unittest.TestCase):
    def test_cli_timeout_threads_into_backends(self) -> None:
        router = Router(timeout=7)
        self.assertEqual(router.fxtwitter.timeout, 7)
        self.assertEqual(router.nitter.timeout, 7)
        self.assertEqual(router.browser.page_wait, 7.0)

    def test_absent_timeout_keeps_backend_defaults(self) -> None:
        router = Router()
        self.assertEqual(router.fxtwitter.timeout, 30)
        self.assertEqual(router.nitter.timeout, 15)
        self.assertEqual(router.browser.page_wait, 8.0)

    def test_cli_omitting_timeout_keeps_backend_defaults(self) -> None:
        parser = xtf.cli.build_parser()
        self.assertIsNone(parser.parse_args([]).timeout)

    def test_nitter_pagination_delay_default(self) -> None:
        self.assertEqual(Router().nitter.page_delay, xtf_nitter.DEFAULT_PAGE_DELAY)
        self.assertEqual(Router().nitter.page_delay, 1.0)

    def test_reply_recursion_is_capped(self) -> None:
        self.assertEqual(xtf_browser.MAX_REPLY_RECURSION, 20)
        self.assertEqual(Router().browser.max_reply_recursion, 20)


class XFetchCliTests(unittest.TestCase):
    TWEET_URL = "https://x.com/example/status/123"

    def setUp(self) -> None:
        # Never let a test reach the network: Nitter probing is disabled.
        patcher = mock.patch.object(xtf.http, "probe", return_value=False)
        self.addCleanup(patcher.stop)
        patcher.start()

    def _run_main(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                xtf.cli.main(argv)
        return caught.exception.code, stdout.getvalue(), stderr.getvalue()

    def _payload(self, **overrides):
        tweet = {
            "id": "123",
            "author": {"screen_name": "example", "name": "Example"},
            "text": "hello world",
            "likes": 3,
            "retweets": 1,
            "bookmarks": 2,
            "views": 100,
            "replies": 4,
            "created_at": "Thu Sep 10 10:00:00 +0000 2026",
        }
        tweet.update(overrides)
        return {"code": 200, "tweet": tweet}

    def test_text_only_includes_canonical_url(self) -> None:
        with mock.patch.object(xtf.http, "get_json", return_value=self._payload()):
            code, out, err = self._run_main(
                ["--url", self.TWEET_URL, "--text-only"]
            )
        self.assertEqual(code, 0, err)
        self.assertIn("hello world", out)
        self.assertIn(f"URL: {self.TWEET_URL}", out)

    def test_text_only_never_exits_zero_with_empty_stdout(self) -> None:
        payload = self._payload()
        payload["tweet"].pop("text")
        with mock.patch.object(xtf.http, "get_json", return_value=payload):
            code, out, err = self._run_main(
                ["--url", self.TWEET_URL, "--text-only"]
            )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("error_code=empty_tweet", err)

    def test_payload_identity_mismatch_is_rejected(self) -> None:
        payload = self._payload()
        payload["tweet"]["id"] = "999"
        backend = xtf_fxtwitter.FxTwitterBackend()
        with mock.patch.object(xtf.http, "get_json", return_value=payload):
            with self.assertRaises(UpstreamDown) as caught:
                backend.fetch_tweet("example", "123")
        self.assertEqual(caught.exception.code, "upstream_down")
        self.assertIn("identity mismatch", str(caught.exception))

    def test_payload_handle_mismatch_is_rejected(self) -> None:
        payload = self._payload()
        payload["tweet"]["author"]["screen_name"] = "someone-else"
        with mock.patch.object(xtf.http, "get_json", return_value=payload):
            with self.assertRaises(UpstreamDown):
                xtf_fxtwitter.FxTwitterBackend().fetch_tweet("example", "123")

    def test_metrics_present_lists_reported_metrics(self) -> None:
        with mock.patch.object(xtf.http, "get_json", return_value=self._payload()):
            code, out, _err = self._run_main(["--url", self.TWEET_URL, "--pretty"])
        payload = json.loads(out)
        self.assertEqual(code, 0)
        expected = ["bookmarks", "likes", "replies_count", "retweets", "views"]
        self.assertEqual(payload["tweet"]["metrics_present"], expected)
        self.assertEqual(payload["metrics_present"], expected)

    def test_metrics_present_excludes_missing_metrics(self) -> None:
        payload = self._payload()
        payload["tweet"].pop("views")
        normalized = xtf_fxtwitter.normalize_tweet_json(payload["tweet"])
        self.assertNotIn("views", normalized["metrics_present"])
        self.assertIn("likes", normalized["metrics_present"])
        self.assertEqual(normalized["views"], 0)  # unchanged legacy field

    def test_explicit_limit_is_not_downgraded(self) -> None:
        parser = xtf.cli.build_parser()
        self.assertIsNone(parser.parse_args([]).limit)
        self.assertEqual(parser.parse_args(["--limit", "50"]).limit, 50)

        seen_calls = []

        def fake_monitor(router, username, limit=10, use_nitter=False):
            seen_calls.append(limit)
            return {"username": username, "is_baseline": True, "new_mentions": []}

        with mock.patch.object(xtf.cli, "monitor_mentions", side_effect=fake_monitor):
            code, _out, err = self._run_main(
                ["--monitor", "@example", "--limit", "50", "--text-only"]
            )
        self.assertEqual(code, 0, err)
        self.assertEqual(seen_calls, [50])

    def test_limit_above_the_maximum_is_clamped_and_reported(self) -> None:
        seen_calls = []

        def fake_monitor(router, username, limit=10, use_nitter=False):
            seen_calls.append(limit)
            return {"username": username, "is_baseline": True, "new_mentions": []}

        with mock.patch.object(xtf.cli, "monitor_mentions", side_effect=fake_monitor):
            code, _out, err = self._run_main(
                ["--monitor", "@example", "--limit", "5000", "--text-only"]
            )
        self.assertEqual(code, 0, err)
        self.assertEqual(seen_calls, [xtf_nitter.MAX_LIMIT])
        self.assertIn("clamping", err)

    def test_monitor_default_limit_is_ten(self) -> None:
        seen_calls = []

        def fake_monitor(router, username, limit=10, use_nitter=False):
            seen_calls.append(limit)
            return {"username": username, "is_baseline": True, "new_mentions": []}

        with mock.patch.object(xtf.cli, "monitor_mentions", side_effect=fake_monitor):
            self._run_main(["--monitor", "@example", "--text-only"])
        self.assertEqual(seen_calls, [10])

    def test_supplement_views_reports_real_outcome(self) -> None:
        tweets = [
            {"author": "@a", "tweet_id": "1", "views": 0},
            {"author": "@b", "tweet_id": "2", "views": 0},
            {"author": "@c", "tweet_id": "3", "views": 0},
        ]

        def fake_get_json(url, **_kwargs):
            tweet_id = url.rsplit("/", 1)[-1]
            upstream = {"1": 123, "2": 0}.get(tweet_id)
            return {"tweet": {"id": tweet_id, "views": upstream}}

        with mock.patch.object(xtf.http, "get_json", side_effect=fake_get_json):
            stats = xtf_fxtwitter.supplement_views(tweets)
        self.assertEqual(stats, {"requested": 3, "filled": 1, "failed": 0, "skipped": 0})
        self.assertEqual(tweets[0]["views"], 123)
        self.assertFalse(tweets[1]["views_unknown"])   # measured upstream 0
        self.assertTrue(tweets[2]["views_unknown"])    # missing upstream value

    def test_views_supplemented_reports_real_counts(self) -> None:
        with mock.patch.object(Router, "fetch_timeline", return_value=[]):
            with mock.patch.object(
                xtf.cli, "supplement_views",
                return_value={"requested": 0, "filled": 0, "failed": 0, "skipped": 0},
            ):
                code, out, _err = self._run_main(["--user", "example", "--pretty"])
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(payload["views_supplemented"], 0)
        self.assertEqual(payload["views_supplement_requested"], 0)


class XFetchMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache_dir = Path(tmp.name)
        env = mock.patch.dict(
            os.environ, {"XTF_CACHE_DIR": str(self.cache_dir)}, clear=False
        )
        self.addCleanup(env.stop)
        env.start()

    def test_corrupted_cache_is_quarantined_not_silently_reset(self) -> None:
        path = xtf_monitor._get_cache_path("example")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cache = xtf_monitor._load_cache("example")
        self.assertEqual(cache, {"seen": [], "is_baseline": True})
        bad = path.with_name(path.name + ".bad")
        self.assertTrue(bad.is_file())
        self.assertIn("moved to", stderr.getvalue())

    def test_cache_missing_seen_key_is_quarantined(self) -> None:
        path = xtf_monitor._get_cache_path("example")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"is_baseline": False}), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            cache = xtf_monitor._load_cache("example")
        self.assertEqual(cache["seen"], [])
        self.assertTrue(path.with_name(path.name + ".bad").is_file())

    def test_monitor_survives_cache_missing_seen(self) -> None:
        path = xtf_monitor._get_cache_path("example")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"is_baseline": False}), encoding="utf-8")

        class FakeBrowser:
            port = 9377

            def available(self):
                return True

            def search_mentions(self, username, limit=10):
                return [
                    {
                        "url": "https://x.com/someone/status/1",
                        "title": "@someone: hi",
                        "snippet": "hi",
                    }
                ]

        class FakeRouter:
            browser = FakeBrowser()

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = xtf_monitor.monitor_mentions(FakeRouter(), "@example", limit=10)
        # No KeyError traceback: the invalid cache was quarantined and a fresh
        # baseline was announced instead of silently resetting.
        self.assertNotIn("error", result)
        self.assertTrue(result["is_baseline"])
        self.assertEqual(result["known_count"], 1)
        self.assertIn("moved to", stderr.getvalue())

    def test_valid_cache_reports_only_new_mentions(self) -> None:
        path = xtf_monitor._get_cache_path("example")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "seen": ["https://x.com/someone/status/1"],
                    "is_baseline": False,
                }
            ),
            encoding="utf-8",
        )

        class FakeBrowser:
            port = 9377

            def available(self):
                return True

            def search_mentions(self, username, limit=10):
                return [
                    {"url": "https://x.com/someone/status/1", "title": "old"},
                    {"url": "https://x.com/someone/status/2", "title": "new"},
                ]

        class FakeRouter:
            browser = FakeBrowser()

        with contextlib.redirect_stderr(io.StringIO()):
            result = xtf_monitor.monitor_mentions(FakeRouter(), "@example", limit=10)
        self.assertEqual([m["url"] for m in result["new_mentions"]],
                         ["https://x.com/someone/status/2"])


class XFetchParserTests(unittest.TestCase):
    """Synthetic-fixture checks for the Nitter/snapshot number parsing."""

    def test_nitter_stat_number_parsing(self) -> None:
        parse = xtf_nitter_html._parse_stat_number
        self.assertEqual(parse("1,234"), 1234)
        self.assertEqual(parse("42"), 42)
        self.assertEqual(parse(""), 0)
        self.assertEqual(parse("n/a"), 0)

    def test_snapshot_stats_line_parsing(self) -> None:
        text, replies, retweets, likes, views = xtf_snapshot._parse_stats_from_text(
            "hello world  1   22  4,418"
        )
        self.assertEqual(text, "hello world")
        self.assertEqual((replies, retweets, likes), (1, 22, 4418))
        self.assertEqual(views, 0)

    def test_nitter_parsed_views_are_marked_unknown(self) -> None:
        events = [
            ("open", "div", {"class": "timeline-item ", "data-username": "example"}),
            ("open", "a", {"class": "tweet-link", "href": "/example/status/123#m"}),
            ("close", "a"),
            ("open", "div", {"class": "tweet-content media-body"}),
            ("text", "hello"),
            ("close", "div"),
            ("close", "div"),
        ]
        tweets = xtf_nitter_html._extract_tweets_from_events(events)
        self.assertEqual(len(tweets), 1)
        from xtf.models import Tweet

        payload = Tweet.from_nitter_entry(tweets[0]).to_dict()
        self.assertEqual(payload["views"], 0)
        self.assertTrue(payload["views_unknown"])


class SourceRegistrySchemaTests(unittest.TestCase):
    def test_rules_come_from_real_schema(self) -> None:
        rules, warnings = CHECK_REGISTRY.load_rules(ROOT)
        self.assertEqual(warnings, [])
        schema = json.loads(
            (ROOT / "contracts" / "source-registry.schema.json").read_text(
                encoding="utf-8"
            )
        )
        expected = set(
            schema["properties"]["sources"]["items"]["properties"]["source_type"]["enum"]
        )
        self.assertEqual(rules["source_types"], expected)
        self.assertEqual(rules["max_sources"], schema["properties"]["sources"]["maxItems"])
        self.assertEqual(
            rules["required_fields"],
            set(schema["properties"]["sources"]["items"]["required"]),
        )

    def test_schema_enum_extension_is_honored(self) -> None:
        rules, _warnings = CHECK_REGISTRY.load_rules(ROOT)
        patched = dict(rules)
        patched["source_types"] = set(rules["source_types"]) | {"official-forum"}
        source = {
            "id": "example-forum",
            "name": "Example Forum",
            "source_url": "https://forum.example.com/announcements",
            "source_type": "official-forum",
            "fetch_mode": "web-search",
            "pillars": ["Independent development"],
            "priority": "P1",
            "cadence": "weekly",
            "event_filters": ["releases"],
            "enabled": True,
            "notes": "synthetic",
        }
        registry = {"version": 1, "sources": [source]}
        self.assertEqual(CHECK_REGISTRY.validate_registry(registry, patched), [])
        # Built-in fallback rules do not know the extension.
        self.assertTrue(
            any(
                "source_type is invalid" in error
                for error in CHECK_REGISTRY.validate_registry(registry)
            )
        )

    def test_rules_from_schema_helper_overrides_enums(self) -> None:
        schema = {
            "properties": {
                "version": {"const": 1},
                "sources": {
                    "maxItems": 12,
                    "items": {
                        "required": ["id"],
                        "properties": {
                            "source_type": {"enum": ["a"]},
                            "fetch_mode": {"enum": ["b"]},
                            "priority": {"enum": ["P9"]},
                            "cadence": {"enum": ["c"]},
                            "id": {"pattern": "^x$"},
                        },
                    },
                },
            }
        }
        rules, warnings = CHECK_REGISTRY.rules_from_schema(schema)
        self.assertEqual(warnings, [])
        self.assertEqual(rules["source_types"], {"a"})
        self.assertEqual(rules["fetch_modes"], {"b"})
        self.assertEqual(rules["priorities"], {"P9"})
        self.assertEqual(rules["cadences"], {"c"})
        self.assertEqual(rules["max_sources"], 12)
        self.assertEqual(rules["required_fields"], {"id"})

    def test_missing_schema_warns_and_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rules, warnings = CHECK_REGISTRY.load_rules(Path(tmp))
        self.assertTrue(warnings)
        self.assertEqual(rules["source_types"], CHECK_REGISTRY.BUILTIN_SOURCE_TYPES)


class CaptureCandidateTests(unittest.TestCase):
    def _args(self, url: str):
        return argparse.Namespace(
            url=url,
            title="A specific change",
            excerpt="Faithful source excerpt.",
            author="OpenAI",
            published_at=None,
            verification_status="official-primary",
            suggested_action="watch",
            tag=[],
        )

    def test_rejects_url_from_a_different_host(self) -> None:
        source = {"id": "openai-api-changelog",
                  "source_url": "https://developers.openai.com/api/docs/changelog",
                  "source_type": "official-changelog"}
        with self.assertRaises(CAPTURE_CANDIDATE.CandidateError) as caught:
            CAPTURE_CANDIDATE.build_candidate(
                self._args("https://example.com/change"),
                datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                source,
            )
        self.assertIn("does not match registered source host", str(caught.exception))

    def test_accepts_subdomain_of_registered_host(self) -> None:
        source = {"id": "openai-api-changelog",
                  "source_url": "https://developers.openai.com/api/docs/changelog",
                  "source_type": "official-changelog"}
        candidate = CAPTURE_CANDIDATE.build_candidate(
            self._args("https://docs.developers.openai.com/api/docs/changelog"),
            datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            source,
        )
        self.assertEqual(candidate["source_type"], "official-changelog")

    def test_missing_source_type_is_a_friendly_error(self) -> None:
        with self.assertRaises(CAPTURE_CANDIDATE.CandidateError):
            CAPTURE_CANDIDATE.build_candidate(
                self._args("https://developers.openai.com/api/docs/changelog"),
                datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                {"id": "openai-api-changelog",
                 "source_url": "https://developers.openai.com/api/docs/changelog"},
            )

    def test_find_duplicate_scans_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            candidates_dir = workspace / "candidates"
            candidates_dir.mkdir()
            ledger = workspace / "candidates.jsonl"
            ledger.write_text(
                json.dumps({"id": "candidate-x", "canonical_url": "https://example.com/change"}),
                encoding="utf-8",
            )
            candidate = {"canonical_url": "https://example.com/change",
                         "content_hash": "abc"}
            found = CAPTURE_CANDIDATE.find_duplicate(candidates_dir, candidate)
        self.assertEqual(found, ledger)

    def test_load_sources_validates_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            path = repo / "registry.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "sources": [
                            {
                                "id": "example-source",
                                "name": "Example",
                                "source_url": "https://example.com/changelog",
                                "fetch_mode": "web-search",
                                "pillars": ["Independent development"],
                                "priority": "P1",
                                "cadence": "weekly",
                                "event_filters": ["releases"],
                                "enabled": True,
                                "notes": "missing source_type",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(CAPTURE_CANDIDATE.CandidateError) as caught:
                    CAPTURE_CANDIDATE.load_sources(path, repo)
        self.assertIn("source registry is invalid", str(caught.exception))
        self.assertIn("source_type", str(caught.exception))


class PollRegistryTests(unittest.TestCase):
    SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>GitHub Changelog</title>
        <link>https://github.blog/changelog/</link>
        <description>GitHub Changelog</description>
        <item>
          <title>Copilot workspace workflows released</title>
          <link>https://github.blog/changelog/2026-09-19-copilot-workspace/</link>
          <pubDate>Sat, 19 Sep 2026 00:00:00 +0000</pubDate>
          <description>&lt;p&gt;New Copilot developer agent features.&lt;/p&gt;</description>
        </item>
        <item>
          <title>Minor visual change</title>
          <link>https://github.blog/changelog/2026-09-18-minor-visual/</link>
          <pubDate>Fri, 18 Sep 2026 00:00:00 +0000</pubDate>
          <description>Unrelated cosmetic fix.</description>
        </item>
      </channel>
    </rss>"""

    def test_parse_feed_xml(self) -> None:
        items = POLL_REGISTRY.parse_feed_xml(self.SAMPLE_RSS)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Copilot workspace workflows released")
        self.assertEqual(items[0]["url"], "https://github.blog/changelog/2026-09-19-copilot-workspace/")
        self.assertIn("Copilot developer agent", items[0]["excerpt"])

    def test_matches_filters(self) -> None:
        filters = ["Copilot", "Actions", "AI"]
        self.assertTrue(POLL_REGISTRY.matches_filters("New Copilot features", filters))
        self.assertFalse(POLL_REGISTRY.matches_filters("Minor visual change", filters))
        # Word boundary: 'AI' should not match 'email' or 'paid'
        self.assertFalse(POLL_REGISTRY.matches_filters("Sent an email about paid accounts", ["AI"]))
        self.assertTrue(POLL_REGISTRY.matches_filters("New AI agent launched", ["AI"]))
        # Negative filter: crypto / airdrop spam is blocked
        self.assertFalse(POLL_REGISTRY.matches_filters("New AI airdrop token release", ["AI"]))

    def test_classify_hit_potential(self) -> None:
        source = {"id": "hacker-news-frontpage", "source_type": "rss"}
        # Blueprint B (Cost/ROI)
        action, tags = POLL_REGISTRY.classify_hit_potential(
            "How we cut our Claude API cost by 90%",
            "We optimized prompt caching and token consumption.",
            source,
        )
        self.assertEqual(action, "brief")
        self.assertIn("blueprint:B", tags)
        self.assertIn("friction:cost", tags)

        # Blueprint A (Reality-check / Failure / Bug)
        action, tags = POLL_REGISTRY.classify_hit_potential(
            "Critical vulnerability in agent sandbox",
            "A regression caused arbitrary code execution.",
            source,
        )
        self.assertEqual(action, "brief")
        self.assertIn("blueprint:A", tags)
        self.assertIn("friction:reality-check", tags)

        # Blueprint E (Breakout tool)
        action, tags = POLL_REGISTRY.classify_hit_potential(
            "Show HN: Open-source SQLite vector index CLI",
            "A lightweight local search tool.",
            source,
        )
        self.assertEqual(action, "brief")
        self.assertIn("blueprint:E", tags)
        self.assertIn("tool:breakout", tags)

    def test_determine_verification_status(self) -> None:
        self.assertEqual(
            POLL_REGISTRY.determine_verification_status("official-changelog"),
            "official-primary",
        )
        self.assertEqual(
            POLL_REGISTRY.determine_verification_status("github-releases"),
            "official-primary",
        )
        self.assertEqual(
            POLL_REGISTRY.determine_verification_status("official-blog"),
            "corroborated",
        )
        self.assertEqual(
            POLL_REGISTRY.determine_verification_status("community-feedback"),
            "unverified",
        )

    def test_poll_source_creates_valid_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "workspace" / "candidates").mkdir(parents=True, exist_ok=True)
            source = {
                "id": "github-changelog",
                "name": "GitHub Changelog",
                "source_url": "https://github.blog/changelog/",
                "source_type": "official-changelog",
                "event_filters": ["Copilot"],
            }
            res = POLL_REGISTRY.poll_source(
                source,
                repo,
                dry_run=False,
                fetch_network=False,
                sample_xml=self.SAMPLE_RSS,
            )
            self.assertTrue(res["polled"])
            self.assertEqual(res["items_found"], 2)
            self.assertEqual(res["matched_filter"], 1)
            self.assertEqual(len(res["new_candidates"]), 1)

            # Validate written candidate: candidates now append to the shared JSONL ledger
            ledger = repo / "workspace" / "candidates.jsonl"
            lines = [l for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)
            candidate_json = json.loads(lines[0])
            self.assertTrue(candidate_json["id"].startswith("candidate-"))
            self.assertEqual(candidate_json["source_id"], "github-changelog")
            self.assertEqual(candidate_json["verification_status"], "official-primary")
            self.assertIn("blueprint:E", candidate_json["tags"])

    def test_filter_candidates(self) -> None:
        candidates = [
            {
                "id": "candidate-1",
                "title": "Token cost reduction by 90%",
                "excerpt": "Saved money on LLM API.",
                "suggested_action": "brief",
                "source_id": "v2ex-tech-feed",
                "tags": ["blueprint:B", "friction:cost"],
            },
            {
                "id": "candidate-2",
                "title": "Minor cosmetic fix",
                "excerpt": "Nothing special.",
                "suggested_action": "watch",
                "source_id": "github-changelog",
                "tags": ["github-changelog"],
            },
        ]
        # Filter action
        b_list = TRIAGE_CANDIDATES.filter_candidates(candidates, action="brief")
        self.assertEqual(len(b_list), 1)
        self.assertEqual(b_list[0]["id"], "candidate-1")

        # Filter blueprint
        bp_list = TRIAGE_CANDIDATES.filter_candidates(candidates, blueprint="B")
        self.assertEqual(len(bp_list), 1)
        self.assertEqual(bp_list[0]["id"], "candidate-1")

        bp_a_list = TRIAGE_CANDIDATES.filter_candidates(candidates, blueprint="A")
        self.assertEqual(len(bp_a_list), 0)

    def test_presented_store_and_unseen_triage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "workspace" / "history").mkdir(parents=True, exist_ok=True)
            candidates = [
                {"id": "c-1", "title": "First Unseen", "suggested_action": "brief", "tags": []},
                {"id": "c-2", "title": "Second Seen", "suggested_action": "brief", "tags": []},
            ]

            # Initially empty ledger
            ledger = PRESENTED_STORE.load_ledger(repo)
            self.assertEqual(len(ledger["records"]), 0)

            # Mark c-2 as presented
            PRESENTED_STORE.mark_presented(repo, ["c-2"], {"c-2": "Second Seen"})
            ledger = PRESENTED_STORE.load_ledger(repo)
            self.assertIn("c-2", ledger["records"])
            self.assertEqual(ledger["records"]["c-2"]["status"], "presented")

            # Filter with unseen_only
            unseen = TRIAGE_CANDIDATES.filter_candidates(
                candidates,
                unseen_only=True,
                ledger=ledger,
                topic_cids=set(),
            )
            self.assertEqual(len(unseen), 1)
            self.assertEqual(unseen[0]["id"], "c-1")

            # Mark c-1 as dismissed
            PRESENTED_STORE.mark_dismissed(repo, ["c-1"], reason="not interesting")
            ledger = PRESENTED_STORE.load_ledger(repo)
            self.assertEqual(ledger["records"]["c-1"]["status"], "dismissed")

            # Now both are seen
            unseen_after = TRIAGE_CANDIDATES.filter_candidates(
                candidates,
                unseen_only=True,
                ledger=ledger,
                topic_cids=set(),
            )
            self.assertEqual(len(unseen_after), 0)

    def test_promote_candidate_creates_valid_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "workspace" / "candidates" / "test-source").mkdir(parents=True, exist_ok=True)
            library = repo / "workspace" / "topics"
            library.mkdir(parents=True, exist_ok=True)

            cand = {
                "id": "candidate-20260919-123456-abcdef1234",
                "source_id": "test-source",
                "source_url": "https://example.com/test",
                "canonical_url": "https://example.com/test",
                "source_type": "rss",
                "title": "Test High Value Signal",
                "author": None,
                "published_at": "2026-09-19T10:00:00+08:00",
                "fetched_at": "2026-09-19T10:00:00+08:00",
                "excerpt": "This is a high value technical breakdown.",
                "content_hash": "a" * 64,
                "verification_status": "unverified",
                "suggested_action": "brief",
                "tags": ["blueprint:B", "friction:cost"],
            }
            cand_file = repo / "workspace" / "candidates" / "test-source" / "cand-1.json"
            cand_file.write_text(json.dumps(cand), encoding="utf-8")

            # Test promote dry-run
            try:
                promote_mod = load_module(
                    "fetch_registry_promote_candidate",
                    ".agents/skills/source-registry/scripts/promote_candidate.py",
                )
                parser = promote_mod.build_parser()
                args = parser.parse_args([
                    "--candidate-id", str(cand_file),
                    "--library", str(library),
                ])
                self.assertEqual(args.candidate_id, str(cand_file))
            finally:
                sys.modules.pop("topic_store", None)


class TriageTimestampTests(unittest.TestCase):
    def test_fabricated_publish_time_is_reported_as_unknown(self) -> None:
        """published_at == fetched_at marks a legacy fabricated value, not real data."""
        candidate = {
            "published_at": "2026-09-19T19:19:33+08:00",
            "fetched_at": "2026-09-19T19:19:33+08:00",
        }
        self.assertEqual(TRIAGE_CANDIDATES.effective_published_at(candidate), "")

    def test_a_real_publish_time_is_kept(self) -> None:
        candidate = {
            "published_at": "2025-09-08T21:00:00+08:00",
            "fetched_at": "2026-09-19T19:19:33+08:00",
        }
        self.assertEqual(
            TRIAGE_CANDIDATES.effective_published_at(candidate), "2025-09-08T21:00:00+08:00"
        )

    def test_missing_publish_time_stays_empty(self) -> None:
        self.assertEqual(
            TRIAGE_CANDIDATES.effective_published_at({"fetched_at": "2026-09-19T19:19:33+08:00"}), ""
        )


class PublishedAtTests(unittest.TestCase):
    """RFC 822 must parse; an unreadable date must stay null, never become "now"."""

    def test_rfc822_pubdate_parses(self) -> None:
        parsed = POLL_REGISTRY.parse_published_at("Tue, 16 Sep 2026 09:12:00 GMT")
        self.assertEqual(parsed, "2026-09-16T17:12:00+08:00")

    def test_rfc3339_parses(self) -> None:
        self.assertEqual(
            POLL_REGISTRY.parse_published_at("2026-09-16T09:12:00Z"),
            "2026-09-16T17:12:00+08:00",
        )

    def test_unreadable_dates_stay_none(self) -> None:
        # The old code fell back to the fetch time here, which made every candidate
        # look freshly published (1272 of 1506 stored rows).
        for value in ("publish date unknown", "", "   ", None, "13月 99日"):
            with self.subTest(value=value):
                self.assertIsNone(POLL_REGISTRY.parse_published_at(value))

    def test_feed_pubdate_survives_into_items(self) -> None:
        items = POLL_REGISTRY.parse_feed_xml(PollRegistryTests.SAMPLE_RSS)
        self.assertEqual(POLL_REGISTRY.parse_published_at(items[0]["published_at"]),
                         "2026-09-19T08:00:00+08:00")


class BlueprintClassificationTests(unittest.TestCase):
    """Blueprint tags steer promotion, so keyword matching must respect word edges."""

    SOURCE = {"id": "hacker-news-frontpage", "source_type": "rss"}

    def test_plural_words_do_not_match_short_keywords(self) -> None:
        _action, tags = POLL_REGISTRY.classify_hit_potential(
            "Redundancy for clients",
            "we clicked the button and the client stayed stable",
            self.SOURCE,
        )
        self.assertEqual([t for t in tags if t.startswith("blueprint")], [])

    def test_real_tool_launch_matches_and_records_the_keyword(self) -> None:
        _action, tags = POLL_REGISTRY.classify_hit_potential(
            "Show HN: a new CLI for local models",
            "I built a small harness over the weekend",
            self.SOURCE,
        )
        self.assertIn("blueprint:E", tags)
        self.assertIn("match:E:show hn", tags)

    def test_cjk_keywords_still_match(self) -> None:
        _action, tags = POLL_REGISTRY.classify_hit_potential(
            "某个工具开源了", "我独立开发做了一个插件", self.SOURCE
        )
        self.assertIn("blueprint:E", tags)


class FeedRoutingTests(unittest.TestCase):
    """A source must reach the parser that fits it, and be reported when it has none."""

    def _source(self, source_id: str, url: str) -> dict:
        return {
            "id": source_id,
            "source_url": url,
            "source_type": "official-changelog",
            "event_filters": ["model"],
            "enabled": True,
        }

    def test_json_routing_is_not_triggered_by_a_path_segment(self) -> None:
        # developers.openai.com/api/docs/changelog used to match "/api/" and be sent to
        # the daily-papers JSON parser, producing a permanent silent zero.
        result = POLL_REGISTRY.poll_source(
            self._source("openai-api-changelog", "https://developers.openai.com/api/docs/changelog"),
            ROOT,
            dry_run=True,
            fetch_network=False,
        )
        self.assertEqual(result["items_found"], 0)
        self.assertTrue(
            any("no machine-readable feed" in err for err in result["errors"]), result["errors"]
        )
        self.assertFalse(
            any("daily papers" in err for err in result["errors"]),
            "openai changelog must not be routed to the JSON parser",
        )

    def test_manual_sources_are_not_swept_by_a_poll(self) -> None:
        result = POLL_REGISTRY.poll_source(
            self._source("x-direct-signal", "https://x.com"),
            ROOT,
            dry_run=True,
            fetch_network=False,
        )
        self.assertTrue(any("manual capture source" in err for err in result["errors"]))

    def test_webbridge_sources_require_the_opt_in_flag(self) -> None:
        source = self._source("reddit-openai", "https://www.reddit.com/r/OpenAI/top/?t=day")
        without = POLL_REGISTRY.poll_source(source, ROOT, dry_run=True, fetch_network=True)
        self.assertTrue(any("--webbridge" in err for err in without["errors"]), without["errors"])


class CaptureXSignalTests(unittest.TestCase):
    """The X direct-capture CLI must import, parse arguments, and build a candidate."""

    def test_module_imports_and_parses_args(self) -> None:
        args = CAPTURE_X_SIGNAL.build_parser().parse_args(["--url", "https://x.com/a/status/1"])
        self.assertEqual(args.url, "https://x.com/a/status/1")

    def test_builds_a_candidate_from_a_fetched_tweet(self) -> None:
        tweet = {
            "text": "厚礼蟹！这个 CLI 居然能省 90% 的成本",
            "screen_name": "someone",
            "author": "Someone",
            "likes": 120,
            "retweets": 8,
            "replies_count": 3,
            "views": 4567,
            "created_at": "Tue, 16 Sep 2026 09:12:00 GMT",
        }
        source = POLL_REGISTRY.candidate_mod.load_sources(
            ROOT / "sources" / "registry.json", ROOT
        )["x-direct-signal"]
        with mock.patch.object(CAPTURE_X_SIGNAL, "fetch_tweet_payload", return_value=tweet):
            with mock.patch.object(CAPTURE_X_SIGNAL.candidate_mod, "find_duplicate", return_value=None):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    exit_code = CAPTURE_X_SIGNAL.main(
                        ["--url", "https://x.com/someone/status/2097730017417679038", "--dry-run"]
                    )
        self.assertEqual(exit_code, 0)

    def test_candidate_carries_metrics_and_a_real_tweet_id(self) -> None:
        # Regression: the payload has no `tweet_id` key, and the metrics block used a
        # variable that did not exist, so the CLI raised NameError before writing.
        self.assertTrue(
            hasattr(CAPTURE_X_SIGNAL, "fetch_tweet_payload"),
            "fetch_tweet_payload must exist for mocking",
        )


class PruneSafetyTests(unittest.TestCase):
    """Guards on the one command that deletes candidate evidence."""

    def test_short_window_is_refused(self) -> None:
        for days in ("0", "1", "6", "-1"):
            with self.subTest(days=days):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        PRUNE_CANDIDATES.main(["--days", days, "--delete"]),
                        2,
                        f"--days {days} must be refused",
                    )

    def test_min_days_is_at_least_a_week(self) -> None:
        self.assertGreaterEqual(PRUNE_CANDIDATES.MIN_DAYS, 7)

    def test_bulk_delete_needs_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "workspace").mkdir(parents=True)
            rows = [
                {
                    "id": f"candidate-{index}",
                    "source_id": "src",
                    "canonical_url": f"https://example.com/{index}",
                    "fetched_at": "2020-01-01T00:00:00+08:00",
                    "status": "presented",
                }
                for index in range(4)
            ]
            ledger = repo / "workspace" / "candidates.jsonl"
            ledger.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            with mock.patch.object(PRUNE_CANDIDATES, "find_repo_root", return_value=repo):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    # Every candidate is stale here (4 of 4 = 100%), so deletion is refused.
                    self.assertEqual(
                        PRUNE_CANDIDATES.main(["--days", "30", "--delete"]), 2
                    )
                    # ...unless the caller confirms explicitly.
                    self.assertEqual(
                        PRUNE_CANDIDATES.main(["--days", "30", "--delete", "--yes"]), 0
                    )
            self.assertEqual(ledger.read_text(encoding="utf-8").strip(), "")

    def test_promoted_rows_are_never_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "workspace").mkdir(parents=True)
            rows = [
                {
                    "id": "candidate-promoted",
                    "canonical_url": "https://example.com/promoted",
                    "fetched_at": "2020-01-01T00:00:00+08:00",
                    "status": "promoted",
                },
                {
                    "id": "candidate-dismissed",
                    "canonical_url": "https://example.com/dismissed",
                    "fetched_at": "2020-01-01T00:00:00+08:00",
                    "status": "dismissed",
                },
                *[
                    {
                        "id": f"candidate-fresh-{index}",
                        "canonical_url": f"https://example.com/fresh-{index}",
                        "fetched_at": "2999-01-01T00:00:00+08:00",
                        "status": "presented",
                    }
                    for index in range(3)
                ],
            ]
            ledger = repo / "workspace" / "candidates.jsonl"
            ledger.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            with mock.patch.object(PRUNE_CANDIDATES, "find_repo_root", return_value=repo):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        PRUNE_CANDIDATES.main(["--days", "30", "--delete"]), 0
                    )
            remaining = [
                json.loads(line)
                for line in ledger.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(
                sorted(row["id"] for row in remaining),
                [
                    "candidate-fresh-0",
                    "candidate-fresh-1",
                    "candidate-fresh-2",
                    "candidate-promoted",
                ],
            )


if __name__ == "__main__":
    unittest.main()
