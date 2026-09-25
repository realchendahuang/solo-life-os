---
name: hit-archive
description: Build and maintain the personal post archive for @realchendahuang — historical high-performing posts to learn from, plus every published post for review. Archive files are Markdown with YAML frontmatter (contracts/hit-post.md); stats are CSV reports. Use when the user says "把这个帖子收进精华库", "入库", "看看我哪些帖子数据好", or asks to learn from past posts.
---

# Hit Archive（精华帖库 + 发布档案）

`workspace/posts/*.md` 是**唯一事实源**：一篇帖子一个 Markdown 文件，
frontmatter 存结构化字段（指标/标签/结构/钩子），正文存帖子全文，批注节
存复盘思考。统计靠脚本扫目录生成 CSV，不维护任何重复台账。

阅读 `contracts/hit-post.md` 了解全部字段。**正文永远原样保留，不重写。**

## 主页补录（已停止：原 Grok 通道）

`grok_profile_analysis.py` 与 `sync_from_profile.py` 已于 2026-09-19 随 Grok
通道一起移除（额度消耗过高，用户决定不再使用 Grok）。`workspace/research/`
里既有的 `grok-profile-*.json` 保留为历史资料，但其中未入库的帖子不再由
仓库脚本补录：

- 补历史帖用站点镜像 `import_from_site.py --mirror`（覆盖 2026-06-15 起）；
- 单条补录用 `archive_hit.py --url`（x-fetch 取原文与指标）；
- 更早的全量历史仍走 `socialdata_history.py`。

既有档案里的 `source: grok-profile-analysis` 是历史来源标注，不要据此重跑。

## 站点同步（chendahuang.com，第二事实源）

个人站有两种增量导入，都按 post_url 去重、可随时重跑：

    # 精选 highlights 页（kind: hit，带站点标题与近似指标）
    python3 .agents/skills/hit-archive/scripts/import_from_site.py

    # /mirror.json 全量镜像：所有帖子原文 + 实时指标（kind: published），
    # 用于把"每一篇已发帖"补齐成完整基线（含低互动日常帖）
    python3 .agents/skills/hit-archive/scripts/import_from_site.py --mirror

站点抓的指标是取整近似值，需要精确值时对目标帖跑
`backfill_metrics.py --url`（x-fetch 校准）。

## 全量历史回填（SocialData，付费，按条计费）

`chendahuang.com/mirror.json` 只覆盖 2026-06-15 之后的帖子。补全更早的
全部历史用 SocialData（socialdata.tools，read-only X 数据代理，
$0.20/1000 条，游标分页可翻到账号最早期，返回含 `views_count` 曝光量，
X 官方档案导出没有）：

    # 1) 全量拉取原始数据（可 --continue 断点续传，失败请求不扣费）
    python3 .agents/skills/hit-archive/scripts/socialdata_history.py --fetch

    # 2) 增量入库（默认跳过纯转发和回复，保基线干净；--include-replies 收回复）
    python3 .agents/skills/hit-archive/scripts/socialdata_history.py --import

API key 放 env `SOCIALDATA_API_KEY` 或 `~/.socialdata_key`（绝不入仓库、
不进日志）。5.6k 帖全量约 280 页、成本约 $1.1。

## 三种写入操作

1. **历史精华帖入库**（学别人的/自己的高赞帖）：

       python3 .agents/skills/hit-archive/scripts/archive_hit.py \
         --url https://x.com/realchendahuang/status/123 \
         --tags AI实战,CodingAgent --structure opinion --pillar AI实战

   `--url` 必须是带数字 status id 的真实 X 链接；x-fetch 抓回的正文会自动
   去掉 `@handle:` 前缀和尾部 `点赞: …` 统计行，只入原样全文。确实没有
   链接时才用 `--text --no-url`（此时 `post_url` 为空、无法按 status id
   去重，脚本会在输出里说明）。`--list-file urls.txt` 批量时同样校验每条
   URL。已入库的 status id 会被跳过并打印已有文件，不会重复建档。
   `--dry-run` 只打印计划不落盘。入库后补 `--metrics` 或复查时回写。
   文件名 `hit-YYYYMMDD-NNN.md`（站点导入的走 `hit-site-YYYYMMDD-NNN.md`，
   见上文站点同步）。

2. **新发帖记录**（发布闭环的另一半，发布后调用；批次对齐时也用它）：

       python3 .agents/skills/hit-archive/scripts/record_post.py \
         --url https://x.com/.../status/123 --channel intent \
         --topic-id topic-20260923-083721-uqg39 --text "正文全文"

   发布通道（intent/buffer）记录在 `channel` 字段。同一个 status id 只允许
   一条档案：重复 `--url` 会被拒绝（退出码 2）并打印已有文件路径。
   `--draft-id` 自 2026-09-24 起只是松散备注（草稿文件已退役，写作在对话
   里完成），可传可不传。`--dry-run` 只打印将写入的文件。
   加 `--topic-id` 时，同一次调用会把选题库里的对应条目推进到 `published`
   并写入 `post_urls`。published/dropped/parked 的选题保持原状态不动，
   只补回链。不想动选题库时传 `--no-topic`。批次对齐官网导出数据时，
   逐条传 `--topic-id`（或后续用 `update_topic.py` 批量回填）。

