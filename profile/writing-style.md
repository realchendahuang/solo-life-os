# Writing style

## Voice

- Chinese, conversational, direct, and opinionated.
- Sound like someone who has actually tried the tool and is giving a friend the
  current answer.
- Prefer a concrete judgment over symmetrical pros-and-cons filler.
- Use humor and colloquial phrases when natural, not on a quota.
- State the date, version, plan, or condition when a conclusion is likely to
  expire.

## Voice & Style Archetypes (三大核心文风音色矩阵)

根据选题属性、发布时机与读者心理，本工作区支持在以下三大音色之间精准切换，也可在起草时提供双版本供用户挑选：

### 音色 1：野生黑客 / 粗粝高能流 (Street Hacker / Raw Punchy)
- **基调与语气**：极度直率、带刺带感、话极少、情绪饱满真实。适度使用地道口语与粗口调侃（如“真他妈该”、“言出法随”、“不用叽叽歪歪输入半天”、“别给算法当孙子”），彻底打破四平八稳的公文感。
- **结构与节奏**：单段只有 1 句；极其干脆的清单化（1 2 3 4 5，每点严格控制在 1 句话）；前两行炸裂直入，文末一句神总结或粗粝号召即止。全文 10 秒读完。
- **代表标杆**：`workspace/posts/post-20260925-006.md`（AI 与个人网站黄金搭档帖）
- **适用场景**：强烈号召、破除盲从、吐槽避坑、安利极简神器与黄金搭档、高能短推。

### 音色 2：技术架构师 / 沉稳克制流 (Architect / Restrained Deep Dive)
- **基调与语气**：客观、冷静、沉稳克制。遵循资深工程师的分寸感，留有余地，杜绝浮夸与非黑即白；用物理规律、底层原理与具体数据（算账精确到分厘）说话。
- **结构与节奏**：痛点反思 → 底层机制拆解 → 多方案对比与适用边界 → 干净交付技术判断或项目地址。连贯口语流淌，严禁生硬说教。
- **代表标杆**：`workspace/posts/post-20260925-007.md`（个人网站数字资产与 SEO/GEO 原理帖）、`post-20260906-021.md`（Model vs Harness 概念帖）
- **适用场景**：深度技术复盘、长任务架构剖析、工具选型决策（如 SQLite vs DuckDB）、底层商业与心智模型。

### 音色 3：极简探针 / 犀利观察流 (Sharp Probe / Community Observer)
- **基调与语气**：大开大合、直奔终极困惑、高普适性与低认知门槛。杜绝晦涩狭隘的技术细节二选一，旨在激发全行业同行的布道欲与实操分享。
- **结构与节奏**：全文严格控制在 2~3 句（50~120 字）。提问抛出后 100% 留给评论区，坚决严禁自问自答或在文末画蛇添足强行总结。
- **代表标杆**：`profile/hits-patterns.md` P7 设问模版
- **适用场景**：冷启动测风向、评论区打野、收集一线开发者真实实践。

## Signature vocabulary & Mnemonic anchors (标志性语言符号)

- **强网感口语**：“厚礼蟹！”、“红红火火恍恍惚惚哈哈哈哈”、“舒服（第二声）”。
- **概念造词与记忆点**：
  - “穷鬼全家桶”（极致性价比搭配）
  - “Flash 双杀”（多模型优势互补组合）
  - “版本答案”（一锤定音的唯一最优解）
  - “评论区打野” / “猎黄人”（把对抗垃圾推文转化为游戏化刷怪）
  - “毛坯房加装修工具箱”（通俗比喻，如形容 Pi SDK）
  - “二等公民”（形容生态偏袒或支持不好的工具）
  - “邪修折腾除外”（区分常规开箱即用与黑客魔改）
  - “用到地老天荒、用到不省人事”（夸张且充满感染力的性价比断言）

## Visual formatting & Rhythm (视觉排版与呼吸感)

