---
name: x-fetch
description: 抓取 X 上具体推文、回复、用户时间线、搜索结果、X Lists/Articles 作为可核验的证据文本（免登录、免 API key、纯 Python 标准库）。用于把用户给的链接、idea-capture 条目或历史 signal 里的 X 链接抓成原文证据，再交给 topic-brief。Do not use for 趋势发现或话题扫描：本仓库自 2026-09-19 起没有任何 agent 侧热点发现通道，把 x-fetch 当搜索引擎用是误用（它只能抓指定对象，且搜索/时间线后端未部署）。The runtime is vendored from ythx-101/x-tweet-fetcher (MIT).
---

# x-fetch

从 X 抓取具体内容作为证据。本地 vendor 自
[ythx-101/x-tweet-fetcher](https://github.com/ythx-101/x-tweet-fetcher)（MIT），
零第三方依赖，免登录、免 API key。

## 能力与后端依赖

| 能力 | 命令 | 依赖 |
|---|---|---|
| 单条推文（正文、互动数、媒体） | `--url <URL>` | 无（零依赖） |
| 推文回复（threaded） | `--url <URL> --replies` | Nitter 或浏览器 |
| 用户时间线 | `--user <name> --limit N` | Nitter 或浏览器 |
| 搜索 | `--search "<query>" --limit N` | Nitter |
| 用户资料 | `--user-info <name>` | 无（零依赖） |
| X 列表 / X Articles | `--list / --article` | 浏览器（Camofox/Playwright） |

默认后端 `auto`：优先 Nitter，抓不到再走浏览器。

**Nitter 这条路已经永久关闭**（2026-09-19 核实）：X 于 2026-08-24 向 Nitter
发出停止函，要求永久下线实例与代码仓库，仓库已于 2026-09-11 归档，作者停止
开发。不要再去部署 Nitter 实例——那不是"还没部署"，而是已被法律手段终结。

因此本机现状是：单条推文抓取随时可用（走 FxTwitter）；搜索、时间线、回复
需要 Nitter 或浏览器后端，
- 浏览器后端需要 Camofox（`localhost:9377`）或 Playwright，本机都没装；
- 但这些能力可以改用你已登录的真实浏览器完成（Kimi WebBridge 路径），
  实测可读到实时搜索结果的作者/正文/时间/互动数。

## 本地补丁（X-Tiller）

vendored 运行时带有以下本地补丁，每个改动点都在源码中以
`# local patch (X-Tiller): ...` 标注：

- 单帖抓取会校验上游返回的 tweet id 与作者 handle；不一致（镜像缓存/重定向）
  直接按 `upstream_down` 失败，绝不把别的帖子当成请求的那条写进 ledger。
- `--limit` 上限 200；未显式指定时按模式取默认（时间线 50、monitor 10），
  显式 `--limit 50` 不会再被静默降级。
- `--timeout` 现在真正贯通到各后端（默认 30；浏览器页等待随之调整）。
- Nitter 分页之间默认 sleep `--page-delay`（1.0s），回复递归抓取默认上限
  `--max-reply-recursion`（20 页）。
- JSON 输出新增 `metrics_present`（上游实际返回的指标键，已排序）以及
  仅新增 `views_unknown: true` 标记；`views`、`metrics` 等既有字段不变。
  Nitter/snapshot 路径浏览量无法测得时给出 `views_unknown`，不会把 0 冒充实测。
- `views_supplemented` 现在是实际补齐的条数（另附
  `views_supplement_requested`），不再是恒为 true 的布尔值。
- `--text-only` 输出末尾带 `URL: <canonical url>`；既无正文也无 Article
  全文时以 `error_code: empty_tweet` 退出 1，不会空 stdout 地 exit 0。

## 用法

```bash
# 单条推文（最常用，零依赖）
python3 .agents/skills/x-fetch/scripts/fetch_tweet.py \
  --url https://x.com/<user>/status/<id> --text-only

# JSON 输出（保留全部元数据，供结构化消费）
python3 .agents/skills/x-fetch/scripts/fetch_tweet.py \
  --url https://x.com/<user>/status/<id> --pretty

# 归档到本地账本（去重，schema 与 OpenClaw tweet-ledger 兼容）
python3 .agents/skills/x-fetch/scripts/fetch_tweet.py \
  --url https://x.com/<user>/status/<id> --ledger /path/to/ledger.db

# 评论区精华收割（三级火箭二级：自动滚动、智能去噪、提取高赞回复与结构化证据）
python3 .agents/skills/x-fetch/scripts/harvest_replies.py \
  --url https://x.com/<user>/status/<id>
```

## 纪律

- 免 API 抓取有账号风控风险：低频、targeted 使用，不批量扫。
- 抓取结果是信号/证据，不是已核验事实；引用时保留原 URL。
- 不把抓取内容直接当发布文案，交给 topic-brief / post-drafter 处理。

## 失败行为

- 输出带 `error_code`（`not_found` / `rate_limited` / `upstream_down` /
  `backend_unavailable` / `all_backends_failed`，失败时多后端附各自原因）。
- 后端全部失败时如实报告错误，不编造抓取结果。
- 关闭一个过于宽泛的查询一次；不要无限重试。

## Output boundary

只输出抓取到的原文、互动数据和元数据。不生成选题、不写帖子。