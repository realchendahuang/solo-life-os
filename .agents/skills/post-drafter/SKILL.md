---
name: post-drafter
description: Draft or revise a Chinese X single post, thread, or quote-post comment in @realchendahuang's direct, practical, opinionated voice. Use for "写成帖子", "给我三个版本", "写得更狠一点", "别这么像 AI", or editing selected copy. Do not use for trend discovery, raw idea capture, or publishing.
---

# Post Drafter

Write a post that adds the user's judgment instead of paraphrasing a source.

## Workflow (simplified 2026-09-24: conversation-only, no draft files)

1. Read the selected topic from the topic library or the user's directly
   stated position.
2. Read three files — nothing else by default:
   - profile/writing-style.md (voice, vocabulary, rhythm, editing tests;
     the absolute bans live in AGENTS.md §4 and are always loaded)
   - profile/examples-bad.md (rejected patterns and the user's reasons —
     never repeat them)
   - profile/hits-patterns.md (verified high-performing patterns — match
     the topic to P1–P8 and reuse the structure that fits)
   Read profile/examples-good.md only for entries relevant to this topic,
   and profile/facts.md only when the draft touches the user's own
   products (e.g. FeedSieve is discontinued — do not cite it as current).
   profile/operating-policy.md is for publishing, not drafting.
3. Read the most recent rows of `workspace/feedback/ledger.jsonl` (matching
   `contracts/feedback.schema.json`); apply the user-stated `reason` and
   `constraints` before writing anything. Recent feedback outranks older
   stylistic habits.
4. Resolve material evidence gaps before drafting. Never turn an unverified
   price, quota, release date, or capability into a clean assertion.
5. Match or select the Voice Archetype (profile/writing-style.md):
   - 音色 1：野生黑客 / 粗粝高能流 (Street Hacker / Raw Punchy: 极短短句、粗粝口语、12345单行清单、强号召力)
   - 音色 2：技术架构师 / 沉稳克制流 (Architect / Restrained Deep Dive: 物理规律、架构选型、算账到分厘、留有余地)
   - 音色 3：极简探针 / 犀利观察流 (Sharp Probe / Community Observer: 2~3句、直击本质困惑、舞台留给评论区)
   Unless the user specifies a treatment, either pick the archetype best matching the topic or present distinct voice options (e.g. Hacker vs Architect).
6. Match the requested format:
   - single: one complete post
   - thread: ordered posts where each item advances the argument
   - quote: a self-contained comment that assumes the quoted post is visible
7. Run every version through the editing tests in profile/writing-style.md.
8. Deliver in the chat: clean copy in a copyable ```text code block. Do NOT
   write draft files under workspace/drafts/ — that workflow is retired.
   Drafting and revision produce zero intermediate files. Alignment of the
   post back to its topic happens later, in batches, when the user imports
   official export data (see AGENTS.md section 2).

## Presentation

Show clean copy first. Put source notes and unresolved risks below it, outside
the publishable text. Never add hashtags, emoji, or calls to action by default.
Always wrap the final ready-to-post text inside a copyable fenced code block
(```text ... ```) so the user can copy with one click in the chat interface.
Never call `fill_clipboard.py`, `audit_post.py`, or any other external script
while drafting or revising — the constitution (AGENTS.md §4查/§5) forbids
extra tool calls in the writing loop. Never use Markdown headings (`###`) or
bolding (`**`) inside the post text.

## Revision behavior

Treat feedback such as "更狠", "更像我", or "太 AI" as an editing constraint,
not permission to invent facts or experiences. Preserve the user's approved
claim while changing rhythm, sharpness, and structure.

When the user edits, approves, or rejects a draft, append a dated JSON record
to `workspace/feedback/ledger.jsonl` matching `contracts/feedback.schema.json`.
Preserve the user's stated reason and constraints so `weekly-review` can learn
without inferring private intent from silence.

Use the local helper rather than writing an ad hoc record:

```bash
python3 .agents/skills/post-drafter/scripts/record_feedback.py \
  --draft-id draft-20260902-example --outcome edited \
  --reason "Too much setup before the conclusion" \
  --constraint "Lead with the judgment"
```

`--draft-id` is loose bookkeeping: it no longer resolves against
`workspace/drafts/` (draft files no longer exist).

## Rejected-pattern proposals

When the user rejects or edits a draft, the reason is durable evidence about
voice. After recording the feedback row, propose (do not write) a new
`profile/examples-bad.md` entry:

- the pattern the user rejected, in their terms;
- the draft path or a short excerpt;
- the user's stated reason, verbatim where possible.

Present the proposal and wait. `profile/` changes require the user's explicit
approval (profile/operating-policy.md); never edit `profile/` on your own.