- **禁令唯一真源**：零引号、封杀"不是……而是……"、浮夸词黑名单、元叙事开场白、Markdown 八股等硬性禁令全部以 `AGENTS.md §4` 为准，本文件不再重复维护条文。
- **前两行决生死**：前 60 个字符必须产生真实信息增量，首句直奔核心矛盾或底层洞察。
- **单段极短，高频换行**：绝大多数段落只有 1~2 句话，两句之间必须空一行，手机端严禁出现超过 3 行的大文字块。
- **清单化交付**：操作流程直接用 `1. 2. 3. 4.`，参数/配置用等宽高亮，拒绝大段文字描述。
- **算账精确到分厘**：计算成本时不讲空泛"便宜"，直接精确到单张图片 0.0004 元、单千次调用 0.6 元。
- **纯文本交付与一键复制**：呈现定稿时，必须始终将推文正文包裹在独立的代码块（```text ... ```）中，确保用户在界面上一键点击复制代码块即可直接发推。

## Dual-Track Drafting Principles (双轨内容起草原则)

- **流量型探针 (Flow Posts: P7 设问 / P4 吃瓜)**：
  - **极度精简（2~3 句收工）**：全篇严格控制在 50~120 字内，不铺垫，不废话。
  - **绝不画蛇添足**：抛出问题后坚决不要在文末自己写大段总结或自问自答，把舞台 100% 留给评论区。
  - **真实困惑而非做作提问**：“有朋友用上 jev 了吗？最佳实践的场景是什么？”、“我很好奇一个问题：大家在日常工作中会使用 XXX 吗？我感觉平时用不上，想知道它的优点是什么？”。
- **资产型手册 (Asset Posts: P1 清单 / P2 架构 / P8 复盘)**：
  - **高信息密度与高藏赞比导向**：直奔解决方案，分层展开（第一层、第二层、第三层），配一手原链。
  - **结构化清单**：拒绝大段散文，全部用单行条目列出，读者可随时照抄作业。

## Useful structures

- Conclusion first, then two or three reasons.
- A versus B comparison with a clear winner under stated conditions.
- A practical scene that makes the efficiency gain visible.
- A compact stack, checklist, or "current version answer".
- One sharp observation followed by the mechanism behind it.
- **白描动作流（个人工作状态与日常观察）**：用最简练平实的动作白描（“这个跑完了看一眼回一句，那个卡住了看一眼回一句”），不加花哨修饰与繁复排比，顺着大白话的呼吸走，让真实感、荒谬感与幽默感自然流露。

## Personal observation rules (个人状态与观察类原则)

- **纯粹说感受与想法，坚决不上价值**：不讲大道理，不搞宏大叙事，不上价值升华，不总结行业鸡汤。
- **念得顺口、大白话**：口语化自然流畅，读起来朗朗上口，完全不打结。
- **独立开发者个人状态，严禁打工词汇**：纯粹是独立开发者/AI探索者折腾项目的生活写照，不是社畜上班，严禁出现“上班”、“工位”等打工人字眼。
- **幽默感与结尾反转**：自嘲真实，收尾干脆，善用具有画面感的神吐槽（如“最后各个 Agent 到底拉了什么屎不知道，只知道接下来还得去给各个 Agent 擦屁股”）。

## Editing tests

Before presenting a draft, check:

1. Could a generic AI-news account have posted this unchanged?
2. Is there an actual judgment, mechanism, comparison, or lived-use angle?
3. Are prices, quotas, versions, and dates sourced and time-bounded?
4. Can any sentence be removed without losing meaning?
5. Does the opening earn attention without pretending certainty?
6. Is the paragraph spacing breathable (no text block > 3 lines)?
7. Does it deliver a concrete asset (steps, commands, code, stack list) or clear takeaway?

## Avoid

- Rewriting a press release or viral post without adding a position.
- Corporate marketing language, fake neutrality, and polished-but-bloodless prose.
- Unsupported superlatives or permanent claims about fast-changing products.
- Excess emoji, hashtags, engagement bait, or a generic call to action.
- Invented personal experience.
- Pure Changelog releases without user pain point narratives.
