from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HIT_SCRIPTS = ROOT / ".agents/skills/hit-archive/scripts"
TOPIC_SCRIPTS = ROOT / ".agents/skills/topic-library/scripts"
for _scripts in (HIT_SCRIPTS, TOPIC_SCRIPTS):
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))

import topic_store as TOPIC_STORE  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")


def load_module(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FRONTMATTER = load_module(
    "archive_frontmatter",
    ".agents/skills/hit-archive/scripts/frontmatter.py",
)
STATS = load_module(
    "archive_stats",
    ".agents/skills/hit-archive/scripts/stats.py",
)
BACKFILL = load_module(
    "archive_backfill",
    ".agents/skills/hit-archive/scripts/backfill_metrics.py",
)
RECORD_POST = load_module(
    "archive_record_post",
    ".agents/skills/hit-archive/scripts/record_post.py",
)
ARCHIVE_HIT = load_module(
    "archive_hit",
    ".agents/skills/hit-archive/scripts/archive_hit.py",
)

PAST = datetime(2026, 9, 9, 20, 0, tzinfo=SHANGHAI)

ARCHIVE_FILE = (
    "---\n"
    "id: {id}\n"
    "kind: {kind}\n"
    "post_url: {post_url}\n"
    "posted_at: '{posted_at}'\n"
    "collected_at: '2026-09-09T09:00:00+08:00'\n"
    "{extra}"
    "---\n\n{body}"
)


def write_archive(root: Path, name: str, **fields) -> Path:
    fields.setdefault("kind", "published")
    fields.setdefault("post_url", f"https://x.com/realchendahuang/status/{abs(hash(name))}")
    fields.setdefault("posted_at", "2026-09-09T10:00:00+08:00")
    fields.setdefault("extra", "")
    fields.setdefault("body", f"{name} 正文\n\n## 我的批注\n\n（占位）\n")
    fields["id"] = fields.pop("id", name.removesuffix(".md"))
    path = root / "workspace" / "posts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ARCHIVE_FILE.format(**fields), encoding="utf-8")
    return path


def make_root(tmp: str) -> Path:
    root = Path(tmp)
    (root / "workspace" / "posts").mkdir(parents=True, exist_ok=True)
    (root / "workspace" / "drafts").mkdir(parents=True, exist_ok=True)
    (root / "profile").mkdir(parents=True, exist_ok=True)
    return root


def run_module_main(module: ModuleType, argv: list[str]) -> tuple[int, str, str]:
    """Call module.main() with argv, returning (returncode, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", argv):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main()
    return code, out.getvalue(), err.getvalue()


class FrontmatterTests(unittest.TestCase):
    def test_dump_round_trip_is_byte_stable(self) -> None:
        meta = {
            "id": "post-20260909-001",
            "kind": "published",
            "post_url": "https://x.com/realchendahuang/status/1234567890",
            "collected_at": "2026-09-09T10:00:00+08:00",
            "posted_at": "2026-09-09T09:00:00+08:00",
            "metrics": {"views": 100, "likes": 3},
        }
        body = "  缩进的首行\n正文第二行\n\n## 我的批注\n\n（占位）\n\n## 数据回采\n- 2026-09-09 20:00 snapshot: views=100\n"
        first = FRONTMATTER.dump(meta, body)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "post.md"
            path.write_text(first, encoding="utf-8")
            second = FRONTMATTER.dump(*FRONTMATTER.load(path))
            self.assertEqual(first, second)

            FRONTMATTER.write(path, meta, body)
            sizes = []
            for _ in range(4):
                loaded_meta, loaded_body = FRONTMATTER.load(path)
                FRONTMATTER.write(path, loaded_meta, loaded_body)
                sizes.append(path.stat().st_size)
            self.assertEqual(len(set(sizes)), 1, f"file grew across rewrites: {sizes}")

    def test_indented_first_line_is_preserved(self) -> None:
        meta = {"id": "post-20260909-001", "kind": "published"}
        body = "  缩进的首行\n正文\n"
        text = FRONTMATTER.dump(meta, body)
        self.assertIn("\n---\n\n  缩进的首行\n", text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "post.md"
            FRONTMATTER.write(path, meta, body)
            _meta, loaded = FRONTMATTER.load(path)
        self.assertEqual(loaded, body)

    def test_load_wraps_yaml_errors_with_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.md"
            path.write_text("---\nid: [unclosed\n---\n\n正文\n", encoding="utf-8")
            with self.assertRaises(FRONTMATTER.FrontmatterError) as ctx:
                FRONTMATTER.load(path)
        self.assertIn(str(path), str(ctx.exception))

    def test_load_all_skips_bad_files_and_reports_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            posts = root / "workspace" / "posts"
            write_archive(root, "post-20260909-001.md")
            (posts / "broken.md").write_text(
                "---\nid: [unclosed\n---\n\n正文\n", encoding="utf-8"
            )
            (posts / "plain.md").write_text("没有 frontmatter\n", encoding="utf-8")
            (posts / "README.md").write_text("index\n", encoding="utf-8")

            errors: list[str] = []
            records = FRONTMATTER.load_all(posts, errors=errors)
            self.assertEqual([p.name for p, _m, _b in records], ["post-20260909-001.md"])
            self.assertEqual(len(errors), 2)
            self.assertTrue(any("broken.md" in err for err in errors))
            self.assertTrue(any("no YAML frontmatter" in err and "plain.md" in err for err in errors))
            self.assertEqual(FRONTMATTER.load_all.errors, errors)

    def test_validate_post_accepts_real_shape(self) -> None:
        meta = {
            "id": "hit-site-20260906-001",
            "kind": "hit",
            "post_url": "https://x.com/realchendahuang/status/2066446337936110030",
            "collected_at": "2026-09-06T14:31:45+08:00",
            "source": "chendahuang.com/highlights",
            "site_title": "标题",
            "in_reply_to_status_id_str": "123",
            "metrics": {"views": 1, "bookmarks": 2},
        }
        FRONTMATTER.validate_post(meta)

    def test_validate_post_rejects_unknown_key(self) -> None:
        meta = _valid_meta()
        meta["weird_key"] = "x"
        with self.assertRaises(FRONTMATTER.FrontmatterError) as ctx:
            FRONTMATTER.validate_post(meta)
        self.assertIn("unknown key", str(ctx.exception))

    def test_validate_post_rejects_missing_required_field(self) -> None:
        meta = _valid_meta()
        del meta["collected_at"]
        with self.assertRaises(FRONTMATTER.FrontmatterError) as ctx:
            FRONTMATTER.validate_post(meta)
        self.assertIn("collected_at", str(ctx.exception))

    def test_validate_post_rejects_non_numeric_post_url(self) -> None:
        meta = _valid_meta()
        meta["post_url"] = "https://x.com/realchendahuang/status/not-a-number"
        with self.assertRaises(FRONTMATTER.FrontmatterError) as ctx:
            FRONTMATTER.validate_post(meta)
        self.assertIn("post_url", str(ctx.exception))

    def test_validate_post_pairs_id_prefix_with_kind(self) -> None:
        """A `post-` id with `kind: hit` used to pass, silently polluting the benchmark set."""
        mismatched = dict(_valid_meta(), id="hit-20260909-001", kind="published")
        with self.assertRaises(FRONTMATTER.FrontmatterError) as ctx:
            FRONTMATTER.validate_post(mismatched)
        self.assertIn("does not match kind", str(ctx.exception))

        hit = {
            "id": "hit-20260909-001",
            "kind": "hit",
            "post_url": "https://x.com/realchendahuang/status/1234567890",
            "collected_at": "2026-09-09T10:00:00+08:00",
        }
        FRONTMATTER.validate_post(hit)
        FRONTMATTER.validate_post(dict(hit, id="hit-site-20260909-001"))
        with self.assertRaises(FRONTMATTER.FrontmatterError):
            FRONTMATTER.validate_post(dict(hit, id="post-20260909-001"))


def _valid_meta() -> dict:
    return {
        "id": "post-20260909-001",
        "kind": "published",
        "post_url": "https://x.com/realchendahuang/status/1234567890",
        "collected_at": "2026-09-09T10:00:00+08:00",
    }


class StatsTests(unittest.TestCase):
    def test_since_compares_shanghai_local_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            write_archive(
                root,
                "post-20260909-001.md",
                posted_at="2026-09-08T16:16:11Z",
                extra="source: chendahuang.com/mirror\n",
            )
            write_archive(root, "post-20260907-001.md", posted_at="2026-09-07T10:00:00+08:00")
            with mock.patch.object(STATS, "find_root", return_value=root):
                code, out, err = run_module_main(STATS, ["stats.py", "--since", "2026-09-09", "--no-csv"])
        self.assertEqual(code, 0)
        self.assertIn("posts: 1", out)
        self.assertNotIn("post-20260907-001", out)
        self.assertIn("data coverage:", err)

    def test_until_is_inclusive_of_the_shanghai_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            write_archive(root, "post-20260909-001.md", posted_at="2026-09-08T16:16:11Z")
            write_archive(root, "post-20260910-001.md", posted_at="2026-09-10T09:00:00+08:00")
            with mock.patch.object(STATS, "find_root", return_value=root):
                code, out, _err = run_module_main(
                    STATS, ["stats.py", "--until", "2026-09-09", "--no-csv"]
                )
        self.assertEqual(code, 0)
        self.assertIn("posts: 1", out)

    def test_csv_header_carries_bookmarks_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            write_archive(
                root,
                "post-20260909-001.md",
                extra=(
                    "source: chendahuang.com/mirror\n"
                    "metrics:\n  views: 10\n  likes: 2\n  bookmarks: 7\n"
                ),
            )
            with mock.patch.object(STATS, "find_root", return_value=root):
                code, out, err = run_module_main(STATS, ["stats.py"])
            csvs = list((root / "workspace" / "stats").glob("posts-*.csv"))
            self.assertEqual(code, 0)
            self.assertEqual(len(csvs), 1)
            with csvs[0].open(encoding="utf-8", newline="") as handle:
                header = handle.readline().strip().split(",")
                row = handle.readline()
            self.assertEqual(header, STATS.COLUMNS)
            self.assertIn("bookmarks", header)
            self.assertIn("source", header)
            self.assertIn("chendahuang.com/mirror", row)
            self.assertIn("draft_id 0/1 (0%)", err)

    def test_non_dict_metrics_are_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            write_archive(root, "post-20260909-001.md", extra="metrics: hand-edited\n")
            with mock.patch.object(STATS, "find_root", return_value=root):
                code, out, _err = run_module_main(STATS, ["stats.py", "--no-csv"])
        self.assertEqual(code, 0)
        self.assertIn("posts: 1", out)
        self.assertEqual(STATS.row_of({"metrics": ["oops"]})["bookmarks"], "")


class RecordPostTests(unittest.TestCase):
    def test_rejects_duplicate_status_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            existing = write_archive(
                root,
                "post-20260909-001.md",
                post_url="https://x.com/realchendahuang/status/111222333444",
            )
            with mock.patch.object(RECORD_POST, "find_root", return_value=root):
                code, _out, err = run_module_main(
                    RECORD_POST,
                    [
                        "record_post.py",
                        "--url",
                        "https://x.com/realchendahuang/status/111222333444",
                        "--channel",
                        "intent",
                        "--no-draft",
                        "--dry-run",
                    ],
                )
            self.assertEqual(code, 2)
            self.assertIn(existing.name, err)
            self.assertEqual(len(list((root / "workspace" / "posts").glob("*.md"))), 1)

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            posts = root / "workspace" / "posts"
            with mock.patch.object(RECORD_POST, "find_root", return_value=root):
                code, out, _err = run_module_main(
                    RECORD_POST,
                    [
                        "record_post.py",
                        "--url",
                        "https://x.com/realchendahuang/status/999888777",
                        "--channel",
                        "intent",
                        "--no-draft",
                        "--dry-run",
                        "--text",
                        "正文",
                    ],
                )
            self.assertEqual(code, 0)
            self.assertIn("dry-run", out)
            self.assertEqual(list(posts.glob("*.md")), [])

    def test_draft_id_is_now_optional_bookkeeping(self) -> None:
        """Draft-file workflow retired 2026-09-24: any draft id records cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            with mock.patch.object(RECORD_POST, "find_root", return_value=root):
                code, out, _err = run_module_main(
                    RECORD_POST,
                    [
                        "record_post.py",
                        "--url",
                        "https://x.com/realchendahuang/status/999888777",
                        "--channel",
                        "intent",
                        "--dry-run",
                    ],
                )
            self.assertEqual(code, 0)
            self.assertIn("dry-run", out)

    def test_status_id_extraction(self) -> None:
        self.assertEqual(
            RECORD_POST.status_id("https://twitter.com/a/status/12345?s=20"), "12345"
        )
        self.assertIsNone(RECORD_POST.status_id("https://x.com/explore"))

    def test_recording_a_post_advances_its_topic(self) -> None:
        """The ledger link: a published post must reach the topic it came from."""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            topics = root / "workspace" / "topics"
            topics.mkdir(parents=True, exist_ok=True)
            topic_path = topics / "topic-1.md"
            TOPIC_STORE.atomic_write(
                topic_path,
                {
                    "id": "topic-1",
                    "status": "candidate",
                    "draft_ids": ["draft-20260901-known"],
                    "brief_ids": ["brief-1"],
                    "post_urls": [],
                },
            )
            with mock.patch.object(RECORD_POST, "find_root", return_value=root):
                code, out, _err = run_module_main(
                    RECORD_POST,
                    [
                        "record_post.py",
                        "--url",
                        "https://x.com/realchendahuang/status/999888777",
                        "--channel",
                        "intent",
                        "--draft-id",
                        "draft-20260901-known",
                        "--topic-id",
                        "topic-1",
                        "--text",
                        "正文",
                    ],
                )
            self.assertEqual(code, 0, out)
            stored = TOPIC_STORE.load_topic(topic_path)
            self.assertEqual(stored["status"], "published")
            self.assertEqual(stored["post_urls"], ["https://x.com/realchendahuang/status/999888777"])
            self.assertIn("topic advanced: topic-1", out)

    def test_parked_topic_advances_to_published(self) -> None:
        """A parked topic that actually shipped must become published — parked
        means 'set aside, may write later', not 'immune to reality'."""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            topics = root / "workspace" / "topics"
            topics.mkdir(parents=True, exist_ok=True)
            topic_path = topics / "topic-parked.md"
            TOPIC_STORE.atomic_write(
                topic_path,
                {"id": "topic-parked", "status": "parked", "post_urls": []},
            )
            with mock.patch.object(RECORD_POST, "find_root", return_value=root):
                code, _out, err = run_module_main(
                    RECORD_POST,
                    [
                        "record_post.py",
                        "--url",
                        "https://x.com/realchendahuang/status/999888778",
                        "--channel",
                        "intent",
                        "--no-draft",
                        "--topic-id",
                        "topic-parked",
                        "--text",
                        "正文",
                    ],
                )
            self.assertEqual(code, 0)
            stored = TOPIC_STORE.load_topic(topic_path)
            self.assertEqual(stored["status"], "published")
            self.assertEqual(
                stored["post_urls"],
                ["https://x.com/realchendahuang/status/999888778"],
            )

    def test_no_topic_skips_the_library(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            topics = root / "workspace" / "topics"
            topics.mkdir(parents=True, exist_ok=True)
            topic_path = topics / "topic-1.md"
            TOPIC_STORE.atomic_write(
                topic_path,
                {"id": "topic-1", "status": "drafted", "post_urls": []},
            )
            before = topic_path.read_bytes()
            with mock.patch.object(RECORD_POST, "find_root", return_value=root):
                code, _out, _err = run_module_main(
                    RECORD_POST,
                    [
                        "record_post.py",
                        "--url",
                        "https://x.com/realchendahuang/status/999888779",
                        "--channel",
                        "intent",
                        "--no-draft",
                        "--topic-id",
                        "topic-1",
                        "--no-topic",
                    ],
                )
            self.assertEqual(code, 0)
            self.assertEqual(topic_path.read_bytes(), before)


class AtomicClaimTests(unittest.TestCase):
    """Concurrent writers must not compute the same free id and overwrite each other."""

    def test_two_claims_never_return_the_same_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            first_id, first_path = FRONTMATTER.next_free_id(posts, "post-20260920-")
            # The claim is the created file, so a second caller must see it as taken
            # even though the first has not written its body yet.
            second_id, second_path = FRONTMATTER.next_free_id(posts, "post-20260920-")
        self.assertEqual(first_id, "post-20260920-001")
        self.assertEqual(second_id, "post-20260920-002")
        self.assertNotEqual(first_path, second_path)

    def test_existing_ids_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            (posts / "post-20260920-001.md").write_text("taken", encoding="utf-8")
            (posts / "post-20260920-002.md").write_text("taken", encoding="utf-8")
            post_id, _path = FRONTMATTER.next_free_id(posts, "post-20260920-")
        self.assertEqual(post_id, "post-20260920-003")

    def test_claim_reports_a_taken_id_instead_of_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            existing = posts / "post-20260920-001.md"
            existing.write_text("original body", encoding="utf-8")
            self.assertIsNone(FRONTMATTER.claim_path(posts, "post-20260920-001"))
            self.assertEqual(existing.read_text(encoding="utf-8"), "original body")

    def test_write_is_atomic_and_replaces_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "post-20260920-001.md"
            meta = {
                "id": "post-20260920-001",
                "kind": "published",
                "post_url": "https://x.com/realchendahuang/status/123",
                "collected_at": "2026-09-20T10:00:00+08:00",
            }
            FRONTMATTER.write(path, meta, "正文\n")
            FRONTMATTER.write(path, meta, "更新的正文\n")
            _meta, body = FRONTMATTER.load(path)
            self.assertIn("更新的正文", body)
            # No stray temp files left behind in the directory.
            self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])

    def test_record_post_reports_the_next_id_in_dry_run(self) -> None:
        """--dry-run must not reserve a file, but still name the id it would use."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            posts = root / "workspace" / "posts"
            with mock.patch.object(RECORD_POST, "find_root", return_value=root):
                code, out, _err = run_module_main(
                    RECORD_POST,
                    [
                        "record_post.py",
                        "--url",
                        "https://x.com/realchendahuang/status/555000111",
                        "--channel",
                        "intent",
                        "--no-draft",
                        "--dry-run",
                    ],
                )
            self.assertEqual(code, 0, out)
            self.assertIn("post-", out)
            self.assertEqual(list(posts.glob("*.md")), [], "dry-run must not reserve an id")

    def test_reserved_id_is_deleted_when_validation_fails(self) -> None:
        """A rejected entry must not leave an empty archive behind."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            posts = root / "workspace" / "posts"
            with mock.patch.object(RECORD_POST, "find_root", return_value=root):
                code, _out, _err = run_module_main(
                    RECORD_POST,
                    [
                        "record_post.py",
                        "--url",
                        "https://x.com/realchendahuang/status/555000112",
                        "--channel",
                        "intent",
                        "--no-draft",
                        "--posted-at",
                        "not-a-timestamp",
                        "--text",
                        "正文",
                    ],
                )
            self.assertEqual(code, 2)
            self.assertEqual(list(posts.glob("*.md")), [])


