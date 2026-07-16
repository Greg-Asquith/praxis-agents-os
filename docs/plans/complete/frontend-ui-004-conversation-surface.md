# Plan 004: Conversation surface — transcript & message styling

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.
>
> **Pre-flight**: plan 002 keeps the existing header row (breadcrumbs +
> workspace switcher), just relocated inside the canvas. The conversation
> route keeps rendering its own `ConversationDetailHeader` below it, as
> today — this plan does not change header ownership.

## Status

- **Completed**: 2026-07-16
- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM — the transcript is the core product surface and has
  live-streaming rendering paths; styling changes must not disturb the
  stream reducer, grouping, or auto-scroll logic.
- **Depends on**: 001 (tokens), 003 (agent identity).

## Goal

Make the transcript read like the reference: a calm single column of
content on the white canvas — user turns as compact right-aligned bubbles,
assistant turns as unadorned prose with a light identity header, generous
breathing room, and quiet streaming states. Styling only: no changes to
`stream/`, grouping, or persistence.

## Current state (verified at `158de0b`)

All under `src/features/conversations/components/` unless noted.

- Route (`routes/conversation-route.tsx:153-204`): flex column; scroll
  region inner column `mx-auto w-full max-w-5xl px-4 py-4 pb-6` (line 161).
- `message-list.tsx:150`: turns stacked with `gap-6`; in-conversation empty
  state at lines 134–146.
- `message-shell.tsx`: user bubble (line 34) `bg-muted text-foreground
  rounded-2xl px-4 py-2.5 text-sm leading-relaxed`, max-w
  `min(42rem,86%)`, with a timestamp + `Avatar` meta row *above* the
  bubble (line 26). Assistant turn (lines 42–70): generic gray `BotIcon`
  circle (line 56), name + timestamp row, pulsing dot when streaming
  (line 63).
- `message-markdown.tsx`: root `text-sm leading-7` (line 65); component
  map lines 94–249; code block card lines 251–277.
- `message-row.tsx`: `ThinkingBlock` (lines 210–228) — "View Thoughts"
  `<details>`, italic bordered body; `AssistantLiveActivityRow` (78–105)
  with plain "Working..." placeholder text.
- `hooks/use-conversation-auto-scroll.ts`: imperative jump-to-bottom on
  content growth; no scroll-to-bottom affordance.

## Decisions taken

1. **Set the transcript column to `max-w-4xl`** (56rem) with `px-6`.
   The original 48rem target proved too narrow against a real tool-heavy
   transcript during maintainer QA; 56rem preserves readable prose while
   giving operational rows enough room. The composer column (plan 006) must use the same width —
   coordinate the shared classname (put it on the two inner columns; do
   not invent a layout component for two call sites).
2. **Assistant turns lose the per-message avatar.** The reference shows
   none; the agent identity moves to a slim turn header shown once per
   turn: `AgentIdentityIcon` (`sm`, from plan 003) + agent name +
   timestamp. In the common single-agent conversation this reads as a
   light rhythm marker, and in delegation transcripts it disambiguates.
3. **User bubbles keep `bg-muted`** (reference user turns are light-gray
   bubbles) but drop the meta row above — the timestamp moves into a
   hover-revealed inline affordance; the user `Avatar` goes away entirely
   (redundant: alignment already says "you").
4. **Copy**: "View Thoughts" → "Thinking"; "Working..." → "Thinking…"
   while no text has streamed. Sentence case throughout.

## Steps

### 1. Column + rhythm

- `conversation-route.tsx:161`: inner column → `mx-auto w-full max-w-4xl
  px-6 py-6 pb-8`. Same for the composer footer inner column (lines
  193–194) — keep them visually flush.
- `message-list.tsx:150`: `gap-6` → `gap-7`; user-turn-to-assistant-turn
  already reads as grouped via alignment, so uniform gap is fine.

### 2. User turns (`message-shell.tsx:11-40`)

- Remove the meta row (line 26) and the `Avatar`.
- Bubble: `bg-muted rounded-2xl rounded-br-md px-4 py-2.5 text-sm
  leading-relaxed` (the flattened corner anchors it to the right edge),
  max-w `min(38rem,90%)`.
- Timestamp: `text-muted-foreground text-xs opacity-0 transition-opacity
  group-hover/message:opacity-100` sitting under the bubble,
  right-aligned. Keep the existing `group/message` wrapper.

