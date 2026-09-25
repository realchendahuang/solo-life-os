# Reference posts

These are style and topic references, not facts that should be copied. Each card
quotes the real opening and closing lines from `workspace/posts/`, states the
structural skeleton, and records the measured numbers, so the lesson can be
reused without imitating the exact wording.

Extract the structural lesson. Do not imitate exact phrasing or force every new
post into the same shape.

---

## 1. Independent-development stack and Cloudflare "穷鬼全家桶"

- Archive: `workspace/posts/hit-site-20260906-003.md` · 2026-06-15 · 41,000 views / 225 likes / 335 bookmarks / 34 reposts

**Hook (verbatim):** `# 2026 独立开发最佳实践：Cloudflare 穷鬼全家桶`

**Skeleton:** label the whole stack in the title → one tool per line, no prose
between them (`Codex：写代码，搞定全栈开发` / `数据库：Cloudflare D1` / `缓存 / 配置：Cloudflare KV`) → stop.

**Why it works:** bookmarks (335) beat likes (225) by 1.5×. The post is not read,
it is kept — a reader can copy the list straight into their own project. The
list has no filler sentence, so nothing needs to be edited before reuse.

**When not to reuse:** only when every line is a tool the owner actually runs.
A list assembled from documentation reads as a directory listing and earns
nothing. Do not pad it with a closing summary.

---

## 2. Model versus harness distinction

- Archive: `workspace/posts/post-20260906-021.md` · 2026-08-30 · 19,672 views / 11 likes / 6 bookmarks / 3 replies

**Hook (verbatim):** `很多人用 Claude Code、Codex 用久了以后，会很容易把"模型"和"Coding Agent"当成一回事。`

**Skeleton:** describe the reader's current mental model as reasonable → show
where it breaks (`但到了 DeepSeek V4、GLM-5.3 这些开放模型这里，问题就出来了`) →
name the missing concept in one line (`简单理解，模型负责"想"，Harness 负责让模型真正把事情干出来`)
→ enumerate the mechanisms that concept covers → close by replacing the
original question with a better one.

**Why it works:** it never says "大家都不懂". It grants the reader the correct
reasoning and then supplies the one missing layer. The definition is a
breathe-easy sentence, not a jargon block, and the mechanisms after it
(工具调用失败处理、去重、Compaction、Prefix Cache) prove the author has run them.

**When not to reuse:** this is a concept post, so low likes are expected and
fine. Do not bolt a conclusion or a call to action onto it — the reframed
question at the end is the payoff.

---

## 3. Follow-up on model and harness

- Archive: `workspace/posts/post-20260906-020.md` · 2026-08-30 · 13,292 views / 34 likes / 17 bookmarks / 13 replies

**Hook (verbatim):** `很多人选 Coding Agent 的第一反应都很自然：`

**Skeleton:** state the common default as reasonable (`用 Claude，就上 Claude Code`)
→ concede what the incumbent is genuinely better at → pivot
(`但到了 DeepSeek、GLM 这些开放模型，事情就开始变得有意思了`) → give the
mechanism (training a good model and building a good harness are different
engineering) → close with the reframed choice.

**Why it works:** replies (13) are ~3× what a same-size opinion post usually gets
here, because the post takes a widely held position seriously before moving off
it. It is a companion post, not a repeat — same territory, new angle two minutes
after the first.

**When not to reuse:** only as an explicit follow-up when the first post left a
question open. Running this shape twice on one topic reads as backpedalling.

---

## 4. Tool price and capability comparison

- Archive: `workspace/posts/post-20260906-025.md` · 2026-08-29 · 36,364 views / 219 likes / 223 bookmarks / 30 replies

**Hook (verbatim):** `经常用Deepseek、GLM国产模型朋友们完全可以看看洋人搞出来的全家桶：`

