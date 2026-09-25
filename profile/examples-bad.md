# Rejected patterns

This file is the durable home for examples the user rejects and the reason for
each rejection. Entries come from `workspace/feedback/ledger.jsonl` — the
user's own words, dated — and are promoted here only after the user confirms the
general lesson. post-drafter reads this file before drafting.

## 2026-09-03 — draft-20260903-code-mode

**User's words:** `Too long, do not include code snippets in X posts`

**Constraint recorded:** Focus on value and mental model, keep it short and
punchy for X, attach only a single URL.

**Lesson:** a post explains the idea, it does not ship the implementation. Code
blocks, multiple URLs, and length all compete with the judgment the post exists
to deliver.

## 2026-09-03 — draft-20260903-code-mode

**User's words:** `User rejected the Playwright attach fill flow as unreliable (timeouts)`

**Constraint recorded:** Publishing flow must be deterministic, no browser
automation; clipboard + manual Cmd+V + user clicks Post.

**Lesson:** this one is about the tooling, not the copy — but it is binding on
every future publish proposal. Do not reintroduce scripted browser filling for
the publish path.

## 2026-09-08 — draft-20260908-media-formats

**User's words:** `开头缺少钩子不容易吸引人`

**Constraint recorded:** 开头必须有抓人注意力的钩子.

**Lesson:** the first line carries the whole post. A correct-but-flat opening
("关于音频和图片存储格式，我最近有一些想法") loses the reader before the
judgment arrives. Compare the openings in `examples-good.md`: each one either
names a surprising fact or states a verdict.

## 2026-09-08 — draft-20260908-media-formats

**User's words:** `不要从独立开发者角度切入`

**Constraint recorded:** 通用视角：任何人想自己存储音频图片，兼具体积兼容性效果的最佳方案.

**Lesson:** not every post should be framed through the owner's own workflow. When
the topic is a general "what is the best option for anyone" question, an
I-build-things framing narrows the audience and buries the answer.

## 2026-09-21 — draft-20260921-ai-时代的开源硬核科普

**User's words:** `正文严禁使用双引号“”等任何引号，不要引号修饰，改用直接陈述` / `语气过冲、戏剧化词汇和教训感过重：严禁使用把概念掰扯清楚、满天飞、更要命的是、商业缰绳、当头一棒、更致命的是、系统疯狂、怀疑人生等夸张煽动性词汇`

**Constraint recorded:** 严禁使用任何引号；禁用自媒体夸张词汇，保持客观、克制、沉稳的工程师事实陈述。

**Lesson:** quotation marks on concepts read as sarcastic, defensive, or preachy; emotional drama words read like marketing clickbait. A senior engineer explains bandwidth, cache, and swap mechanisms calmly.

## 2026-09-21 — draft-20260921-反思纳瓦尔宝典

**User's words:** `坚决不要分点（1. 2. 3.），分点太机械呆板` / `彻底封杀‘不是……而是……’这种辩论腔、说教腔、AI味道极重的傻逼对仗句式` / `严厉禁止任何过度夸张、绝对化词汇（如‘死磕代码’、打穿、壁垒等伪概念与夸张修辞）`

**Constraint recorded:** 坚决杜绝“不是……而是……”对仗句；严禁机械分点；说话留有余地、平实朴素克制。

**Lesson:** "不是……而是……" is the single biggest AI tell. It forces false dichotomies and sounds like an internet debater. Plain prose that admits trade-offs and complexity always beats forced antithesis.

## 2026-09-23 — draft-20260923-local-first-选型排除法

**User's words:** `严禁在正文出现'大白话'等元叙事或居高临下的说教词汇` / `结构化痕迹过重、像AI生成的死板提纲列表，缺乏个人色彩；坚决去除业务使用场景、开发者选型考量等模板化死板小标题`

**Constraint recorded:** 严禁“大白话”、“科普一下”等元叙事口头禅；坚决去除模板化小标题与死板提纲，以自然流淌的个人体验展开。

**Lesson:** AI instinctively generates boilerplate report templates (【业务场景】、【选型考量】). Real practitioners write in a natural conversational rhythm with progressive context (pain point → mental model → tool specifics).

## 2026-09-23 — draft-20260923-agent长期记忆选型设问探针

**User's words:** `你这个问题说的太局限了。你应该说的是：这种大模型的记忆系统，到底什么样才是最佳实践？你应该说这个，懂吗？或者说，你弄一个开放性的问题。你踏马说得太局限了，让人都难以理解。`

**Constraint recorded:** 设问探针必须大开大合、开放普适、直击本质与最佳实践；严禁陷入具体狭隘的技术细节二选一，造成理解门槛。

