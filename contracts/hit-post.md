# Hit-Post Contract（精华帖/发布档案字段契约）

`workspace/posts/` 下每个 Markdown 档案文件的字段规范。这是 CSV 报表和
模式提炼脚本读取的事实源。契约文档（本文件）用于人与 AI 对齐字段含义；
`frontmatter.validate_post()` 在写入前按本契约校验必填键、未知键与类型
（stats 等只读脚本不校验，坏文件跳过并报告）。

## 文件名

- 历史高赞帖：`hit-YYYYMMDD-NNN.md`（`archive_hit.py` 手工入库）或
  `hit-site-YYYYMMDD-NNN.md`（`import_from_site.py` 站点导入）
- 新近发布帖：`post-YYYYMMDD-NNN.md`
- 一律为 Markdown，正文 = 帖子原样全文
- **文件名里的日期是入库/采集日，不是发布日。** 档案里有大量补录帖（例如
  `post-20260918-001.md` 实际发布于 2026-09-12），所以任何按时间的筛选都必须
  读 `posted_at` 字段，禁止用文件名日期过滤。`stats.py --since/--until` 已改为
  把 `posted_at` 折算到 Asia/Shanghai 后比较日期。

## YAML frontmatter 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| id | string | 是 | `hit-YYYYMMDD-NNN`、`hit-site-YYYYMMDD-NNN` 或 `post-YYYYMMDD-NNN`，与文件名一致。前缀必须与 `kind` 匹配：`kind: hit` 用 `hit-`/`hit-site-`，`kind: published` 用 `post-`（`validate_post` 拒绝不一致的组合；否则 `stats.py --kind hit` 会把自家帖统计进标杆集合） |
| kind | enum | 是 | `hit`（历史高赞标杆）/ `published`（自己新发的复盘对象） |
| post_url | string | 是 | X 帖子 URL，形如 `https://x.com/…/status/<numeric id>`（必须是真实数字 ID；仅显式 `--no-url` 时可为空） |
| collected_at | date-time | 是 | 入库时间（Asia/Shanghai） |
| posted_at | date-time | 否 | 帖子发布时间（未知可省略；可带 `Z` 或时区偏移） |
| channel | enum | 否 | `intent` / `buffer` / `unknown`（历史帖默认 unknown） |
| draft_id | string | 否 | 松散备注（2026-09-24 起草稿文件已退役，写作在对话里完成；可传可不传，不再校验） |
| pillar | string | 否 | 内容支柱。新写入建议用 `profile/content-pillars.md` 的稳定 id（`ai-coding-agents` / `indie-dev` / `ai-productivity` / `insight-income` / `language-learning`）；历史档案里的 `AI实战` 等写法仍可读，不强制回改 |
| tags | array | 否 | 标签列表，如 `[AI实战, CodingAgent]` |
| structure | string | 否 | 结构形式：`opinion` / `list` / `story` / `thread` / `quote` |
| hook | string | 否 | 开头钩子句原文 |
| metrics | object | 否 | 见下表 |
| verdict | enum | 否 | `good` / `meh` / `bad`（复盘结论，只有复盘批注后才填） |
| source | string | 否 | 入库来源，如 `chendahuang.com/mirror`、`chendahuang.com/highlights`、`socialdata`、`x-fetch`。历史值 `grok-profile-analysis` 保留在既有档案里（Grok 通道 2026-09-19 移除），新写入不再产生该值 |
| site_title | string | 否 | 站点导入时的标题（`import_from_site.py` 的 highlights 页） |
| in_reply_to_status_id_str | string | 否 | 被回复帖的 status id（SocialData 导入的回复帖） |

## metrics 对象

| 键 | 类型 | 含义 |
|---|---|---|
| views | int | 浏览量 |
| likes | int | 点赞数 |
| reposts | int | 转发数 |
| replies | int | 回复数 |
| quotes | int | 引用数 |
| bookmarks | int | 收藏数（本账号的核心资产信号，报表与模式提炼都读） |
| link_clicks | int | 链接点击数 |

全数字可选填，未知的键省略即可。同一帖子可多次回采，覆盖写入时在
`## 数据回采` 小节追加一行窗口记录（时间、**窗口标签**、来源、数字），
frontmatter 保留最新值。上游没有返回某项指标时省略该键，绝不写入 0 占位
（`backfill_metrics.py` 对全零快照直接跳过并报告）。

## 正文结构

```markdown
---
<frontmatter>
---
<帖子全文原样>

## 我的批注
（复盘时的思考：为什么好/为什么差，预留空节）

## 数据回采
- 2026-09-05 24h: views=51200 likes=842 reposts=119
```

## 约定

- 正文永远原样保留，AI 不改写；“为什么”写在批注节。
- 模式提炼（profile/hits-patterns.md）只引用 frontmatter + 批注，不重抄全文。
- 一个 status id 只允许一条档案（唯一性）：`record_post.py` /
  `archive_hit.py` 按 `post_url` 里的数字 ID 去重，重复入库直接拒绝并打印
  已有文件路径；改用已有文件回采/补写，不要新建第二条。
- 真实 URL 规则：除非入库时显式用了 `--no-url`（此时 `post_url` 为空，
  脚本会在输出里说明），`post_url` 必须是真实可访问的 status URL；不得用
  `--text` 绕过 URL 校验。
- draft_id 规则（2026-09-24 更新）：草稿文件工作流已退役，`--draft-id` 只是
  松散备注，任何值都接受且不再对照文件校验；发布来源用 `--topic-id` 关联
  选题即可。`--no-draft` / `--allow-unknown-draft` 已随之下线。