class ArchiveHitTests(unittest.TestCase):
    def test_text_without_url_requires_no_url(self) -> None:
        code, _out, err = run_module_main(
            ARCHIVE_HIT, ["archive_hit.py", "--text", "正文"]
        )
        self.assertEqual(code, 2)
        self.assertIn("--no-url", err)

    def test_url_must_carry_numeric_status_id(self) -> None:
        code, _out, err = run_module_main(
            ARCHIVE_HIT, ["archive_hit.py", "--url", "https://x.com/realchendahuang/"]
        )
        self.assertEqual(code, 2)
        self.assertIn("numeric id", err)

    def test_strip_text_decorations(self) -> None:
        decorated = (
            "@realchendahuang: 第一行\n第二行\n\n"
            "点赞: 12 | 转推: 3 | 浏览: 456\n"
        )
        self.assertEqual(
            ARCHIVE_HIT.strip_text_decorations(decorated), "第一行\n第二行"
        )
        self.assertEqual(
            ARCHIVE_HIT.strip_text_decorations("@someone: 没有指标"), "没有指标"
        )
        self.assertEqual(
            ARCHIVE_HIT.strip_text_decorations("Likes: 1 | Retweets: 2 | Views: 3"),
            "",
        )

    def test_no_url_dry_run_writes_nothing_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            with mock.patch.object(ARCHIVE_HIT, "find_root", return_value=root):
                code, out, _err = run_module_main(
                    ARCHIVE_HIT,
                    ["archive_hit.py", "--no-url", "--text", "正文", "--dry-run"],
                )
            self.assertEqual(code, 0)
            self.assertIn("--no-url", out)
            self.assertEqual(list((root / "workspace" / "posts").glob("*.md")), [])

    def test_duplicate_status_id_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            write_archive(
                root,
                "hit-20260909-001.md",
                kind="hit",
                post_url="https://x.com/realchendahuang/status/555666777",
            )
            with mock.patch.object(ARCHIVE_HIT, "find_root", return_value=root):
                code, out, _err = run_module_main(
                    ARCHIVE_HIT,
                    [
                        "archive_hit.py",
                        "--url",
                        "https://x.com/realchendahuang/status/555666777",
                        "--dry-run",
                    ],
                )
            self.assertEqual(code, 0)
            self.assertIn("already archived", out)
            self.assertEqual(len(list((root / "workspace" / "posts").glob("*.md"))), 1)


