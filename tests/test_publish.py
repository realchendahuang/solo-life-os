from __future__ import annotations

import importlib.util
import io
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DRAFT_TEXT = load_module(
    "x_tiller_draft_text",
    ".agents/skills/publish-x/scripts/draft_text.py",
)
INTENT_OPEN = load_module(
    "x_tiller_intent_open",
    ".agents/skills/publish-x/scripts/intent_open.py",
)
FILL_CLIPBOARD = load_module(
    "x_tiller_fill_clipboard",
    ".agents/skills/publish-x/scripts/fill_clipboard.py",
)
WEBBRIDGE = load_module(
    "x_tiller_webbridge",
    ".agents/skills/publish-x/scripts/webbridge_client.py",
)
REAL_DRAFT = ROOT / "workspace" / "drafts" / "20260907-whack-a-mole-ai-agents.md"
REAL_FIRST_BODY_LINE = "我现在每天基本上就是在打地鼠。"

APPROVED_DRAFT = (
    "---\n"
    "id: draft-test\n"
    "status: approved\n"
    "source_urls: []\n"
    "---\n"
    "\n"
    "# Post\n"
    "\n"
    "第一条正文。\n"
)


def write_draft(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    )
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


def run_main(module: ModuleType, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(argv)
    return code, out.getvalue(), err.getvalue()


def _body_after_frontmatter(text: str) -> str:
    """Everything after the closing `---` line, independent of the module's own parsing."""
    match = re.search(r"\n---[^\S\n]*\r?\n", text)
    if match is None:
        raise AssertionError("no closing frontmatter delimiter")
    return text[match.end():]


class DraftTextTests(unittest.TestCase):
    def test_load_draft_returns_empty_meta_without_frontmatter(self) -> None:
        path = write_draft("只有正文。\n")
        try:
            meta, body = DRAFT_TEXT.load_draft(path)
        finally:
            path.unlink()
        self.assertEqual(meta, {})
        self.assertEqual(body, "只有正文。\n")

    def test_load_draft_parses_frontmatter_and_returns_body_only(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            meta, body = DRAFT_TEXT.load_draft(path)
        finally:
            path.unlink()
        self.assertEqual(meta["status"], "approved")
        self.assertTrue(body.lstrip().startswith("# Post"))
        self.assertNotIn("id: draft-test", body)

    def test_load_draft_rejects_non_mapping_frontmatter(self) -> None:
        path = write_draft("---\n- just\n- a list\n---\n\n正文\n")
        try:
            with self.assertRaises(DRAFT_TEXT.DraftError):
                DRAFT_TEXT.load_draft(path)
        finally:
            path.unlink()

    def test_publishable_posts_drops_notes_sections(self) -> None:
        body = (
            "# Post\n\n"
            "正文。\n\n"
            "## Verification notes\n\n"
            "待核实：价格。\n\n"
            "## Feedback\n\n"
            "用户改过这里。\n\n"
            "## Notes\n\n"
            "内部备注。\n"
        )
        self.assertEqual(DRAFT_TEXT.publishable_posts({}, body), ["正文。"])

    def test_publishable_posts_keeps_hashtag_lines(self) -> None:
        body = "# Post\n\n#AI 编程工具 又更新了。\n"
        posts = DRAFT_TEXT.publishable_posts({}, body)
        self.assertEqual(posts, ["#AI 编程工具 又更新了。"])

    def test_publishable_posts_preserves_heading_lines_in_code_fences(self) -> None:
        body = "# Post\n\n正文。\n\n```\n# not a heading\n## neither\n```\n"
        posts = DRAFT_TEXT.publishable_posts({}, body)
        self.assertIn("# not a heading", posts[0])
        self.assertIn("## neither", posts[0])

    def test_publishable_posts_ignores_post_heading_inside_fence(self) -> None:
        body = "# Post\n\n正文。\n\n```\n## Post 9\n```\n\n结尾。\n"
        posts = DRAFT_TEXT.publishable_posts({}, body)
        self.assertEqual(len(posts), 1)
        self.assertIn("## Post 9", posts[0])

    def test_publishable_posts_splits_thread_sections(self) -> None:
        body = (
            "# Post 1\n\n"
            "第一部分。\n\n"
            "# Post 2\n\n"
            "第二部分。\n\n"
            "# Post 3\n\n"
            "第三部分。\n"
        )
        self.assertEqual(
            DRAFT_TEXT.publishable_posts({}, body),
            ["第一部分。", "第二部分。", "第三部分。"],
        )

    def test_publishable_posts_treats_body_without_post_heading_as_one_post(self) -> None:
        body = "没有 Post 标题的旧草稿。\n\n第二段。\n"
        posts = DRAFT_TEXT.publishable_posts({}, body)
        self.assertEqual(posts, [body.strip()])

    def test_publishable_posts_never_concatenates_into_one_blob(self) -> None:
        body = "## Post 1\n\n一。\n\n## Post 2\n\n二。\n"
        posts = DRAFT_TEXT.publishable_posts({}, body)
        self.assertEqual(len(posts), 2)
        self.assertNotIn("二。", posts[0])

    def test_weighted_length_counts_cjk_as_two_and_ascii_as_one(self) -> None:
        self.assertEqual(DRAFT_TEXT.weighted_length("hello"), 5)
        self.assertEqual(DRAFT_TEXT.weighted_length("中文文字"), 8)
        self.assertEqual(DRAFT_TEXT.weighted_length("中a中"), 5)

    def test_weighted_length_counts_url_as_23(self) -> None:
        self.assertEqual(DRAFT_TEXT.weighted_length("https://example.com/a"), 23)
        self.assertEqual(DRAFT_TEXT.weighted_length("hi中 https://a.b/c"), 28)
        self.assertEqual(DRAFT_TEXT.MAX_WEIGHT, 280)

    def test_preview_reports_weight_and_marks_truncation(self) -> None:
        short = DRAFT_TEXT.preview("短文本")
        self.assertTrue(short.startswith(f"weighted 6/{DRAFT_TEXT.MAX_WEIGHT} | 短文本"))
        long_text = "字" * 200
        long_preview = DRAFT_TEXT.preview(long_text)
        self.assertIn("…", long_preview)
        self.assertEqual(
            long_preview.count("字"), 160, "first 80 + last 80 characters"
        )

    def test_extracts_real_draft_without_leaking_frontmatter(self) -> None:
        if not REAL_DRAFT.is_file():
            self.skipTest("real draft is not present in this checkout")
        meta, body = DRAFT_TEXT.load_draft(REAL_DRAFT)
        posts = DRAFT_TEXT.publishable_posts(meta, body)
        self.assertEqual(len(posts), 1)
        text = posts[0]
        self.assertFalse(text.startswith("---"))
        for leaked in ("id: draft-", "status:", "source_urls", "待核实"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, text)
        self.assertTrue(text.startswith(REAL_FIRST_BODY_LINE), text[:40])


class IntentOpenTests(unittest.TestCase):
    def test_dry_run_never_touches_clipboard_or_browser(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            with mock.patch.object(
                INTENT_OPEN.subprocess,
                "run",
                side_effect=AssertionError("subprocess must not run in --dry-run"),
            ):
                code, out, _ = run_main(
                    INTENT_OPEN, ["--file", str(path), "--dry-run"]
                )
        finally:
            path.unlink()
        self.assertEqual(code, 0)
        self.assertIn("dry-run: clipboard and browser untouched", out)
        self.assertIn("intent URL: https://x.com/intent/post?text=", out)

    def test_real_draft_output_has_no_frontmatter_or_notes(self) -> None:
        if not REAL_DRAFT.is_file():
            self.skipTest("real draft is not present in this checkout")
        code, out, _ = run_main(
            INTENT_OPEN,
            ["--file", str(REAL_DRAFT), "--dry-run", "--allow-over-limit"],
        )
        self.assertEqual(code, 0)
        body = out.split("===== text (part 1/1) =====\n", 1)[1]
        text = body.split("\n===== end of text =====", 1)[0]
        self.assertFalse(text.startswith("---"))
        for leaked in ("id: draft-", "status:", "source_urls", "待核实"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, text)
        self.assertTrue(text.startswith(REAL_FIRST_BODY_LINE), text[:40])

    def test_refuses_unapproved_draft_and_legacy_draft(self) -> None:
        unapproved = write_draft(
            "---\nid: draft-x\nstatus: draft\n---\n\n# Post\n\n正文。\n"
        )
        legacy = write_draft("没有 frontmatter 的旧草稿。\n")
        try:
            with mock.patch.object(
                INTENT_OPEN.subprocess,
                "run",
                side_effect=AssertionError("must not run before approval gate"),
            ):
                code, _, err = run_main(
                    INTENT_OPEN, ["--file", str(unapproved), "--dry-run"]
                )
                self.assertEqual(code, 2)
                self.assertIn("not approved", err)

                code, _, err = run_main(
                    INTENT_OPEN, ["--file", str(legacy), "--dry-run"]
                )
                self.assertEqual(code, 2)
                self.assertIn("--allow-unapproved", err)

                code, out, _ = run_main(
                    INTENT_OPEN,
                    ["--file", str(legacy), "--dry-run", "--allow-unapproved"],
                )
                self.assertEqual(code, 0)
        finally:
            unapproved.unlink()
            legacy.unlink()
        self.assertIn("没有 frontmatter 的旧草稿。", out)

    def test_refuses_over_limit_unless_allowed(self) -> None:
        long_draft = write_draft(
            "---\nid: draft-long\nstatus: approved\n---\n\n# Post\n\n"
            + "字" * 200
            + "\n"
        )
        try:
            with mock.patch.object(
                INTENT_OPEN.subprocess, "run", side_effect=AssertionError("no actions")
            ):
                code, _, err = run_main(
                    INTENT_OPEN, ["--file", str(long_draft), "--dry-run"]
                )
                self.assertEqual(code, 2)
                self.assertIn("exceeds X's weighted 280 limit", err)
                self.assertIn("--allow-over-limit", err)

                code, _, err = run_main(
                    INTENT_OPEN,
                    ["--file", str(long_draft), "--dry-run", "--allow-over-limit"],
                )
                self.assertEqual(code, 0)
        finally:
            long_draft.unlink()
        self.assertIn("warning", err)
        self.assertIn("over-limit", err)

    def test_refuses_thread_without_flag_and_prepares_one_part(self) -> None:
        thread = write_draft(
            "---\nid: draft-thread\nstatus: approved\n---\n\n"
            "## Post 1\n\n第一部分。\n\n"
            "## Post 2\n\n第二部分。\n"
        )
        try:
            with mock.patch.object(
                INTENT_OPEN.subprocess, "run", side_effect=AssertionError("no actions")
            ):
                code, _, err = run_main(
                    INTENT_OPEN, ["--file", str(thread), "--dry-run"]
                )
                self.assertEqual(code, 2)
                self.assertIn("--thread", err)

                code, out, _ = run_main(
                    INTENT_OPEN,
                    ["--file", str(thread), "--dry-run", "--thread", "--part", "2"],
                )
                self.assertEqual(code, 0)
                self.assertIn("第二部分。", out)
                self.assertNotIn("第一部分。", out)

            code, _, err = run_main(
                INTENT_OPEN,
                ["--file", str(thread), "--dry-run", "--thread", "--part", "5"],
            )
            self.assertEqual(code, 2)
            self.assertIn("--part must be between 1 and 2", err)
        finally:
            thread.unlink()

    def test_darwin_uses_pbcopy_and_open(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(
                INTENT_OPEN.subprocess, "run"
            ) as runner:
                runner.return_value = subprocess.CompletedProcess([], 0)
                code, out, _ = run_main(INTENT_OPEN, ["--file", str(path)])
        finally:
            path.unlink()
        self.assertEqual(code, 0)
        commands = [call.args[0][0] for call in runner.call_args_list]
        self.assertEqual(commands, ["pbcopy", "open"])
        self.assertIn("next: review the prefilled composer and click Post yourself.", out)

    def test_non_darwin_skips_subprocess_and_prints_intent_url(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            with mock.patch.object(sys, "platform", "linux"), mock.patch.object(
                INTENT_OPEN.subprocess,
                "run",
                side_effect=AssertionError("no pbcopy/open on linux"),
            ):
                code, out, err = run_main(INTENT_OPEN, ["--file", str(path)])
        finally:
            path.unlink()
        self.assertEqual(code, 0)
        self.assertIn("intent URL: https://x.com/intent/post?text=", out)
        self.assertIn("macOS-only", err)

    def test_subprocess_failure_exits_three_with_intent_url(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(
                INTENT_OPEN.subprocess,
                "run",
                side_effect=OSError("pbcopy is not installed"),
            ):
                code, _, err = run_main(INTENT_OPEN, ["--file", str(path)])
        finally:
            path.unlink()
        self.assertEqual(code, 3)
        self.assertIn("clipboard copy failed", err)
        self.assertIn("paste this URL manually: https://x.com/intent/post?text=", err)

    def test_no_open_prints_url_without_browser(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(
                INTENT_OPEN.subprocess, "run"
            ) as runner:
                runner.return_value = subprocess.CompletedProcess([], 0)
                code, out, _ = run_main(
                    INTENT_OPEN, ["--file", str(path), "--no-open"]
                )
        finally:
            path.unlink()
        self.assertEqual(code, 0)
        commands = [call.args[0][0] for call in runner.call_args_list]
        self.assertEqual(commands, ["pbcopy"])
        self.assertIn("intent URL: https://x.com/intent/post?text=", out)


class FillClipboardTests(unittest.TestCase):
    def test_darwin_copies_extracted_text(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(
                FILL_CLIPBOARD.subprocess, "run"
            ) as runner:
                runner.return_value = subprocess.CompletedProcess([], 0)
                code, out, _ = run_main(
                    FILL_CLIPBOARD, ["--file", str(path), "--no-open"]
                )
        finally:
            path.unlink()
        self.assertEqual(code, 0)
        copy_call = runner.call_args_list[0]
        copied = copy_call.kwargs["input"].decode("utf-8")
        self.assertEqual(copied, "第一条正文。")
        self.assertNotIn("status", copied)
        commands = [call.args[0][0] for call in runner.call_args_list]
        self.assertEqual(commands, ["pbcopy"])
        self.assertIn("weighted", out)

    def test_non_darwin_prints_text_without_subprocess(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            with mock.patch.object(sys, "platform", "linux"), mock.patch.object(
                FILL_CLIPBOARD.subprocess,
                "run",
                side_effect=AssertionError("no pbcopy on linux"),
            ):
                code, out, err = run_main(FILL_CLIPBOARD, ["--file", str(path)])
        finally:
            path.unlink()
        self.assertEqual(code, 0)
        self.assertIn("第一条正文。", out)
        self.assertIn("macOS-only", err)

    def test_refuses_thread_draft(self) -> None:
        path = write_draft(
            "---\nstatus: approved\n---\n\n## Post 1\n\n一。\n\n## Post 2\n\n二。\n"
        )
        try:
            with mock.patch.object(
                FILL_CLIPBOARD.subprocess, "run", side_effect=AssertionError("no actions")
            ):
                code, _, err = run_main(FILL_CLIPBOARD, ["--file", str(path)])
        finally:
            path.unlink()
        self.assertEqual(code, 2)
        self.assertIn("intent_open.py --thread --part N", err)

    def test_pbcopy_failure_exits_three(self) -> None:
        path = write_draft(APPROVED_DRAFT)
        try:
            with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(
                FILL_CLIPBOARD.subprocess, "run", side_effect=OSError("no pbcopy")
            ):
                code, _, err = run_main(FILL_CLIPBOARD, ["--file", str(path)])
        finally:
            path.unlink()
        self.assertEqual(code, 3)
        self.assertIn("pbcopy failed", err)


class WebBridgeTests(unittest.TestCase):
    def run_webbridge(self, argv: list[str]) -> tuple[int, str, str, list[dict]]:
        sent: list[dict] = []

        def fake_post(payload: dict) -> dict:
            sent.append(payload)
            return payload

        with mock.patch.object(WEBBRIDGE, "post", side_effect=fake_post):
            code, out, err = run_main(WEBBRIDGE, argv)
        return code, out, err, sent

    def test_help_exits_zero(self) -> None:
        code, out, _, sent = self.run_webbridge(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("webbridge_client.py", out)
        self.assertIn("--unlock", out)
        self.assertEqual(sent, [])

    def test_no_args_prints_usage_and_exits_one(self) -> None:
        code, out, _, sent = self.run_webbridge([])
        self.assertEqual(code, 1)
        self.assertIn("Usage:", out)
        self.assertEqual(sent, [])

    def test_missing_arguments_are_friendly_errors(self) -> None:
        for argv in (
            ["navigate"],
            ["find_tab"],
            ["fill", "#editor"],
            ["evaluate", "--unlock"],
            ["raw", "--unlock"],
        ):
            with self.subTest(argv=argv):
                code, out, _, sent = self.run_webbridge(argv)
                self.assertEqual(code, 1)
                self.assertIn("error:", out)
                self.assertNotIn("Traceback", out)
                self.assertEqual(sent, [])

    def test_unknown_command_exits_one(self) -> None:
        code, out, _, sent = self.run_webbridge(["frobnicate"])
        self.assertEqual(code, 1)
        self.assertIn("unknown command: frobnicate", out)
        self.assertEqual(sent, [])

    def test_evaluate_and_raw_are_locked_without_unlock(self) -> None:
        for argv in (["evaluate", "document.title"], ["raw", '{"action":"list_tabs"}']):
            with self.subTest(argv=argv):
                code, out, _, sent = self.run_webbridge(argv)
                self.assertEqual(code, 1)
                self.assertIn("outside the publish flow", out)
                self.assertIn("--unlock", out)
                self.assertEqual(sent, [])

    def test_evaluate_runs_with_unlock(self) -> None:
        code, _, _, sent = self.run_webbridge(
            ["evaluate", "document.title", "--unlock"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(sent[0]["action"], "evaluate")
        self.assertEqual(sent[0]["args"]["code"], "document.title")

    def test_raw_keeps_default_session_and_honours_explicit_session(self) -> None:
        code, _, _, sent = self.run_webbridge(
            ["raw", '{"action":"list_tabs"}', "--unlock"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(sent[0]["session"], WEBBRIDGE.DEFAULT_SESSION)

        code, _, _, sent = self.run_webbridge(
            ["raw", '{"action":"list_tabs","session":"other"}', "--unlock"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(sent[0]["session"], "other")

    def test_fill_accepts_literal_path_and_stdin(self) -> None:
        code, _, _, sent = self.run_webbridge(["fill", "#editor", "hello"])
        self.assertEqual(code, 0)
        self.assertEqual(sent[0]["args"], {"selector": "#editor", "value": "hello"})

        value_file = write_draft("file contents 内容\n")
        try:
            code, _, _, sent = self.run_webbridge(
                ["fill", "#editor", str(value_file)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(sent[0]["args"]["value"], "file contents 内容\n")
        finally:
            value_file.unlink()

        with mock.patch.object(WEBBRIDGE.sys, "stdin", io.StringIO("from stdin")):
            code, _, _, sent = self.run_webbridge(["fill", "#editor", "-"])
        self.assertEqual(code, 0)
        self.assertEqual(sent[0]["args"]["value"], "from stdin")

    def test_snapshot_compact_elides_tree(self) -> None:
        def fake_post(payload: dict) -> dict:
            return {"session": payload["session"], "tree": ["node"] * 500}

        with mock.patch.object(WEBBRIDGE, "post", side_effect=fake_post):
            code, out, _ = run_main(WEBBRIDGE, ["snapshot", "--compact"])
        self.assertEqual(code, 0)
        self.assertIn("<tree omitted:", out)
        self.assertNotIn("node", out)

        with mock.patch.object(WEBBRIDGE, "post", side_effect=fake_post):
            code, out, _ = run_main(WEBBRIDGE, ["snapshot"])
        self.assertEqual(code, 0)
        self.assertIn("node", out)

    def test_compact_marks_truncation(self) -> None:
        rendered = WEBBRIDGE.compact({"tree": ["node"] * 500})
        self.assertIn("…[truncated", rendered)
        self.assertIn("chars]", rendered)
        self.assertLessEqual(len(rendered), WEBBRIDGE.COMPACT_LIMIT + 40)

        rendered = WEBBRIDGE.compact({"args": {"code": "secret()"}}, elide_tree=True)
        self.assertIn("<js omitted>", rendered)
        self.assertNotIn("secret()", rendered)


if __name__ == "__main__":
    unittest.main()