### 3. Assistant turns (`message-shell.tsx:42-70`)

- Replace the `BotIcon` circle (line 56) with `AgentIdentityIcon`
  (`sm`) in the label row itself — one header line: icon + `text-sm
  font-medium` name + `text-muted-foreground text-xs` timestamp +
  existing streaming dot (restyle dot `bg-primary` — it may as well be
  the accent).
- Body: full-width under the header, `pl-0` (no gutter indent — the
  reference body text is flush left with the header), content stack keeps
  `gap-3`.

### 4. Markdown & blocks (`message-markdown.tsx`)

- Root stays `text-sm`; loosen paragraph spacing: `p` → `mb-3 last:mb-0`
  (currently `mb-1`, which reads cramped at leading-7).
- Headings: keep scale, add `first:mt-0` so a heading-led reply doesn't
  float.
- Code block (lines 251–277): body `bg-muted/40` instead of
  `bg-background` so blocks read as inset on the white canvas; header bar
  keeps `bg-muted/60`; radius `rounded-lg` stays.
- Links are now brand teal via 001 — confirm `underline-offset-2` still
  looks right, no change expected.

### 5. Thinking & streaming (`message-row.tsx`)

- `ThinkingBlock` (210–228): summary label → "Thinking", keep chevron;
  body keeps the bordered-italic treatment but `border-border` at full
  opacity and `text-sm`.
- Live placeholder (line 101 and the draft fallback at 139): "Thinking…"
  with a subtle shimmer: `animate-pulse` on the text is acceptable;
  respect `motion-reduce:animate-none`.
- Empty state (`message-list.tsx:134-146`): keep structure; icon chip
  picks up `bg-muted`, title `font-heading text-lg font-medium` stays;
  check copy is an invitation ("Send a message to get started" style, in
  the interface's voice).

### 6. Scroll affordance (small, contained)

Add a "scroll to bottom" floating button: appears when the user has
scrolled > ~300px away from the bottom during a stream; `absolute` above
the composer, `size-8 rounded-full border bg-background shadow-sm` with
`ArrowDownIcon size-4`; clicking jumps to bottom (reuse the hook's scroll
target). Keep it inside the existing hook + route file; no new
dependencies. If this exceeds ~40 lines of change, ship the plan without
it and note it as pending.

### 7. Verify

- `pnpm check` passes.
- Visual pass with a real streamed conversation (make dev, run an agent
  turn): stream renders progressively with no layout jumps; thinking
  expands/collapses; user/assistant rhythm matches the reference; hover
  reveals user timestamps; delegation transcripts (read-only lock footer,
  `conversation-route.tsx:186-191`) still render; both themes.
- Auto-scroll still pins to bottom during streaming; scroll-up during a
  stream stays put (no fighting the user) — this is existing behavior,
  confirm it survived.

## STOP conditions

- Any change would touch `features/conversations/stream/` (parser,
  protocol, reducer) — this plan is styling-only; stop and report.
- The grouping logic (`groupConversationRenderItems`) would need to change
  to achieve the turn-header treatment — stop; the header must come from
  render-time data already present.

## Execution record

- Completed 2026-07-16 without touching the SSE parser, protocol, reducer, or
  assistant-turn grouping. The conversation's existing active-agent id and
  label now feed the shared deterministic `AgentIdentityIcon`.
- User turns are compact right-aligned bubbles with hover-revealed timestamps;
  assistant turns use a slim identity header and full-width prose. Markdown,
  code blocks, thinking labels, reduced-motion streaming placeholders, empty
  copy, and transcript rhythm now match the refined surface vocabulary.
- Auto-scroll remains pinned while the reader is at the bottom, stops fighting
  an intentional scroll-up, and exposes an icon-only return control once a live
  stream is more than 300px below the viewport.
- Maintainer visual QA of a real light-theme, tool-heavy transcript found the
  planned 48rem column too narrow. The final surface uses 56rem (`max-w-4xl`),
  and plan 006 was corrected to keep the composer aligned. All new colors use
  semantic tokens, so the same component styling carries into dark mode.
- `pnpm check` passed on 2026-07-16: typecheck, ESLint, 81 Vitest tests,
  Prettier, Knip, dependency-cruiser, and the production build.
