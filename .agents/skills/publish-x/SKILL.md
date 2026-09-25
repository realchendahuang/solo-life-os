---
name: publish-x
description: Publish an already-final post for @realchendahuang. Direct posting uses the X intent URL (visible prefilled composer, user clicks Post); scheduled posting is queued by the human in the Buffer console (no API client exists in this repo). Use for "发布一下", "帮我发", or "定时发"; do not use for drafting, scheduling decisions, or autonomous browser posting.
---

# Publish X

Two channels, chosen by **requested timing**:

```
直接发布（默认）  →  x.com/intent/post?text=...  预填的可见 composer → 用户审阅 → 用户点 Post
定时/排程发布     →  Buffer 控制台（由本人手动排队）→ Agent 只出示最终稿并说明要录入什么
```

There is no X API direct-publish path, and no Buffer API client in this repo
(no script, no token): the agent never publishes through Buffer. The Post click
for the direct channel always stays with the user.

Read `profile/operating-policy.md` and the final agreed post text (from the
conversation, or a legacy draft file) before either mode.

## Length accounting (applies to every channel)

`scripts/draft_text.py` is the shared text layer used by both helper scripts.
X counts a **weighted** length, not characters: CJK/fullwidth characters count
2, every URL counts 23, all other characters count 1, and the limit is 280.
`preview()` prints `weighted N/280` plus the first/last 80 characters.

`intent_open.py` refuses (>280) unless `--allow-over-limit` is passed, which
downgrades the refusal to a warning (long post / X Premium). Chat-delivered
posts are often above 280 and must be edited down or consciously overridden —
never silently posted.

Markdown handling is also shared, so the two scripts can never drift:

- YAML frontmatter is never part of the published text.
- `## Verification notes`, `## Feedback`, and `## Notes` sections are dropped
  whole and never reach the composer or the clipboard.
- Markdown heading lines (`# ...` with a space) are stripped, but hashtag lines
  such as `#AI 编程工具 又更新了。` — no space — are kept, and heading-looking
  lines inside fenced code blocks are preserved.

## Direct channel: X Web Intent URL (default for "帮我发")

Use when the user asks to post now (or gives no timing). The official Web
Intent endpoint opens X's composer with the text prefilled:

    https://x.com/intent/post?text=<url-encoded text>

Recommendation: open the URL in the user's default browser (`open`). Verified:
a real user browser (manual paste or `open`) prefills the text; automated
WebBridge `navigate` does NOT trigger prefill (X treats scripted navigation
differently), so always use `open` for this channel.

Helper (extracts the publishable text, checks the weighted limit, url-encodes
it, opens the intent URL, and keeps the same text on the clipboard as a
manual-paste fallback):

    python3 .agents/skills/publish-x/scripts/intent_open.py \
      --text "帖子正文全文"

Flags:

- `--dry-run` — print the draft, preview, and intent URL; touch neither the
  clipboard nor the browser. Use this to show the exact text first.
- `--no-open` — copy to the clipboard and print the intent URL, but do not open
  the browser (used when the user already has X open).
- `--allow-unapproved` — the script exits 2 unless the frontmatter has
  `status: approved`. Legacy drafts without frontmatter also require this flag.
- `--allow-over-limit` — warn instead of refusing above weighted 280.
- `--thread --part N` — for thread drafts. See below.

The script exits 2 on a refused draft (unapproved, over limit, thread without
`--thread`, bad `--part`) and exit 3 if `pbcopy`/`open` fails, in which case it
prints the intent URL for manual pasting. On non-macOS platforms it skips
`pbcopy`/`open`, warns, and prints the URL.

### Thread posts

Legacy file mode only (the old draft-file workflow was retired 2026-09-24): a
thread draft has one `## Post N` section per part. Without `--thread` the
script refuses a multi-part draft instead of
concatenating the parts into one blob. With `--thread`:

1. The script lists every part with its weighted length and never concatenates.
2. `--part N` (default 1) selects the one part this run prepares: it prints the
   part, copies **that part** to the clipboard, and opens the intent composer
   for it.
3. After the user posts part N, rerun with `--part N+1` and tell the user to
   reply-chain it to the previous post. Repeat until the last part; the script
   prints this reply-chain instruction each run.

In the conversation workflow (`--text`), pass each thread part as its own
`intent_open.py --text …` call, one part at a time.

Then report the opened composer and let the user review and click Post. Never
click Post, submit a keyboard shortcut, or claim publication. Do not archive
the post unless the user confirms it went out; the publisher is the user.

## Scheduled channel: Buffer (human-executed, agent does not queue it)

Use only when the user explicitly asks for timing, queueing, or "定时发".
There is **no Buffer API client and no configured token in this repo** — the
agent cannot create, queue, or schedule a Buffer post. Buffer is connected to
@realchendahuang's X account in the human's own Buffer console; only the human
operates it. Free plan: 10 queued posts per channel at once, slots free as
posts publish.

The agent's job is therefore only:

1. Show the final agreed text (with its weighted length) and get the user's
   approval for that exact wording. In the conversation workflow the wording
   shown in chat is the approval record — no draft file exists to mark. This
   marks *approval of the wording*, which is a separate act from the final
   Post click the user performs in step 3.
2. Tell the user exactly what to queue in the Buffer console: the full text
   (the trailing source URL is part of the text), the X channel, and that the
   schedule time is theirs to choose. Never pick a schedule time on the agent's
   own initiative.
3. After the user confirms the post went out (from Buffer), archive it with the
   hit-archive recorder (creates `workspace/posts/*.md`, kind: published, per
   `contracts/hit-post.md`):

   ```bash
   python3 .agents/skills/hit-archive/scripts/record_post.py \
     --url <post_url> --channel buffer --topic-id <topic-id>
   ```

   Pass `--topic-id` so the topic library learns the post shipped: the same
   call advances that topic to `published` and attaches the post URL to it.
   Recording without it is how the library ends up full of topics that were
   published months ago. (Draft files were retired 2026-09-24 — writing is
   conversation-only, and `--draft-id` is optional loose bookkeeping.)

   Do not maintain a separate publish ledger; the post archive is the single
   source of truth.

Buffer never handles replies, quote-posts, or interactions — those are direct
channel.

## Fallbacks: clipboard and WebBridge

`fill_clipboard.py` (clipboard + compose page) and `webbridge_client.py`
(local Kimi WebBridge daemon, see the user-level `browser-control` skill)
remain for placing text into a page the user already has open (e.g. a reply
composer). They never press the publishing control.

- `fill_clipboard.py --file <draft> [--no-open]` shares the same extraction
  and weighted preview as `intent_open.py`; it refuses thread drafts (use
  `intent_open.py --thread --part N`) and prints the text instead of touching
  `pbcopy`/`open` on non-macOS platforms.
- `webbridge_client.py` usage: `navigate <url> [--new-tab] [--group "<label>"]`,
  `find_tab <url> [--active]`, `snapshot [--compact]`, `fill
  <selector_or_re> <value|file|->`, `list_tabs`. `snapshot --compact` replaces
  the accessibility tree with a size summary, and any clipped output ends with
  an explicit `…[truncated N chars]` marker.
- `evaluate "<js>"` and `raw '<json>'` are **locked by default**: arbitrary JS
  or arbitrary daemon payloads on the user's logged-in X tab are outside the
  publish flow. They run only with an explicit `--unlock`, and they are not
  needed for the normal fill flow.

## Scope boundary

One text-only post per run (a thread is prepared one part per run). Media
upload, deletion, likes, follows, replies to strangers, unattended publishing,
and agent-chosen schedule times are outside this skill.