**Lesson:** P7 设问探针的核心目的是用极低门槛激发全社区开发者的布道欲。一旦问题里塞满晦涩狭窄的具体架构细节（如“异步提取事实 vs 全量保留日志”），读者看不懂或者懒得思考。提问必须直奔终极困惑（“这种大模型记忆系统到底什么样才是最佳实践？”、“大家体感最顺手的方案是什么？”），把具体的架构细节留给评论区去争论和补充。

## 2026-09-24 — direct-dialog-premature-sync

**User's words:** `我觉得你每次没必要直接写到线上去。你应该先发给我，我确认以后，你再写到线上去，懂了吗？你应该先发给我，不要随便写。你妈写好了直接发给我，别同步啊，你傻逼吧你，我操了。你只需要写，写完发给我就可以了。 你不要每次都同步。为什么要同步呢？我都没确认的东西，你同步进去有什么价值呀？你把整套流程再给我简化一下，怎么回事？你妈的，搞那么复杂。`

**Constraint recorded:** 写稿改稿阶段 0 线上同步、0 Git 推送；纯粹交付对话框文本与剪贴板；严禁在确认前执行 Git 推送；只有用户明确确认并已发布后才允许归档入库与执行同步。

**Lesson:** Premature synchronization is harmful noise. An unapproved draft is purely an in-chat scratchpad. Running git pull/rebase/push or any remote write during drafting creates latency, pollutes the repository, and wastes user attention. The workflow must be streamlined to two dead-simple steps: 1) Agent writes/edits in chat, zero online side-effects; 2) User publishes on X, then the confirmed result is archived into the plain-text files.

## 2026-09-23 — draft-20260923-jev-落地最佳实践与避坑复盘

**User's words:** `严重过度浓缩，丢失了评论区大量的真实案例、具体项目、参数数据与不同阵营的丰富细节。要求详尽盘点，把评论区涌现出的具体实践、项目和体感全景式呈现` / `要求具体点名并@对应推特ID，把谁讨论的什么观点与项目逐一精确对标，增强真实感与同行互动`

**Constraint recorded:** 复盘评论区必须详尽盘点全部真实案例与具体项目（推特打分插件、微信悬浮窗、问卷重构、德州打牌、脚本风控等），保留硬核信息增量（Vercel 免排队、0.0036 美元测试花销）；观点与项目逐一 @ 到真实推特账号。

**Lesson:** 评论区复盘帖的价值就在具体性和真实性。把 30 条鲜活回复压成一句"大家反馈不错"，等于把信息增量全部扔掉。谁讨论了什么观点、做了什么项目，要精确到真实推特 ID 逐一呈现。

## 2026-09-23 — draft-20260923-local-first-选型排除法（衔接）

**User's words:** `上下文衔接生硬割裂，从痛点描述突然生硬跳跃到'所谓的Local-First'名词概念，缺乏自然的承上启下与思维过渡`

**Constraint recorded:** 痛点与概念名词之间必须建立丝滑自然的思考转折，顺理成章引出为什么大家要转向本地优先，杜绝生硬概念切入。

**Lesson:** 口语化叙事不是把术语直接砸出来。读者跟着作者的思考路径走：先感受到痛，再自然生出"是不是该换个思路"的疑问，概念这时候登场才顺理成章。

## 2026-09-23 — draft-20260923-agent长期记忆演进谱系与无损原木反思（rejected）

**User's words:** `文章完全缺少真实技术调研，充斥抽象概念与过时方案。必须深度调研OpenAI、Anthropic、Hermes、OpenClaw等一线机构与前沿开源项目的真实记忆系统实现与最佳实践，用扎实具体的案例说话。`

**Constraint recorded:** 写架构和系统对比前必须深入调研顶流工业界与开源标杆的真实实现，严禁用抽象虚浮的旧八股糊弄。

**Lesson:** 读者是一线开发者，凭印象编造抽象演进谱系会被一眼看穿。写系统类内容前先去把真实实现翻一遍，用具体的项目名、机制、参数说话。

## 2026-09-25 — draft-20260925-taro5-cpp-react

**User's words:** `这些话、这种语气，以后不要说，你给我记住。：把手术刀直接动到了系统底层，直接掀了桌子，非常纯粹。`

**Constraint recorded:** 坚决杜绝“动手术刀”、“掀桌子”、“非常纯粹”等戏剧化夸张、自媒体煽动与空洞修辞，保持客观、平实、克制、沉稳的工程师事实陈述。

