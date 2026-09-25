---
name: topic-brief
description: Conversation-only topic evaluation for @realchendahuang — judge whether a topic is worth posting, pick the best angle, and list what evidence is missing. Use for "这个值不值得写", "给我几个角度", "这个题从哪切". Do not use merely to store a raw idea, discover X trends, or write final copy.
---

# Topic Brief（选题研判 —— 纯对话，不落盘）

Convert raw material into a decision about whether this account has something
worth saying. All output lives in the conversation: no brief files, no status
changes, no library bookkeeping (the `workspace/briefs/` artifact workflow was
retired 2026-09-24 — zero briefs were ever needed downstream).

## Workflow

1. Read the source topic (a `workspace/topics/` entry), idea, or historical
   signal artifact, then read:
   - profile/identity.md
   - profile/content-pillars.md
   - profile/hits-patterns.md（四维潜力漏斗 + P1–P8 模式 + 三选三不选）
2. Cluster source items that describe the same event. Keep their original
   identifiers and URLs.
3. Separate the evidence into:
   - verified facts with current primary-source URLs and verification times
   - representative external views with direct URLs
   - the user's stated position, or null when not yet known
4. Verify time-sensitive claims against current primary sources using the
   user-level `web-search` skill, preferring official docs and product pages.
   When a specific X post needs its original text, fetch it with x-fetch. There
   is no agent-side X trend scan in this repository (the Grok channel was
   removed on 2026-09-19), so a brief starts from something the user named or
   from a historical signal — never from an invented scan result.
   If the user already pasted the full text/data in the conversation, work
   from it directly — never re-fetch what is already in front of you
   (AGENTS.md §5).
5. Produce no more than three angles. Each angle must add a distinct mechanism,
   comparison, practical scene, or judgment rather than a wording variation.
6. Assign one verdict, stated in the reply:
   - ready: enough evidence and a distinct account fit
   - needs-evidence: promising but a material claim remains unresolved
   - skip: stale, repetitive, weak fit, or no original value

## User-facing result

Lead with the recommendation. Show the best angle first, explain why it fits the
account, list the evidence still needed, and include source links. Do not write
a full post unless the request also asks for drafting; in that case hand the
chosen angle to post-drafter.