class BackfillMetricsTests(unittest.TestCase):
    def test_all_zero_snapshot_is_skipped(self) -> None:
        tweet = {"views": 0, "likes": 0, "retweets": 0, "replies_count": 0, "bookmarks": 0}
        metrics, reason = BACKFILL.select_metrics(tweet)
        self.assertEqual(metrics, {})
        self.assertIn("zero", reason)

        meta, body, changes = BACKFILL.backfill_file(
            Path("post-x.md"),
            {"id": "post-x", "kind": "published"},
            "正文\n",
            {"tweet": {**tweet, "text": "正文"}},
            sync_text=False,
            now=PAST,
            window="backfill",
        )
        self.assertNotIn("metrics", meta)
        self.assertNotIn("snapshot", body)
        self.assertTrue(any("zero" in change for change in changes))

    def test_metrics_present_restricts_merged_keys(self) -> None:
        tweet = {"views": 5, "likes": 0, "bookmarks": 0, "metrics_present": ["views"]}
        metrics, reason = BACKFILL.select_metrics(tweet)
        self.assertIsNone(reason)
        self.assertEqual(metrics, {"views": 5})

    def test_metrics_present_keeps_real_zeros_using_fetch_key_names(self) -> None:
        # x-fetch emits fetch-side names (retweets/replies_count); an explicit
        # zero is real data there and must survive the merge.
        tweet = {
            "views": 5,
            "likes": 0,
            "retweets": 0,
            "replies_count": 2,
            "bookmarks": 0,
            "metrics_present": ["views", "likes", "retweets", "replies_count"],
        }
        metrics, reason = BACKFILL.select_metrics(tweet)
        self.assertIsNone(reason)
        self.assertEqual(metrics, {"views": 5, "likes": 0, "reposts": 0, "replies": 2})

    def test_window_label_appears_in_recycle_line(self) -> None:
        line = BACKFILL.recycle_line(PAST, {"views": 100}, "24h")
        self.assertIn("[24h] snapshot: views=100", line)

        meta, body, _changes = BACKFILL.backfill_file(
            Path("post-x.md"),
            {"id": "post-x", "kind": "published"},
            "正文\n",
            {"tweet": {"text": "正文", "views": 100, "likes": 3}},
            sync_text=False,
            now=PAST,
            window="backfill",
        )
        self.assertEqual(meta["metrics"], {"views": 100, "likes": 3})
        self.assertIn("[backfill] snapshot: views=100 likes=3", body)

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            path = write_archive(
                root,
                "post-20260909-001.md",
                extra="metrics:\n  views: 1\n",
            )
            before = path.read_bytes()
            payload = {
                "tweet": {
                    "text": "正文",
                    "views": 100,
                    "likes": 3,
                    "created_at": "Sat Sep 05 02:15:18 +0000 2026",
                }
            }
            with mock.patch.object(BACKFILL, "find_root", return_value=root), mock.patch.object(
                BACKFILL, "fetch_tweet", return_value=payload
            ):
                code, out, _err = run_module_main(
                    BACKFILL, ["backfill_metrics.py", "--all", "--kind", "published", "--dry-run"]
                )
            self.assertEqual(code, 0)
            self.assertIn("would change", out)
            self.assertIn("changed=1", out)
            self.assertEqual(path.read_bytes(), before)

    def test_all_zero_fetch_is_reported_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            path = write_archive(root, "post-20260909-001.md")
            before = path.read_bytes()
            payload = {
                "tweet": {
                    "text": "正文",
                    "views": 0,
                    "likes": 0,
                    "retweets": 0,
                    "replies_count": 0,
                    "bookmarks": 0,
                }
            }
            with mock.patch.object(BACKFILL, "find_root", return_value=root), mock.patch.object(
                BACKFILL, "fetch_tweet", return_value=payload
            ):
                code, out, _err = run_module_main(
                    BACKFILL, ["backfill_metrics.py", "--all", "--kind", "published"]
                )
            self.assertEqual(code, 0)
            self.assertIn("zero", out)
            self.assertIn("changed=0", out)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
