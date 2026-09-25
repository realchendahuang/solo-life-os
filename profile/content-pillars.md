# Content pillars

The order below is the default scanning and ranking priority. A direct user idea
always outranks this list.

Each pillar has a stable id. The id is the canonical joining key: new artifacts
that need a machine-readable pillar should use it, starting with
`possible_pillar_id` in `contracts/idea.schema.json`. Existing artifacts use
several other vocabularies (`AI实战`, `independent-developer-stack`,
`AI productivity and ways of working`, registry pillar names); those stay
readable and migrate only when a file is next touched.

## P0: GitHub 仓库专题与知识沉淀

- id: `github-repos`
- 专有定位：以个人与团队自研、维护的 GitHub 开源仓库为物理真源与知识沉淀底座，推文作为锋利切角与高价值交付物。
- 核心矩阵：覆盖 zero-noise, deep-pod, read-deep, hidden-gems, zero2dev, deep-ask, human-tone, clean-ui, dont-burnout, open-alt, flare-box, save-time, opc-global, zero-stack, cold-launch, dev-english, free-assets, global-sim, one-person-one-site, FlareMo 等开源资产。
- 飞轮闭环：
  1. 仓库沉淀：以纯文本、清单、代码模板、OPML 等作为可验证物理资产；
  2. 锋利发推：直击痛点，交付具体可复制的干货，挂出仓库一手链接；
  3. 社区互动：引导读者在 GitHub Issues 或 PR 补充案例，沉淀 Star 与技术信任；
  4. 持续迭代：将评论区与社区贡献回填至仓库，衍生出二次技术复盘与深度手册推文。
- Account-fit test: 推文必须挂载真实可访问的自有开源仓库，交付具体可带走的资产或结论，严禁干瘪的功能通告与营销自嗨。
- 归档标杆：`hit-site-20260909-001`（福滤娃开源词库征集，108 万曝光 / 2,465 收藏）；`hit-site-20260906-002`（sub-store-cloudflare，4.5 万曝光 / 471 收藏）。

## P0: AI and Coding Agents

- id: `ai-coding-agents`
- Model versus harness behavior.
- Codex, Claude Code, ZCode, OpenCode, and comparable agent products.
- Prompts, tool schemas, context management, and model adaptation.
- New-model and new-agent hands-on experience.
- Pricing, quotas, reliability, and current value-for-money conclusions.
- Account-fit test: does the post carry a conclusion the account reached by
  actually running the tool at a named version or price? A rewrite of the
  announcement without a first-hand comparison fails and belongs in
  `external_views`.
- Archive exemplar: `hit-site-20260906-026`
  (`workspace/posts/hit-site-20260906-026.md`, 237,115 views) — DeepSeek API
  built-in web search, a hands-on discovery with the concrete call format.

## P1: Independent development

- id: `indie-dev`
- Low-cost technology stacks and the Cloudflare ecosystem.
- Product-to-deployment workflows for solo builders.
- Developer tools, payments, infrastructure, and operational shortcuts.
- Combinations that reduce money, maintenance, or time to launch.
- Account-fit test: does the post end in something a solo builder can copy —
  a stack, a step list, a price, or a deploy path? Pure market commentary
  fails.
- Archive exemplar: `hit-site-20260906-001`
  (`workspace/posts/hit-site-20260906-001.md`, 102,402 views) — the Cloudflare
  "穷鬼全家桶" stack, each service named against a concrete job.

## P1: AI productivity and ways of working

- id: `ai-productivity`
- Agents completing real work instead of merely chatting.
- Mobile, remote, and automated workflows.
- Which steps a tool actually removes.
- Personal systems that materially change how work gets done.
- Account-fit test: can the post name the step that disappeared and the scene
  where it used to cost time? A feature list without the removed step fails.
- Archive exemplar: `post-20260906-030`
  (`workspace/posts/post-20260906-030.md`, 39,001 views) — customizing Pi's
  SDK into a personal workflow, layer by layer.

## P2: Insight, growth, and independent income

- id: `insight-income`
- Use only when there is a specific user idea, real experience, or unusually
  strong connection to the primary pillars.
- Account-fit test: does the account have first-hand experience or a dated
  personal decision behind the claim? Otherwise it is skip.
- No archive exemplar yet: no post in `workspace/posts/` clears the fit test
  for this pillar. Keep it out of the daily scan until one does.

## P3: Efficient language learning

- id: `language-learning`
- Do not include in the default daily scan until the user explicitly promotes
  it.
- Account-fit test: does the post show a method the account actually used and
  its measured effect? Otherwise it is skip.
- No archive exemplar yet.

## Ranking rule

Prefer a smaller signal with a clear account-specific angle over a large trend
that would only produce a rewritten news summary.