3. **指标回采**（发布后 24h/7d）：通过 x-fetch 实抓最新互动数，更新
   对应 archive 文件的 `metrics`，并在 `## 数据回采` 追加一行带时间戳和
   窗口标签的快照记录（抓取失败不编造）：

       python3 .agents/skills/hit-archive/scripts/backfill_metrics.py \
         --url https://x.com/.../status/123 --window 24h

   上游没返回的指标直接省略，全零快照视为"没抓到"并跳过（不写 0 占位）；
   x-fetch payload 带 `metrics_present` 时只合并它列出的键。窗口标签默认
   `backfill`，按 weekly-review 的窗口命名（1h/24h/7d/30d）更可比。
   `--dry-run` 打印计划变更不写盘。批量校准（`--all` 按 kind 遍历，1s/条
   限速，rate_limited 即停，结束打印 changed/skipped/failed 汇总）；
   `--sync-text` 把档案正文与 x-fetch 原样全文对齐（历史档案里由 Grok 主页
   分析或站点摘要落库的正文可能是压缩文本，用本参数校准为原样全文）——
   它批量重写正文，务必先 `--dry-run`：

       python3 .agents/skills/hit-archive/scripts/backfill_metrics.py \
         --all --kind published --sync-text --dry-run

   人工细窗口快照（带 window/来源）走 weekly-review 的 record_metrics.py，
   字段同 metric-snapshot 契约。

## 统计与报表

    python3 .agents/skills/hit-archive/scripts/stats.py \
      [--kind hit|published] [--since 2026-09-01] [--until 2026-09-10] [--top 5]

生成 `workspace/stats/posts-<ts>.csv`（表头即契约，含 bookmarks/source），
打印摘要（帖数、views/likes 均值、top），并在 stderr 打印一行数据覆盖度
（pillar/structure/hook/verdict/draft_id 的填写比例）——这些字段没填，
模式提炼就没有可比维度。`--since`/`--until` 按 Asia/Shanghai 本地日期过滤
（`posted_at` 里的 UTC/`Z` 时间会先换算，避免把北京时间凌晨发的帖滤掉）。
坏文件（YAML 解析失败/无 frontmatter）会跳过并在 stderr 列出，不中断报表。
CSV 是派生报表，随时可重新生成，不手工编辑。

## 模式提炼（闭环的核心）

1. 统计找到数据好的帖子（高 views/likes/bookmarks，或与 draft_id 关联的
   发布复盘），并看 stderr 的覆盖度：pillar/structure/hook/verdict 没填
   的帖先补字段，否则模式提炼只是拍脑袋。
2. 逐帖写 **批注提案**（不是脚本自动生成）：读原帖 + 指标，给出
   "为什么这条值得学 / 为什么它能爆"的 1-2 句判断草案，连同依据（指标、
   结构、钩子）交给用户；用户批准后才写入该文件的 `## 我的批注` 节。
   批注推进 `verdict` 时一并回填 frontmatter。
3. 对比 frontmatter + 批注，归纳：主题（pillar/tags）、结构、钩子、时长、
   通道——找出"哪些组合对这个账号有效"。
4. 产出草案写入 `profile/hits-patterns.md`，**必须用户批准后才落盘**。
5. post-drafter 写稿时读取 hits-patterns.md 作为风格与选题基准。

> 现状提醒：`workspace/posts/` 里大量文件仍是占位批注
> `（为什么这条值得学/为什么它能爆？）`，批注未写就是模式提炼的证据缺口；
> 优先给高数据帖补批注。

**字段批量回填**：pillar/structure/hook 覆盖度低时，可以先用脚本把能从
标题与正文稳定推断的字段补上（它**不会**写批注判断——批注仍必须人工提案）：

```bash
python3 .agents/skills/hit-archive/scripts/tag_hit_posts.py --top 50 --dry-run
python3 .agents/skills/hit-archive/scripts/tag_hit_posts.py --top 50
```

先看 `--dry-run` 的预览再落盘；它批量重写档案正文之外的 frontmatter，
改动前建议先 `git status` 确认工作区干净，便于 `git diff` 复核。

## Rules（纪律）

- 正文原样，AI 不改写；分析只进批注节和模式文件。
- 一个 status id 一条档案：重复 `--url` 入库被拒绝，用已有文件回采指标，
  不要新建重复条目；`post_url` 必须是真实数字 ID 链接（仅显式 `--no-url`
  可为空）；新发帖必须有可解析的 draft_id，缺草稿才用 `--no-draft`。
- 不把原始帖（全文）放进 profile/；profile 只放提炼结论 + 少量精选样例。
- 不手工编辑 CSV；改数据就改 archive 的 frontmatter，再重跑 stats。
- `workspace/posts/` 是唯一事实源并随仓库版本控制（`.gitignore` 只忽略
  workspace 下的其他运行数据）；模式文件进 git。
- 指标数字来自用户回采或可验证源，不编造；窗口必须标注，全零/缺失指标
  不写 0 占位。