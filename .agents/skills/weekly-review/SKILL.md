---
name: weekly-review
description: Turn local publish records, draft feedback, and user-provided metrics into a cautious weekly X content review for @realchendahuang. Use when the user asks to review this week, learn from published posts, or decide what to continue, stop, or test next. Do not use to publish, fabricate metrics, or rewrite profile files automatically.
---

# Weekly Review

Review the account's own decisions and results without turning sparse data into
false certainty.

## Workflow

1. Read `profile/content-pillars.md`, `profile/writing-style.md`, and
   `profile/operating-policy.md`.
2. (Optional but recommended) Refresh metrics for posts published in the past 7 days:
   ```bash
   python3 .agents/skills/hit-archive/scripts/backfill_metrics.py --recent 7
   ```
3. Build a dated, local baseline from the post archive (`workspace/posts/`,
   the single source of truth per `contracts/hit-post.md`) and structured
   draft feedback:

   ```bash
   python3 .agents/skills/weekly-review/scripts/build_weekly_review.py --days 7
   ```

4. Read the generated JSON against `contracts/weekly-review.schema.json`.
   It is an inventory, not a performance conclusion.
   - `metrics.by_window` keeps fixed windows (`1h`, `24h`, `7d`, `30d`) under
     their plain name; every other window is keyed
     `custom:<window_start>..<window_end>`, so two different custom windows
     never merge.
   - The archive's own `metrics` frontmatter is included under the
     `archive-snapshot` bucket. Those are cumulative counters ("whatever the
     collector last saw"), deliberately kept out of the stated windows, so a
     bucket never mixes a measured interval with a lifetime total.
   - Within one window bucket only the latest snapshot per post is summed
     (latest by `recorded_at`, falling back to ledger order). Repeated
     snapshots of the same post measure the same window and must never be
     added together. `record_count` counts those summed latest snapshots.
   - `feedback.user_stated_evidence` repeats the user's own reasons and
     constraints verbatim (most recent first, capped at 10 per outcome). It
     is user evidence, not an inferred cause; never paraphrase it into a
     finding the user did not state.
   - An `evidence_gaps` entry reports when the archive is stale relative to
     the review window ("archive has no posts after ...; N days missing").
     Treat the missing days as missing data, not as a content decision.
   - A `feedback` gap that says no structured feedback exists means the ledger
     went unrecorded for the period, not that the user gave none. Say so
     rather than reading silence as approval.
5. If the user supplies X metrics, retain the source, collection time, metric
   window, and post ID under `workspace/metrics/`. Use the local recorder; it
   never reads X or invents a metric:

   ```bash
   python3 .agents/skills/weekly-review/scripts/record_metrics.py \
     --post-id <numeric-post-id> --metric-window 24h \
     --window-start 2026-09-01T10:00:00+08:00 \
     --window-end 2026-09-02T10:00:00+08:00 \
     --source x-analytics --impressions 1200 --likes 34
   ```

   Do not invent impressions, engagement, clicks, or reach.
6. Separate the final review into:
   - observations supported by the local records;
   - hypotheses worth testing next;
   - profile or writing-style changes that require the user's explicit approval.
7. Save final review notes under `workspace/reviews/`. Never directly modify
   files under `profile/` during a review.

## Feedback records

When recording user edits, approvals, or rejections, append one JSON object to
`workspace/feedback/ledger.jsonl` matching `contracts/feedback.schema.json`.
Preserve the user's reason and constraints; do not infer a reason from silence.

## Rules

- An empty week is valid evidence. Say there is not enough data instead of
  manufacturing a trend.
- Do not compare posts by engagement unless their collection windows match;
  custom windows compare only within the same explicit bounds.
- Repeated snapshots of the same post in the same window are one measurement:
  the latest snapshot wins, and only latest snapshots per post are summed.
- Treat a user's edit/rejection as stronger evidence about voice than public
  engagement alone, and quote their stated reason/constraints rather than
  inferring a motive from silence.
- When the archive has no posts after some date inside the review window, say
  the days are missing; do not read the silence as a deliberate pause.
- A review may recommend a profile update, but only the user can approve it.
