---
name: idea-capture
description: Preserve a raw personal idea, observation, URL, transcript, or unfinished judgment in the X-Tiller inbox with minimal friction. Use when the user says "我有个想法", "记一下这个点子", pastes a source for later, or wants an idea saved. Do not use for an already selected topic brief or final post drafting.
---

# Idea Capture

Save the user's original expression before interpreting it.

## Workflow

1. Keep the original idea verbatim. Do not rewrite it before capture.
2. Run the capture script from the repository root:

       python3 .agents/skills/idea-capture/scripts/capture_idea.py \
         "模型和 Harness 不应该混为一谈"

   Add --source-url, --intent, --pillar, or --note only when those values are
   already available. Do not interrogate the user to fill every field.
3. Confirm the saved artifact path and restate the core judgment in one short
   sentence.
4. If the same request asks to develop the idea, hand the saved idea to
   topic-brief. Otherwise stop.

## Rules

- Direct user input outranks inferred account pillars.
- Preserve ambiguity as null or a note; do not manufacture intent.
- Store links as sources, not as endorsement.
- Do not search, rank, or draft merely because an idea was captured.