**Lesson:** 工程师写技术选型和架构分析，靠客观物理机制、数据和真实场景打动同行，绝不能滑入科技自媒体的夸张煽动套路。把动手术刀、掀桌子、非常纯粹这类戏剧化词汇彻底剔除。

## 2026-09-25 — topic-20260922-001351-46a38ec52e

**User's words:** `不要在后面强行加一个提问的设问，太他妈傻逼了，跟你妈 AI 一样。`

**Constraint recorded:** 严禁在文末机械或强行追加提问设问求互动。技术沉淀与项目推荐类推文收尾要干净利落，直接交付完技术判断或项目链接即止。

## 2026-09-25 — topic-20260919-131450-e4c68ef28a

**User's words:** `我觉得你说的太局限了，你局限在开发了。还有一个体面交付的核心，就是说很多人的学习能力不够，或者说需要有一个人能领进门，领进门了以后呢才能不断的去学习。因为你一开始的时候万事开头难，你要是自己凭着各种各样的东西你去搭建的话，是非常非常困难。但是你如果你快速的付费，然后快速的学习，知道行业内的一些 know how 你就能够快速的去入门，这也是一种能力。所以说花钱的话，知识付费它就是买的一种权。进行一种时间上的节省，所以说你要好好的帮我把这一套东西好好重新捋捋，不仅是在写代码，不仅是做独立开发，而是所有的知识付费，你都给我好好写`

**Constraint recorded:** 商业、方法论与变现逻辑探讨必须具备全行业通用视野，严禁狭隘局限于写代码与独立开发圈子；核心价值聚焦冷启动破冰（领进门跑通闭环）与买断一线实操 know-how（用钱换时间），花钱买确定性与效率本身是一种高维能力。

**Lesson:** 探讨商业与交付本质时，不要自说自话地把场景本能缩回技术人员或程序员的小圈子里。各行各业的新手都有极强的冷启动焦虑和信息过载，愿意付费买的是别人的一线实战门道（know-how）和带进门的确定性，以小额学费买断数月摸索试错风险，这是普适的商业法则。

## Recurring constraints (repeated feedback only)

- **Zero quotes**: Never use Chinese double quotes “”, single quotes ‘’, or English double quotes "". State terms directly.
- **No '不是……而是……'**: Ban forced antithesis and debate rhetoric.
- **No theatrical jargon**: Ban "死磕", "打穿", "跌到地平线", "核心壁垒", "当头一棒", "更致命的是", "系统疯狂", "怀疑人生", "动手术刀", "掀桌子", "非常纯粹". Speak with calm, grounded engineering nuance.
- **No meta-narration or cold openings**: Cut "刚才发完", "顺便琢磨了一下", "今天聊聊", "大白话讲", "科普一下". The opening must earn attention with a direct insight or pain point.
- **Pure text, no outline slop**: No Markdown headings (`###`), bold (`**`), or divider lines (`---`). No boilerplate headings like "业务使用场景".
- **No self-answering in probe posts and keep questions open**: P7 probe questions must stay under 2–3 sentences. Questions must be open and universal ("到底什么样才是最佳实践？"). Never box the audience into narrow, jargon-heavy binary choices that confuse readers. Let the community provide the answers.
- **No forced ending questions**: Ban mechanical engagement-farming questions ("大家怎么看？", "大家踩过哪些坑？") at the end of tech posts. End cleanly on the insight, conclusion, or project link.
- **Comment-recap posts must stay concrete**: 复盘评论区要全景式盘点真实案例与具体项目，观点精确对标到真实推特账号（@ID）；严禁过度浓缩成抽象概况。
- **Smooth concept transitions**: 痛点场景到新概念名词之间要有顺理成章的思维转折；严禁生硬甩术语。
- **No unresearched abstractions**: 写架构/系统对比前必须调研一线标杆的真实实现；严禁抽象概念与过时方案糊弄。
- **Commercial & methodology discussions beyond coding**: 探讨商业模式与交付方法论时严禁狭隘局限于写代码圈子，直击冷启动破冰与买断时间杠杆的跨领域常识。
- **No large code blocks**: 严禁正文粘贴大段代码块或长配置文件。推文只交付心智模型与架构决策，实现细节放链接或仓库。
- **No link bombing**: 单篇推文严禁超过 1 个核心链接，防算法降权与阅读混乱。
- **Zero premature sync during drafting**: Never run `sync.py` / git push while drafting. Just output the draft into chat. Sync only after explicit user confirmation/publishing.

## Adding entries

- Date and draft id
- Draft excerpt or artifact path
- Rejection reason in the user's own words
- General lesson — only when supported by repeated feedback, never inferred from
  one silent rejection
