#!/usr/bin/env python3
"""Triage candidate topics in workspace/topics/ against the four-point hit filter and Blueprint A–E.

Evaluates unwritten candidate topics, scores their viral potential, recommends the
best-fitting Blueprint (A–E), and prints a prioritized recommendation list to eliminate
backlog bottlenecks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topic_store as store  # noqa: E402

# Keywords for the four-point filter
KEYWORD_MICRO_PAIN = ["难受", "烦", "坑", "黑框框", "为什么", "配置", "慢", "贵", "限额", "问题", "误伤", "痛点", "崩溃"]
KEYWORD_DELIVERABLE = ["全家桶", "方案", "整理", "教程", "流程", "最佳实践", "配置", "清单", "脚本", "工具", "代码", "推荐", "库"]
KEYWORD_COUNTER_INTUITIVE = ["以为", "其实", "反差", "区别", "淘汰", "暴论", "替代", "二等公民", "真正", "误区", "真相"]
KEYWORD_EXTREME_ROI = ["免费", "便宜", "美元", "元", "成本", "省钱", "白嫖", "额度", "性价比", "穷鬼", "算账", "包月"]

# Pattern matching for Blueprints A-E
BLUEPRINT_PATTERNS = {
    "D": {
        "name": "以问代讲征集型 (Blueprint D)",
        "keywords": ["大家", "用什么", "好奇", "会使用", "怎么看", "区别", "最佳实践", "？", "?", "请教", "探讨"],
        "reason": "以问代讲激发程序员布道欲与评论区争议，极低阅读门槛，算法推流权重最高",
    },
    "A": {
        "name": "隐藏功能挖宝型 (Blueprint A)",
        "keywords": ["隐藏", "免费", "白嫖", "自带", "内置", "福利", "官方居然", "好东西", "流量", "小技巧"],
        "reason": "击穿官方信息差，分钱级算账 + 1-2-3-4 极简步骤，冲收藏与曝光天花板",
    },
    "B": {
        "name": "深度横评与版本答案 (Blueprint B)",
        "keywords": ["对比", "选型", "哪个好", "替代", "淘汰", "折腾", "选择", "Harness", "哪个好用", "体验"],
        "reason": "排除法痛点收窄 + 一锤定音给死结论（版本答案），建立极强专家信任",
    },
    "C": {
        "name": "架构分层手册型 (Blueprint C)",
        "keywords": ["架构", "配置", "SDK", "工作流", "定制", "分层", "方案", "系统", "全套", "插件"],
        "reason": "认知反转开局 + 四层递进结构（Prompt->Skill->Ext->Pkg），超高藏赞比(1.5+)",
    },
    "E": {
        "name": "痛点对抗与实战复盘 (Blueprint E)",
        "keywords": ["血泪", "踩坑", "复盘", "经验", "开源", "独立开发", "产品", "出海", "上线", "怒", "对抗"],
        "reason": "情绪触发 + 真实教训白描 + 最终收敛的 MVP 技术栈，建立同行共鸣与专家信任",
    },
}


def score_topic(record: dict[str, Any]) -> dict[str, Any]:
    text = f"{record.get('title', '')} {record.get('statement', '')}"

    # 1. Four-point filter scoring (each up to 25 pts)
    score_pain = min(25, sum(8 for k in KEYWORD_MICRO_PAIN if k in text))
    score_deliv = min(25, sum(8 for k in KEYWORD_DELIVERABLE if k in text))
    score_contra = min(25, sum(8 for k in KEYWORD_COUNTER_INTUITIVE if k in text))
    score_roi = min(25, sum(10 for k in KEYWORD_EXTREME_ROI if k in text))

    base_score = score_pain + score_deliv + score_contra + score_roi
    # Bonus for primary pillar
    if record.get("pillar_id") == "ai-coding-agents":
        base_score += 10
    elif record.get("pillar_id") in {"indie-dev", "ai-productivity"}:
        base_score += 5

    final_score = min(100, max(20, base_score))

    # 2. Determine best matching Blueprint
    bp_scores: dict[str, int] = {}
    for bp, meta in BLUEPRINT_PATTERNS.items():
        bp_scores[bp] = sum(1 for k in meta["keywords"] if k in text)

    best_bp = max(bp_scores, key=lambda k: bp_scores[k])
    # If no keywords matched, default to Blueprint D for short/questioning, B for selection
    if bp_scores[best_bp] == 0:
        if any(mark in text for mark in ("？", "?", "为什么", "怎么")):
            best_bp = "D"
        else:
            best_bp = "B"

    matched_bp_meta = BLUEPRINT_PATTERNS[best_bp]

    return {
        "id": record.get("id"),
        "title": record.get("title"),
        "pillar_id": record.get("pillar_id"),
        "status": record.get("status"),
        "score": final_score,
        "blueprint": best_bp,
        "blueprint_name": matched_bp_meta["name"],
        "blueprint_reason": matched_bp_meta["reason"],
        "statement": record.get("statement", "").strip(),
        "created_at": record.get("created_at"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Triage topics in workspace/topics/ by viral potential and match Blueprints A-E."
    )
    parser.add_argument("--status", default="candidate", help="Topic status to filter (default: candidate).")
    parser.add_argument("--pillar", help="Filter by pillar id.")
    parser.add_argument("--limit", type=int, default=10, help="Number of top candidates to display (default: 10).")
    parser.add_argument("--json", action="store_true", help="Output results as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = store.find_repo_root()
        library = store.resolve_library(repo, None)
        topics = store.iter_topics(library)

        target_status = store.STATUS_ALIASES.get(args.status, args.status)
        evaluated = []
        for _path, record in topics:
            if target_status and record.get("status") != target_status:
                continue
            if args.pillar and record.get("pillar_id") != args.pillar:
                continue
            evaluated.append(score_topic(record))

        evaluated.sort(key=lambda x: x["score"], reverse=True)
        top_picks = evaluated[: args.limit]

        if args.json:
            print(
                json.dumps(
                    {
                        "total_evaluated": len(evaluated),
                        "top_picks": top_picks,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        status_label = store.STATUS_LABELS.get(target_status, target_status)
        print("\n" + "=" * 70)
        print(f"🎯 选题库高爆分拣排行榜 (共 {len(evaluated)} 条【{status_label}】，展示 Top {len(top_picks)})")
        print("=" * 70 + "\n")

        for idx, item in enumerate(top_picks, 1):
            print(f"【No.{idx:02d} | 潜力分: {item['score']}】 {item['title']} [{item['pillar_id'] or '未分配'}]")
            print(f"  📌 选题 ID: {item['id']}")
            print(f"  🚀 推荐蓝图: {item['blueprint_name']}")
            print(f"  💡 推荐理由: {item['blueprint_reason']}")
            stmt_snippet = item['statement'][:90] + ("..." if len(item['statement']) > 90 else "")
            print(f"  📝 原话摘录: \"{stmt_snippet}\"\n")

        print("=" * 70)
        print("提示：挑好题后直接在对话里说写成帖子，写作纯对话直出，不落草稿文件。\n")
        return 0
    except store.TopicError as exc:
        print(f"[triage-topics] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
