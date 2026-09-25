#!/usr/bin/env python3
"""Batch tag hit posts in workspace/posts/ with pillar, structure, hook, tags, and empirical annotations.

Resolves the 2% metadata coverage bottleneck by auto-tagging top hit posts with
verified Blueprint A–E tags, extracting opening hooks, classifying content pillars,
and backfilling empirical notes into '## 我的批注'.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontmatter import load_all, validate_post, write  # noqa: E402

ALLOWED_STRUCTURES = {"opinion", "list", "story", "thread", "quote"}
PILLARS = {"ai-coding-agents", "indie-dev", "ai-productivity", "insight-income"}


def clean_hook(first_line: str) -> str:
    cleaned = re.sub(r"^#+\s*", "", first_line).strip()
    return cleaned[:100]


def infer_pillar(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ["cloudflare", "pwa", "独立开发", "mvp", "部署", "sub-store", "域名", "出海", "app"]):
        return "indie-dev"
    if any(k in lower for k in ["deepseek", "codex", "opencode", "claude", "agent", "harness", "glm", "qwen", "zcode", "gemini", "模型", "api"]):
        return "ai-coding-agents"
    if any(k in lower for k in ["macos", "浏览器", "firefox", "brave", "工作流", "效率", "快捷键", "插件", "福滤娃"]):
        return "ai-productivity"
    return "ai-coding-agents"


def infer_structure(body: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if any(re.match(r"^(?:[1-9]\.|[①-⑩]|第[一二三四1-4])", line) for line in lines):
        return "list"
    if any("## post 2" in line.lower() for line in lines):
        return "thread"
    if len(lines) <= 4:
        return "opinion"
    if any(k in body for k in ["一怒之下", "笑了5分钟", "血泪"]):
        return "story"
    return "opinion"


def infer_blueprint(body: str, metrics: dict[str, Any]) -> tuple[str, str]:
    lower = body.lower()
    replies = metrics.get("replies", 0) or 0
    likes = metrics.get("likes", 0) or 0
    bookmarks = metrics.get("bookmarks", 0) or 0
    views = metrics.get("views", 0) or 0

    if any(k in body for k in ["好奇", "大家在", "大家用", "会使用", "？", "?"]) and (replies > 40 or "好奇" in body):
        return "blueprint-d", "【蓝图 D 以问代讲】极低阅读门槛 + 抛出真实争议，以问代讲引爆评论区讨论欲，算法推流权重极高。"

    if any(k in body for k in ["厚礼蟹", "内置了", "免费", "50g", "白嫖", "使用方法就是"]):
        return "blueprint-a", "【蓝图 A 挖宝型】击穿官方信息差，痛点直击 + 极简四步上手清单，分钱级算账，冲曝光与收藏双高。"

    if any(k in body for k in ["折腾", "排除", "版本答案", "对比", "二等公民"]):
        return "blueprint-b", "【蓝图 B 排除法选型】痛点铺垫 + 逐项排除竞品劣势 + 一锤定音给死结论（版本答案），建立极强专家信任。"

    if any(k in body for k in ["分四层", "毛坯房", "架构", "sdk", "配置方案", "skill", "extension"]):
        return "blueprint-c", "【蓝图 C 分层手册】认知反转开局 + 四层递进结构，超高藏赞比(1.3~1.7)，读者存下来作为随时抄作业的工具手册。"

    if any(k in body for k in ["血泪", "踩坑", "福滤娃", "打野", "开源公开", "一怒之下"]):
        return "blueprint-e", "【蓝图 E 痛点对抗/独立开发复盘】真实痛点情绪反转 + 开源共建/实操清单，纯白描不上价值，建立强烈同行共鸣。"

    if bookmarks > likes:
        return "blueprint-c", "【高收藏手册型】藏赞比倒挂，干货清单交付感强，读者当成备用手册收藏。"

    return "blueprint-b", "【选型与观点型】直接给明确结论，结合具体场景与工具名，实操性强。"


def generate_annotation(bp_tag: str, bp_desc: str, metrics: dict[str, Any], hook: str) -> str:
    views = metrics.get("views", 0) or 0
    likes = metrics.get("likes", 0) or 0
    bookmarks = metrics.get("bookmarks", 0) or 0
    replies = metrics.get("replies", 0) or 0
    bm_ratio = (bookmarks / likes) if likes > 0 else 0

    lines = [
        "## 我的批注\n",
        f"为什么这条能爆/值得学（{bp_desc}）：",
        f"- 数据表现：曝光 {views:,} / 点赞 {likes:,} / 收藏 {bookmarks:,} / 回复 {replies}（藏赞比 {bm_ratio:.2f}）。",
        f"- 开篇钩子：`{hook}`，前两行迅速击中读者注意力，拒绝冗长铺垫。",
        f"- 模式归属：{bp_tag}，结构紧凑且留出呼吸感，纯白描交付核心价值，坚决不上空泛大道理。\n",
    ]
    return "\n".join(lines)


def tag_post(path: Path, meta: dict[str, Any], body: str, dry_run: bool = False) -> tuple[dict[str, Any], str, list[str]]:
    changes = []
    # Split out existing annotations and backfill
    clean_body = body
    recycle_section = ""
    if "## 数据回采" in body:
        parts = body.split("## 数据回采")
        clean_body = parts[0]
        recycle_section = "## 数据回采" + parts[1]

    # Extract main text before any "## 我的批注"
    main_text = clean_body.split("## 我的批注")[0].strip()
    non_empty_lines = [l.strip() for l in main_text.splitlines() if l.strip()]
    first_line = non_empty_lines[0] if non_empty_lines else ""

    metrics = meta.get("metrics", {}) or {}

    # 1. Hook
    if not meta.get("hook") and first_line:
        hook_val = clean_hook(first_line)
        meta["hook"] = hook_val
        changes.append(f"hook: '{hook_val[:30]}...'")

    # 2. Pillar
    if not meta.get("pillar"):
        pillar_val = infer_pillar(main_text)
        meta["pillar"] = pillar_val
        changes.append(f"pillar: {pillar_val}")

    # 3. Structure
    if not meta.get("structure"):
        struct_val = infer_structure(main_text)
        meta["structure"] = struct_val
        changes.append(f"structure: {struct_val}")

    # 4. Blueprint tag
    bp_tag, bp_desc = infer_blueprint(main_text, metrics)
    current_tags = meta.get("tags") or []
    if not isinstance(current_tags, list):
        current_tags = [str(current_tags)]
    if not any(t.startswith("blueprint-") for t in current_tags):
        current_tags.append(bp_tag)
        meta["tags"] = current_tags
        changes.append(f"tag: {bp_tag}")

    # 5. Verdict
    views = metrics.get("views", 0) or 0
    likes = metrics.get("likes", 0) or 0
    if not meta.get("verdict"):
        if views >= 30000 or likes >= 100 or metrics.get("bookmarks", 0) >= 100:
            meta["verdict"] = "good"
            changes.append("verdict: good")

    # 6. Check annotation
    hook = meta.get("hook", first_line)
    new_annotation = generate_annotation(bp_tag, bp_desc, metrics, hook)

    existing_notes = ""
    if "## 我的批注" in clean_body:
        existing_notes = clean_body.split("## 我的批注")[1].strip()

    # If annotation is placeholder or empty, overwrite with distilled empirical notes
    if not existing_notes or "为什么这条值得学" in existing_notes or "预留空节" in existing_notes:
        if recycle_section:
            new_body = f"{main_text}\n\n{new_annotation}\n{recycle_section}"
        else:
            new_body = f"{main_text}\n\n{new_annotation}"
        changes.append("批注已写入")
    else:
        new_body = body

    return meta, new_body, changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-tag posts in workspace/posts/ with metadata and annotations.")
    parser.add_argument("--top", type=int, default=50, help="Number of top posts by views/likes to tag (default: 50).")
    parser.add_argument("--all", action="store_true", help="Tag all posts in workspace/posts/.")
    parser.add_argument("--dry-run", action="store_true", help="Preview tags without writing files.")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[4]
    posts_dir = repo / "workspace" / "posts"

    records = load_all(posts_dir)
    print(f"Loaded {len(records)} posts from {posts_dir.relative_to(repo)}")

    # Sort to prioritize hits
    def hit_score(item: tuple[Path, dict, str]) -> int:
        m = item[1].get("metrics", {}) or {}
        return (m.get("views", 0) or 0) + (m.get("likes", 0) or 0) * 100 + (m.get("bookmarks", 0) or 0) * 150

    sorted_records = sorted(records, key=hit_score, reverse=True)
    targets = sorted_records if args.all else sorted_records[: args.top]

    updated_count = 0
    for path, meta, body in targets:
        new_meta, new_body, changes = tag_post(path, meta, body, dry_run=args.dry_run)
        if changes:
            updated_count += 1
            mode = "[DRY-RUN] " if args.dry_run else ""
            print(f"{mode}Updated {path.name}: {', '.join(changes)}")
            if not args.dry_run:
                validate_post(new_meta, path)
                write(path, new_meta, new_body)

    print(f"\nDone! {updated_count}/{len(targets)} posts updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