**Skeleton:** name the audience and the subject in the first line → cut straight
to the verdict (`得出结论就是闭眼选 Command GOAT，毋庸置疑`) → date-bound the
verdict (`在2026年八月末，版本答案就是`) → give exactly one link → stop.

**Why it works:** it is 5 lines. The verdict arrives before the reader can
scroll, the date boundary makes it falsifiable rather than absolute, and exactly
one URL means nothing competes for the click.

**When not to reuse:** the verdict must come from actually comparing the plans.
Without the dated boundary this becomes a permanent claim about a moving target,
which the Avoid list forbids.

---

## 5. Follow-up current recommendation

- Archive: `workspace/posts/post-20260906-024.md` · 2026-08-29 · 50,554 views / 265 likes / 198 bookmarks / 32 replies

**Hook (verbatim):** `之前X上面吹的牛逼的5美元OpenCode Go已经彻底拉完了。`

**Skeleton:** report the change that invalidated the old answer → contrast the
competitor's new position → introduce a two-line mental model
(`主力模型和苦力模型`) → map each model onto it → re-issue the verdict with the
date boundary.

**Why it works:** it is a price-sensitive post published inside the window where
the price moved, and it supplies a reusable frame (主力/苦力) rather than only a
ranking. The frame is why the post keeps earning bookmarks after the prices
change again.

**When not to reuse:** the window is roughly 24–72h. After that the numbers are
stale; write a new post instead of editing this one.

---

## 6. Concrete ZCode productivity scene

- Archive: `workspace/posts/post-20260906-026.md` · 2026-08-28 · 1,135 views / 6 likes / 2 replies

**Hook (verbatim):** `zcode真是太好用了`

**Skeleton:** one-line verdict → a physical scene (`电脑在桌上，我躺在沙发上玩手机就把活干完了`)
→ the concrete mechanic that enables it (`不需要配置网络，扫码直连`) → stop.

**Why it works:** the low numbers are the point of keeping it. It shows the same
verdict-first opening can be carried by a lived scene instead of a comparison,
and it is the shortest post in the archive that still carries a reason. Use it
as a shape reference for 白描动作流, not as a benchmark.

**When not to reuse:** a scene without the mechanic ("很好用，很方便") is a
feeling, not a post. If the mechanism cannot be named in one sentence, the scene
is not ready.

---

## 7. AI 时代个人站黄金搭档（野生黑客 / 粗粝高能流）

- Archive: `workspace/posts/post-20260925-006.md` · 2026-09-25 · 待回采

**Hook (verbatim):** `天天玩 AI 的人，现在真他妈该去搞个个人网站。`

**Skeleton:** 炸裂爆论开篇 → 核心定性（相得益彰，黄金搭档） → 5 点极简清单（1 2 3 4 5，每点严格一句话，涵盖建站速度/喂模型上下文/谷歌搜自己/AI搜索GEO/小工具挂载） → 一句粗粝号召收尾。

**Why it works:** 话极少，情绪饱满真实，彻底打破四平八稳的公文腔。用粗粝有力的口语（“骂两句提要求言出法随”、“不用叽叽歪歪输入半天”、“别给算法当孙子”）直击一线开发者爽点，阅读体感畅快淋漓，10 秒内完整交付高密度共鸣。

**When not to reuse:** 严禁用于长篇深度架构剖析或需要严密论证的严肃技术选型帖；纯粹用于破除迷思、高能安利与强行动力号召。

---

## Cross-cutting lessons

1. **Verdict before argument.** Every post above states its conclusion inside the
   first two lines. The reasoning exists to defend a claim the reader already has.
2. **Date or condition the conclusion.** `2026年八月末`, `当前版本答案`, a plan
   name — anything that lets a future reader tell whether it still applies.
3. **One link, or none.** Two URLs split the click and read as a digest.
4. **Public numbers are rounded in some entries.** `hit-site-*` files imported
   from the site carry approximations; `post-*` files carry x-fetch snapshots.
   Do not compare across the two without checking `source` in the frontmatter.
