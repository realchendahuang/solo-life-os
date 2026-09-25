# Operating policy

## Evidence

- An X search or third-party result is a signal, not a verified fact. Do not
  use Grok Build for discovery: the channel was removed on 2026-09-19 over
  usage cost, and no agent-side trend scan exists (see AGENTS.md).
- Active discovery uses the local WebBridge daemon (`http://127.0.0.1:10086`)
  via `poll_registry.py --webbridge` against user browser sessions (LINUX DO,
  Reddit, Indie Hackers).
- **Strict noise gate on sources**:
  - Never track minor patch releases or bugfixes of single frameworks/libraries
    (e.g., Hono, uv, llamacpp). Readers are builders, not QA testers; minor library
    releases are strictly in the "坚决不选" (skip) pool.
  - Community threads must carry technical substance: strip pure giveaway / CDK
    spam, retaining only model degradation (降智), API/service fraud, cost benchmarks,
    and developer pain points.
  - Candidate discovery presents the full, comprehensive inventory of fresh signals
    in a single pass (zero artificial quantity caps or premature 8-12 batching);
    the user reads all signals at once and makes the editorial judgment.
  - **Plain-text files are the single source of truth** (no database since 2026-09-24): discovery candidates append to `workspace/candidates.jsonl`, strictly deduplicated by `canonical_url` at capture time.
- Keep direct X URLs on every retained signal.
- Verify prices, quotas, release dates, product capabilities, legal claims, and
  security claims against a current primary source before drafting them as fact.
- Label the user's position separately from established facts and third-party
  opinions.
- If a required fact cannot be verified, either remove it or mark the
  uncertainty explicitly.

## Output

- Default to at most three recommended topics or three meaningfully different
  draft strategies.
- Do not turn every signal into content: adhere to the "三选三不选" virality funnel.
- Do not invent personal use or endorsement.
- Save runtime artifacts under workspace/ with timestamps and source links.

## Publishing gate

Publishing is an external, irreversible action. This project publishes through
two channels, chosen by the requested timing:

1. **Direct (default)**: the X Web Intent URL
(`x.com/intent/post?text=...`) opens a prefilled visible composer in the
user's default browser. The exact final text must have been shown first, and
the user always performs the final Post action themselves.
2. **Scheduled**: Buffer, operated by the user in the Buffer console. There is
no Buffer client and no token in this repository, so the agent never queues
anything: it hands over the exact approved text and the user schedules it. Used
only when the user explicitly asks for timing/queueing ("定时发"); the schedule
time is always chosen by the user, never by the agent.

There is no X API direct-publish path in this project (removed by decision;
never reintroduce it).

Browser-assisted draft fill is a reversible preparation action. It is
permitted only after the exact final text is shown and the user explicitly
asks to fill that text into X. It may open the composer and fill text, but must
never click Post, submit a keyboard shortcut, claim that a post was published,
or archive the post. The user always performs the final X
publishing action, and `workspace/posts/` (the single publication record) is
written only after the user confirms the post went out.

## Dual-mode publishing and archiving

Most posts from @realchendahuang are posted manually from mobile or web, while
some in-depth threads/posts are co-crafted with the agent. The system supports
both without friction:

1. **Agent-assisted flow (co-crafted drafts)**:
   - Agent runs `intent_open.py` to open the prefilled composer;
   - Agent **must always display a reminder**: "已为你预填发推框，请审阅并点击 Post；发完后把推文链接发我，我来建档！"
   - User posts and returns the URL; Agent records with `record_post.py --channel intent --url <url> --topic-id <topic_id> --text "正文"`.
2. **Manual spontaneous flow (user posts directly — the majority case)**:
   - User posts directly on X (app/web) with no prior workspace draft;
   - **Instant single ingest**: User shares the URL (or text+URL) with "刚发了这篇，帮我入库"; Agent archives with `record_post.py --channel unknown --url <url> --text "正文"` or `archive_hit.py`, automatically fetching verbatim text via `x-fetch`.
   - **Periodic mirror reconciliation**: User asks to sync ("把这几天我手动发的帖子对账同步一下"); Agent runs `import_from_site.py --mirror` to batch-import all missing posts from `chendahuang.com/mirror.json`.
3. **Hit post learning & pattern extraction**:
   - When the user shares a high-performing post URL ("收进精华库" / "分析为什么爆"), Agent archives it via `archive_hit.py`, analyzes its Hook, structure, rhythm, and tension, and upon explicit user approval, records the pattern into `profile/hits-patterns.md` to guide future drafting.

## Secrets

- Read credentials only from environment variables at execution time.
- Never place tokens in prompts, command output, logs, drafts, or committed
  files.
- Never ask the user to paste a token into chat.

## Multi-device synchronization & turn closure

- The repository is actively operated across multiple devices (laptops, desktops).
- Sync is **manual and explicit**: run `python3 scripts/sync.py` only when the user
  asks to sync or after content has been confirmed and archived (e.g. a published
  post recorded into `workspace/posts/`).
- Never sync unconfirmed work: drafting, editing, and rule changes stay local until
  the user approves. The sync script pulls with rebase, commits with a semantic
  message, and pushes to `origin main`.
