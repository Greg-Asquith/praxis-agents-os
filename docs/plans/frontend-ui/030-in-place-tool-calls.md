# Plan 030: In place, in order — tool calls interleave with text

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-17, anchors verified against the working tree at
  `19ace81` with plan 022 applied. Part of the tool-surface series —
  see the series preamble in plan 025. This plan carries the fifth
  thread: **in place, in order** (maintainer direction, 2026-07-17).
- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM-HIGH — this restructures how turns are parsed and
  rendered, touching the message-parts parser and the live-stream
  reducer. Both are pure client-side transforms with existing unit
  tests, and no wire or persistence format changes; the risk is
  ordering bugs that scramble transcripts, so the test surface for
  ordering must grow substantially.
- **Depends on**: nothing in the series mechanically (it precedes the
  card work in spirit — cards land in the right position because of
  it). File-disjoint from 025; overlaps 027/028 in `message-row.tsx`
  and the reducer — run it **before** them, or coordinate. Web-only.

## Goal

When the agent writes a paragraph, calls a tool, and continues writing,
the transcript should read exactly that way: text, then the tool
surface, then text — the same narrative order the agent actually
worked in. Today every assistant turn renders **all tool calls first,
then thinking, then all text** regardless of when things happened
(`message-row.tsx`: `AssistantLiveActivityRow` renders
`toolActivities.map` before the text drafts, `AssistantTurnRow` does
the same for persisted turns, and `MessageContentParts` puts tool
activities after all text parts within a single message). The result
reads like an attachment dump on top of an essay — and it breaks the
collaborating-in-real-time feel the series is built for: a running
activity card (028) should appear at the *bottom* of the turn's story
so far, right where the agent paused to act, not pinned above
paragraphs the agent wrote earlier.

## Current state (verified 2026-07-17, working tree at `19ace81` + 022)

- **Order is destroyed at parse time.** `ParsedConversationMessage`
  holds separate typed arrays — `text: string[]`,
  `thinking: string[]`, `toolActivities: ToolActivity[]`
  (`message-parts/types.ts`) — built by the parser in
  `message-parts/parse.ts` from the persisted model-message parts,
  which *are* ordered in the source payload.
- **Persisted turns**: `AssistantTurnRow` (`message-row.tsx:120-149`)
  renders `toolActivities` first, one `ThinkingBlock`, then per-message
  text; `MessageContentParts` (`:184-193`) orders thinking → text →
  attachments → tools within one message.
- **Live turns**: the stream reducer keeps `messages` (text/thinking
  drafts) and tool activity state separately; events arrive in true
  chronological order over SSE (`stream/reducer.ts`), and
  `AssistantLiveActivityRow` (`message-row.tsx:82-118`) renders all
  activities, then thinking, then all text drafts.
- Existing test coverage for the parser and reducer lives under
  `apps/web/tests/features/conversations/` (paths mirror source
  modules).
- The versioned SSE protocol and the persisted message format both
  carry enough sequencing information to reconstruct order (parts
  arrays are ordered; stream events arrive in order). No backend
  change is needed.

## Design decisions (this plan)

- **Ordered parts become the parse output.** `ParsedConversationMessage`
  gains an ordered `parts: MessagePart[]` sequence
  (`{kind: "text" | "thinking" | "tool"} …`) built in source order.
  The existing flat arrays remain as derived views only if callers
  still need them (search for consumers; prefer migrating them) — no
  component may re-sort parts by kind after this plan.
- **The reducer preserves arrival order.** Live turns compose one
  ordered timeline: text drafts and tool activities tagged with a
  monotonic sequence assigned as events arrive. In-place updates to a
  running activity (completion, result) update the existing entry —
  they do not move it. Ordering derives from stream arrival, not
  wall-clock (`Date` stays out of the reducer).
- **Thinking stays a collapsible block, positioned where it happened.**
  Consecutive thinking parts merge into one block at the position of
  the first, as reading flow beats fragmenting into many tiny
  disclosures. Interleaved thinking → tool → thinking sequences render
  as separate blocks in true order.
- **Turn rendering walks the timeline.** `AssistantTurnRow`,
  `MessageContentParts`, and `AssistantLiveActivityRow` render the
  ordered sequence; tool rows/cards (027/028) land wherever the
  timeline puts them. The "Thinking…" pulse placeholder still shows
  when a live turn has no content yet.
- **Old transcripts must not regress.** Persisted turns from before
  this plan replay through the same parser; if a payload genuinely
  lacks ordering (it should not — parts arrays are ordered), fall back
  to the current grouped order rather than guessing.

## Steps

### 1. Parser: ordered parts

- `message-parts/parse.ts` / `types.ts`: emit `parts` in source order
  while building today's arrays; type the part union tightly. Audit
  every consumer of `.text` / `.thinking` / `.toolActivities` (grep
  across `features/conversations`) and migrate render-path consumers to
  `parts`; non-render consumers (e.g. previews, sorts) may keep the
  flat views.

### 2. Reducer: ordered live timeline

- `stream/reducer.ts`: introduce the sequence counter and expose an
  ordered timeline selector for the live turn (text drafts and
  activities in arrival order, updates in place). Keep existing state
  shape changes minimal — additive sequencing, not a rewrite.

### 3. Turn rendering

- `message-row.tsx`: `AssistantLiveActivityRow`, `AssistantTurnRow`,
  and `MessageContentParts` walk the ordered timeline/parts. Merge
  consecutive thinking parts per the decision above. Preserve keys
  stable across updates so running→completed transitions do not
  remount rows (scroll position and `<details>` open state survive).

### 4. Tests

- Parser tests: a turn with text → tool → text yields parts in that
  order; thinking merge behavior; legacy grouped fallback.
- Reducer tests: interleaved SSE sequences (text delta, tool start,
  more text, tool result) produce a stable ordered timeline; a tool
  completion updates in place and never reorders.
- Update any existing tests that asserted grouped order.

### 5. Verify

- `cd apps/web && pnpm check`.
- Manual QA (`pnpm dev`, both themes):
  - Prompt an agent to write, search the web, then conclude (e.g.
    "introduce the topic, then search for X, then summarize"): live
    turn shows paragraph → activity card → paragraph appearing in
    order; after the run, the persisted turn replays identically.
  - Multi-tool turns keep each call at its own position.
  - Old conversations (created before this change) still render with
    nothing lost.
  - `<details>` state on a tool row survives subsequent stream events
    in the same turn; scroll does not jump on completion.

## STOP conditions

- The persisted payload for assistant turns turns out not to preserve
  part order for some message shape — stop and report the shape; do
  not infer order heuristically.
- Preserving order requires a wire/protocol or backend change — stop;
  this plan is client-side reconstruction only.
- Row remounts on stream updates prove unavoidable with the new keying
  — stop and report; losing open/scroll state on every event is worse
  than grouped order.
