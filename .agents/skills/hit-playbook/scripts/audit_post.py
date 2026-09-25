#!/usr/bin/env python3
"""Audit a post draft against @realchendahuang's empirical hit patterns and style rules.

Checks opening hook strength, paragraph breathability, concreteness (steps/numbers/ROI),
signature vocabulary, and generic AI anti-patterns.

Usage:
    python3 audit_post.py --file workspace/drafts/draft-example.md
    python3 audit_post.py --text "厚礼蟹！我才知道Firefox提供了免费50G的VPN流量..."
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AI_SLOP_PHRASES = [
    "在当今",
    "快速发展",
    "日新月异",
    "不得不说",
    "总的来说",
    "综上所述",
    "显而易见",
    "不可否认",
    "值得注意的是",
    "让我们拭目以待",
    "在这个时代",
    "毋庸置疑",
    "把概念掰扯清楚",
    "更要命的是",
    "当头一棒",
    "更致命的是",
    "怀疑人生",
    "商业缰绳",
    "满天飞",
    "物理定律的账本",
]

SIGNATURE_TERMS = [
    "厚礼蟹",
    "穷鬼全家桶",
    "版本答案",
    "双杀",
    "打野",
    "猎黄",
    "踩坑",
    "折腾",
    "二等公民",
    "邪修",
    "毛坯房",
    "用到地老天荒",
    "舒服（第二声）",
    "红红火火恍恍惚惚",
    "一怒之下",
    "先有鸡",
    "先有蛋",
]

PROVEN_HOOK_PREFIXES = [
    "厚礼蟹",
    "发现个好东西",
    "我才知道",
    "很多人把",
    "很多人吐槽",
    "我很好奇一个问题",
    "好奇大家用",
    "有朋友用上",
    "大家在日常",
    "大家觉得",
    "给大家分享一下",
    "分享给大家我",
    "笑死我了",
    "最近一直在折腾",
    "最近被",
    "当 AI 把",
    "一怒之下",
]


def audit_text(text: str) -> dict:
    # Strip markdown headers like ## Post or frontmatter if present
    cleaned_lines = []
    in_frontmatter = False
    frontmatter_count = 0

    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed == "---":
            frontmatter_count += 1
            in_frontmatter = frontmatter_count < 2
            continue
        if in_frontmatter:
            continue
        if trimmed.startswith("## "):
            if "post" in trimmed.lower():
                continue
            else:
                # Reached non-post section (e.g. ## Verification notes)
                break
        cleaned_lines.append(line)

    cleaned_text = "\n".join(cleaned_lines).strip()
    if not cleaned_text:
        return {"error": "empty post text"}

    paragraphs = [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]
    first_para = paragraphs[0] if paragraphs else ""
    first_line = first_para.splitlines()[0].strip() if first_para else ""

    findings = []
    score = 100

    # 1. Hook check
    hook_matched = any(first_para.startswith(p) for p in PROVEN_HOOK_PREFIXES)
    if hook_matched:
        findings.append(("PASS", "开篇钩子符合已验证爆款句式"))
    else:
        findings.append(("INFO", f"开篇钩子未命中典型高爆句式（首句: '{first_line[:30]}...'）"))

    if len(first_line) > 80:
        score -= 10
        findings.append(("WARN", f"首行长度过长（{len(first_line)} 字），建议在 60 字内换行并直击痛点"))

    # 2. Breathability & paragraph length check
    long_paras = [p for p in paragraphs if len(p.splitlines()) > 3]
    if long_paras:
        score -= 15
        findings.append(("WARN", f"发现 {len(long_paras)} 个超过 3 行的密集段落，移动端呼吸感不足，建议拆分空行"))
    else:
        findings.append(("PASS", f"排版呼吸感良好，共 {len(paragraphs)} 个呼吸段落"))

    # 3. Concreteness check (numbers, steps, ROI) or P7 question probe check
    is_p7_probe = len(paragraphs) <= 4 and any(
        first_para.startswith(p)
        for p in ("我很好奇一个问题", "好奇大家用", "有朋友用上", "大家在日常", "大家觉得")
    ) and any(kw in cleaned_text for kw in ("吗", "？", "?", "场景是什么", "最佳实践"))

    has_steps = bool(re.search(r"(?:^|\n)\s*(?:[1-9]\.|[①-⑩]|第[一二三四1-4])", cleaned_text))
    has_numbers = bool(re.search(r"\d+(?:\.\d+)?\s*(?:元|美金|\$|G|M|K|%|个|套|行)", cleaned_text))

    if is_p7_probe:
        findings.append(("PASS", "命中以问代讲（Pattern P7）流量探针模式：极简设问，免除步骤/数字硬性要求"))
    elif has_steps or has_numbers:
        findings.append(("PASS", "包含具体步骤清单/精确数字算账，实操交付感强"))
    else:
        score -= 15
        findings.append(("WARN", "未检测到具体步骤（1. 2. 3.）或量化数据，容易滑向空泛感悟"))

    # 4. AI slop check
    detected_slop = [w for w in AI_SLOP_PHRASES if w in cleaned_text]
    if detected_slop:
        score -= 25
        findings.append(("FAIL", f"检测到典型 AI 套话/废话: {', '.join(detected_slop)}，必须彻底剔除"))
    else:
        findings.append(("PASS", "未检测到 AI 腔与公关套话"))

    # 5. Signature vocabulary check
    detected_signatures = [w for w in SIGNATURE_TERMS if w in cleaned_text]
    if detected_signatures:
        findings.append(("PASS", f"包含大黄标志性语言符号: {', '.join(detected_signatures)}"))
    else:
        findings.append(("INFO", "未包含标志性口语或记忆锚点（如'穷鬼全家桶'/'版本答案'/'折腾'/'厚礼蟹'等）"))

    # 6. Feedback constraints audit (from workspace/feedback/ledger.jsonl)
    repo = Path(__file__).resolve().parents[4]
    ledger_path = repo / "workspace" / "feedback" / "ledger.jsonl"
    active_constraints = []
    ledger_warnings: list[str] = []
    if ledger_path.is_file():
        for lineno, line in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                # A corrupt line must be visible: silently skipping it drops every
                # constraint the user already gave us.
                ledger_warnings.append(f"{ledger_path.name}:{lineno}: {exc}")
                continue
            for c in row.get("constraints", []):
                if c and c not in active_constraints:
                    active_constraints.append(c)

    employee_words = ["工位", "上班", "打工", "汇报", "开会", "老板", "领导", "职场"]
    detected_employee = [w for w in employee_words if w in cleaned_text]
    if detected_employee:
        score -= 20
        findings.append(("FAIL", f"检测到打工/社畜词汇: {', '.join(detected_employee)}。违反反馈约束: 严禁社畜字眼，必须是独立开发者极客写照"))
    else:
        findings.append(("PASS", "未包含社畜打工词汇，保持独立开发者个人真实写照"))

    if "```" in cleaned_text:
        score -= 15
        findings.append(("WARN", "检测到代码块（```）。违反反馈约束: X 推文不要放代码，改用单行参数或等宽高亮"))

    forbidden_quotes = ["“", "”", "‘", "’"]
    detected_quotes = [q for q in forbidden_quotes if q in cleaned_text]
    if detected_quotes:
        score -= 20
        findings.append(("FAIL", f"检测到引号（{''.join(set(detected_quotes))}）。违反用户铁律: 严禁使用任何引号，杜绝概念刻意修饰，改用平视直接陈述"))
    else:
        findings.append(("PASS", "未包含任何修饰性引号（“”/‘’）"))

    antithesis_patterns = [r"不是.+?而是", r"不再是.+?而是", r"从来不是.+?而是"]
    detected_antithesis = [p for p in antithesis_patterns if re.search(p, cleaned_text)]
    if detected_antithesis:
        score -= 20
        findings.append(("FAIL", "检测到‘不是……而是……’套路对仗句式。违反用户铁律: 严禁使用辩论腔/说教腔对仗，改用平实直接陈述"))
    else:
        findings.append(("PASS", "未包含任何‘不是……而是……’等机械对仗套路"))

    extreme_words = [
        "死磕", "核心壁垒", "彻底打穿", "跌到地平线", "满大街", "决定死活", "毫无悬念", "逆天改命",
        "动手术刀", "掀桌子", "直接掀了桌子", "把手术刀直接动到", "非常纯粹",
    ]
    detected_extreme = [w for w in extreme_words if w in cleaned_text]
    if detected_extreme:
        score -= 20
        findings.append(("FAIL", f"检测到绝对化/极端夸张词汇: {', '.join(detected_extreme)}。违反用户铁律: 说话留有余地，保持客观分寸感，严禁好为人师与用力过猛"))
    else:
        findings.append(("PASS", "未包含极端绝对化词汇，保持客观分寸感"))

    score = max(0, min(100, score))
    return {
        "score": score,
        "first_line": first_line,
        "paragraphs_count": len(paragraphs),
        "findings": findings,
        "active_constraints": active_constraints[:5],
        "ledger_warnings": ledger_warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a post against @realchendahuang hit patterns")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path, help="Path to markdown draft or post file")
    group.add_argument("--text", type=str, help="Raw text of the post to audit")
    parser.add_argument(
        "--fail-on-fail",
        action="store_true",
        help="Exit 2 when any FAIL finding is present, so the audit can act as a gate.",
    )
    args = parser.parse_args()

    if args.file:
        if not args.file.is_file():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            raise SystemExit(2)
        raw_content = args.file.read_text(encoding="utf-8")
    else:
        raw_content = args.text

    result = audit_text(raw_content)
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        raise SystemExit(2)

    print("\n" + "=" * 50)
    print(f"📊 爆款基因与文风审核报告 (得分: {result['score']}/100)")
    print("=" * 50)
    print(f"开篇钩子: \"{result['first_line'][:50]}...\"")
    print(f"段落分块: 共 {result['paragraphs_count']} 个呼吸段落\n")

    for status, msg in result["findings"]:
        icon = "✅" if status == "PASS" else ("⚠️" if status == "WARN" else ("❌" if status == "FAIL" else "ℹ️"))
        print(f"{icon} [{status}] {msg}")

    if result.get("active_constraints"):
        print("\n📋 当前生效的用户反馈约束 (Feedback Ledger):")
        for c in result["active_constraints"]:
            print(f"  • {c}")
    for warning in result.get("ledger_warnings", []):
        print(f"\n⚠️  feedback ledger 解析失败，部分约束未生效: {warning}", file=sys.stderr)
    print("=" * 50 + "\n")

    if args.fail_on_fail and any(status == "FAIL" for status, _ in result["findings"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
