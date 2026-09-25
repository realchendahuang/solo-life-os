---
name: source-registry
description: Manage the small, high-value source registry for X-Tiller without turning it into broad scraping. Use when the user asks to add, remove, prioritize, or review the official sources that should feed topic discovery. Do not use for a specific X post, trend discovery, or final fact verification.
---

# Source Registry

Maintain the intentionally small set of sources that can produce candidates for
@realchendahuang. This is configuration and quality control, not an automated
news feed. `sources/registry.json` is **stateless metadata**: it defines the sources,
`fetch_mode`, `cadence`, `event_filters`, and `priority`.

To poll the official changelogs and RSS feeds into the candidate ledger (`workspace/candidates.jsonl`) with
concurrency and automatic Hit-Playbook blueprint tagging, run:

```bash
python3 .agents/skills/source-registry/scripts/poll_registry.py --dry-run
python3 .agents/skills/source-registry/scripts/poll_registry.py
```

Polling reads the whitelist; it does not look for sources you have not added.

Preconditions and side effects worth knowing before running it:

- Some registry entries are not machine-readable (JS-rendered changelogs such as
  `openai-api-changelog`). The poll reports them as `no machine-readable feed`
  instead of storing navigation links; capture those by hand with the user-level
  `web-search` skill plus `capture_candidate.py`.
- Reddit/linux.do/IndieHackers entries are read out of **your open browser tab**
  through the Kimi WebBridge daemon (`http://127.0.0.1:10086`) and are skipped
  unless `--webbridge` is passed, because that path can open tabs in your Chrome.
- `x-direct-signal` is a manual-capture source: poll never sweeps it; use
  `capture_x_signal.py --url` for one post at a time.
- Feed timestamps are normalized from RFC 822/RFC 3339; a date that cannot be
  read stays `null` rather than being replaced with the fetch time.

To triage and scan candidate signals by Blueprint (A-E) or action (defaults to `--unseen-only`, excluding previously surfaced or promoted items):

```bash
python3 .agents/skills/source-registry/scripts/triage_candidates.py --action brief
python3 .agents/skills/source-registry/scripts/triage_candidates.py --blueprint B
python3 .agents/skills/source-registry/scripts/triage_candidates.py --broad --mark-presented
python3 .agents/skills/source-registry/scripts/triage_candidates.py --dismiss <candidate-id>
python3 .agents/skills/source-registry/scripts/triage_candidates.py --include-seen
```

Candidates live in one append-only JSONL ledger (`workspace/candidates.jsonl`, one JSON
object per line, deduplicated by `canonical_url` at capture). A persistent
presentation cache (`workspace/history/presented_ledger.json`) keeps already surfaced
candidates from repeating across conversations.
Candidate records carry `match:<blueprint>:<keyword>` tags (for example
`match:E:cli`), so a classification can be explained rather than guessed at.

To see per-source volume and yield before deciding what to keep:

```bash
python3 .agents/skills/source-registry/scripts/source_stats.py --active-only
```

To housekeep the candidate pool (defaults to a preview; nothing is deleted
without `--delete`):

```bash
python3 .agents/skills/source-registry/scripts/prune_candidates.py --days 30
```

`--days` has a floor of 7, a deletion covering more than 30% of the pool (or all
of it) additionally requires `--yes`, and every deletion writes a manifest to
`workspace/runs/prune-<timestamp>.json`. Candidates referenced by a topic entry
or marked `promoted` are locked and never pruned.

To promote an approved candidate into the Topic Library (`workspace/topics/`):

```bash
python3 .agents/skills/source-registry/scripts/promote_candidate.py --candidate-id <ID>
```

The candidate title becomes the topic statement when `--statement` is not given,
so supply your own wording when the machine title is not how you would say it.

To capture an X/Twitter post directly into the candidate pipeline:

```bash
python3 .agents/skills/source-registry/scripts/capture_x_signal.py --url https://x.com/user/status/123456
```

## One size rule

Keep the registry small and reviewable (**42 sources as of 2026-09-20**; the
schema allows up to 200, which is a safety bound, not a target). Add a source only when it has a
clear event filter. Prefer a smaller registry over a broad feed.

## Workflow

1. Read `profile/content-pillars.md`, `profile/operating-policy.md`,
   `sources/registry.json`, and `contracts/source-registry.schema.json`.
2. For a new source, use the user-level `web-search` skill to confirm that its
   URL is a current primary source. Prefer official changelogs, release notes,
   documentation, blogs, and GitHub Releases.
3. Add a source only when it serves a content pillar and has a clear event
   filter.
4. Run:

   ```bash
   python3 .agents/skills/source-registry/scripts/check_registry.py
   ```

   The validator reads its enums and limits from
   `contracts/source-registry.schema.json` when that file is readable and falls
   back to built-in copies with a warning if it is not; the summary's
   `rules_source` field says which was used.

5. After manually reading a relevant source item, capture one candidate rather
   than copying it into a draft:

   ```bash
   python3 .agents/skills/source-registry/scripts/capture_candidate.py \
     --source-id openai-api-changelog \
     --url https://developers.openai.com/api/docs/changelog \
     --title "Specific official change" \
     --excerpt "A short faithful excerpt" \
     --verification-status official-primary \
     --suggested-action watch
   ```

   `--url` must be on the registered source's host or one of its subdomains,
   and the registry itself is validated first, so a broken entry fails with a
   clear exit-2 error instead of a traceback.

6. Candidate artifacts and any personal observations go under ignored
   `workspace/` (default ledger `workspace/candidates.jsonl`), never in the
   tracked registry. Duplicate detection scans the ledger by `canonical_url`
   and content hash.

## Candidate boundary

When a source produces a potentially useful item, save a Candidate Signal that
matches `contracts/candidate-signal.schema.json`. Keep the source URL, a
canonical URL, the original excerpt, timestamps, a SHA-256 content hash, and
its verification state. A candidate is not a fact and is not publish-ready.

Use `suggested_action` deliberately:

- `brief`: enough novelty and account-specific value to send to `topic-brief`;
- `watch`: retain it without writing about it yet;
- `discard`: record why it was not useful when that improves future filtering.

## Rules

- Do not add an unofficial aggregator when an official source exists.
- Do not fetch sources continuously, scrape broad communities, or automatically
  publish a candidate.
- Community feedback can establish that somebody experienced something, not
  that it is universal or technically proven.
- Every time-sensitive claim still needs current primary-source verification in
  `topic-brief`.
