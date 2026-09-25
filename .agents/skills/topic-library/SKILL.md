---
name: topic-library
description: Maintain the personal topic library for @realchendahuang — one Markdown entry per topic under workspace/topics/ (YAML frontmatter + prose body), with lifecycle status and backlinks to its published posts. Use when the user hands over a topic ("记个选题", "这个选题存一下", "这周我想写这些"), asks what is still unwritten ("选题库还剩什么"), or says a topic got published, parked, or dropped. Do not use for raw ideas that are not yet topics (idea-capture), for angle/evidence work on one topic (topic-brief), or for drafting the post itself (post-drafter).
---

# Topic Library（选题库）

`workspace/topics/` 是选题的唯一台账：一条选题一个 Markdown 文件（YAML
frontmatter + 正文），契约见 `contracts/topic.schema.json`。它回答两个问题——**这条选题是不是已经提过**、
**哪些选题还没写**。

两层不要混：

| 层 | 位置 | 是什么 |
|---|---|---|
| 原材料 | `workspace/inbox/` | 用户原话的点子/观察，尚未成为选题 |
| **选题** | `workspace/topics/` | 一条决定要写/可能写的选题，带生命周期状态与回链 |

选题库不存证据、不存正文，只存"要写什么"和"写到哪一步"。证据与角度研判
在对话内完成（topic-brief），不落盘、不推进状态。

## 工作流

### 1. 用户给选题 → 存入

    python3 .agents/skills/topic-library/scripts/capture_topic.py \
      "Git Worktree 在 AI 并行开发里到底值不值得用" \
      --title "Git Worktree × 多 Agent 并行" \
      --pillar ai-coding-agents

参数按需给，不要为了填满字段去盘问用户：

- `statement`（位置参数）：**用户交付时的原话，逐字保留**，不润色、不扩写；
- `--title`：便于扫读和去重的短标签；省略时取 statement 首行截断；
- `--pillar`：`profile/content-pillars.md` 的规范 id，不确定就省略（存 `null`）；
- `--thesis`：**本人观点**，只有本人说过才填，否则留 `null`，不得代拟；
- `--source` / `--source-ref`：选题来自已有工件时（inbox 点子、signal、
  candidate）标明来源；用户直接给的一律 `user`（默认）；
- `--note`：补充说明。

命令打印保存路径与完整记录，向用户复述时用一句话讲清存了哪条。

**重复检测**：库中已有相同（或近似）选题时脚本拒绝写入，退出码 2，并在
stderr 指出已存在条目的 id、状态与文件路径。此时应告诉用户"这条已经在库里
了（`topic-...`，状态 X）"，并问是否推进那条，而不是新建。确认要作为独立
条目保留时加 `--allow-duplicate`。

### 2. 用户问库里有什么 → 列出

    python3 .agents/skills/topic-library/scripts/list_topics.py
    python3 .agents/skills/topic-library/scripts/list_topics.py --status candidate
    python3 .agents/skills/topic-library/scripts/list_topics.py --pillar ai-coding-agents --json

默认按状态分组、组内新→旧。摘要行的"未写"= candidate，
这就是当前待写队列（parked 是搁置备查，不在队列里）。

### 3. 选题推进 → 更新

    # 写完了、发出去了
    python3 .agents/skills/topic-library/scripts/update_topic.py \
      --id topic-20260919-153012-ab12cd34ef --status published \
      --post-url https://x.com/realchendahuang/status/2097730017417679038

    # 明确不写了（必须给理由）
    python3 .agents/skills/topic-library/scripts/update_topic.py \
      --id topic-20260919-153012-ab12cd34ef --status dropped \
      --dropped-reason "与 09-07 那条观点重复，没有新增量"

`--brief-id` / `--draft-id` / `--post-url` / `--note` 追加去重，重复运行结果
一致；字段无变化时打印 `unchanged` 且不写文件。

## 状态语义（方案 A 创作者看板）

| 状态 | 中文名 | 含义与定位 | 硬约束 |
|---|---|---|---|
| `candidate` | **待写库** | 主力待写队列，切角清晰，随时挑出来动笔 | |
| `parked` | **素材库** | 慢素材与长尾灵感，需要时再翻，不占日常视线 | |
| `published` | **已发布** | 已经发出，且已挂接实际推文链接闭环 | 必须有 `post_urls` |
| `dropped` | **已弃用** | 明确淘汰或排除的题目，防重复打扰 | 必须有 `dropped_reason` |

注：CLI 脚本支持直接传入中文名（如 `--status 待写库`、`--status 待写` 或 `--status 素材库`）。
两条硬约束同时写在 schema 的 `if/then` 里，由 `tests/test_contracts.py` 强制。
（`briefed`/`drafted` 已于 2026-09-24 随草稿文件流程一起退役：写作在对话
里完成，选题库只回答"提过没有"和"发了没有"。）

## 纪律

- **不代拟观点**：`thesis` 为 `null` 表示本人尚未表态，补充观点只能来自本人。
- **不改写原话**：`statement` 是原话；改写会把"用户要写什么"替换成"我以为
  用户要写什么"，之后无法回溯。
- **状态只往前推**：把选题标成 `published` 必须能指向真实帖子 URL；不确定就
  保持原状态，宁可少记一步也不要让台账说假话。
- **不把选题库当收藏夹**：`dropped` 也需要理由，理由是复盘时唯一能学的东西。
- 选题入库不触发搜索、不触发写稿；研判交给 `topic-brief`，写稿交给
  `post-drafter`，用户要求时才继续。
