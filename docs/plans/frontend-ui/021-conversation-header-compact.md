# Plan 021: Conversation headers — compact banner, source without pills

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-16 (anchors verified against the live tree at
  `01104f7`)
- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM — display-only changes, but they touch the header
  of every conversation surface plus the shared badge component used by
  three routes; a regression is immediately visible everywhere.
- **Depends on**: nothing outstanding (004/012 are DONE). Independent of
  016–020; safe in a parallel worktree.

## Goal

The conversation banner shrinks to a single compact row, and the
Direct/Scheduled **badge pills disappear**. Source is still specified —
the maintainer wants it stated, just not as chrome — so non-direct
conversations get a quiet plain-language meta line instead. Direct
conversations are simply unmarked: direct is the default way a
conversation exists, and labeling the default is noise.

## Current state (verified 2026-07-16 at `01104f7`)

- **New-conversation banner** (`features/conversations/routes/new-conversation-route.tsx:21-39`):
  a `py-4` header stacking three rows — a badge row with
  `<Badge variant="outline">Direct</Badge>` (line 25) plus an optional
  "Starting" badge, an `h1` at `text-xl font-semibold` (line 33), and
  "N active agents available." (lines 34-36) — followed by a
  `<Separator />`. This is the banner in the maintainer's screenshot:
  roughly 110px of vertical space saying almost nothing.
- **Conversation detail header**
  (`features/conversations/components/conversation-detail-header.tsx`):
  `p-4` header with a badge row (`ConversationBadges`,
  `sourceVisibility="non-direct"`, lines 26-32), a `text-xl` title
  (33-35), an agent-label line (36-38), an optional schedule-context
  block with a "Support details" disclosure (39-58), and a two-line
  right-aligned "Last Updated" block (60-65). Rendered from
  `routes/conversation-route.tsx:203`.
- **The badge component**
  (`features/conversations/components/conversation-badges.tsx`): renders
  Approval / Unread / source / run-status pills; source visibility modes
  at lines 11 and 28-31, the source pill itself at line 53 via
  `sourceLabel` (`format.ts:6-10, 34-36`).
- **List rows** (`features/conversations/components/conversation-list.tsx`):
  pass `sourceVisibility` through (prop line 22, usage 69-73). Callers:
  `routes/conversations-route.tsx:38` (default `"non-direct"`),
  `src/routes/home.tsx:68` (`"none"`) and `home.tsx:101` (`"always"` —
  the scheduled-activity list, where source distinguishes rows).
- `lib/format.ts` already has `formatCompactDate` (line 32, from plan
  012) and `formatDateTime` (line 17).

## Design decisions (this plan)

- **No source pills anywhere.** `ConversationSourceVisibility` and the
  source branch of `ConversationBadges` are deleted, not hidden.
- **Direct is unmarked.** Nothing in the UI says "Direct".
- **Non-direct sources read as a sentence, not a label.** A muted
  meta-line fragment with a small lucide icon:
  - scheduled → `CalendarClockIcon` + "Runs from a schedule" (detail
    header extends this with the existing scheduled-for datetime).
  - delegated → `CornerDownRightIcon` + "Started by another agent".
- **Headers are one row.** Title drops from `text-xl` to `text-base
  font-medium`; everything else becomes inline muted meta on the same
  row (wrapping on mobile is fine; stacking by design is not).

## Steps

### 1. New-conversation banner → one row

In `new-conversation-route.tsx`:

- Delete the badge row (lines 24-32) including the "Direct" badge. Keep
  the "Starting" streaming indicator but move it inline into the meta
  text (a muted `CircleDashedIcon` spinner + "Starting" after the
  title), not as a pill row above it.
- Collapse the header to a single row: `New Conversation` at
  `text-base font-medium`, followed by inline muted
  `· N agents available` (drop the word "active" — users pick from a
  list; whether an agent is "active" is our jargon). Reduce header
  padding to `py-3`.
- The body empty state ("Blank chat…") and composer are untouched.

### 2. Detail header → one row

In `conversation-detail-header.tsx`:

- Single flex row: truncating title at `text-base font-medium`, then an
  inline muted meta group: agent label (`conversationAgentLabel`), a
  `·` separator, and "Updated {formatCompactDate(...)}" — replacing the
  two-line "Last Updated" block (lines 60-65). Keep the full
  `formatDateTime` value as a `title` attribute on the compact date.
- Badges shrink to the ones that carry state: keep the Approval pill and
  `RunStatusBadge` (right-aligned in the same row); the source pill goes
  away with step 3.
- Scheduled conversations: the schedule context (lines 39-58) joins the
  meta group as `CalendarClockIcon` + the existing "Scheduled for {…}"
  label. The "Support details" `<details>` disclosure stays (collapsed,
  technical, already correct) — place it as a second, conditional line
  under the row; it is the one legitimate second line.
- Delegated conversations (`conversation.source === "delegated"`): meta
  fragment `CornerDownRightIcon` + "Started by another agent".
- Header padding tightens from `p-4` to `px-4 py-3`.

### 3. Remove the source pill machinery

- `conversation-badges.tsx`: delete `ConversationSourceVisibility`, the
  `sourceVisibility` prop, `showSource` (lines 28-31), and the source
  badge (line 53). The component keeps Approval / Unread / run-status.
- `conversation-list.tsx`: drop the pass-through prop. Rows instead show
  the source icon in the existing meta line (next to the `ClockIcon`
  timestamp, lines 75-78): `CalendarClockIcon` for scheduled,
  `CornerDownRightIcon` for delegated, nothing for direct, each with an
  `sr-only` text label ("Scheduled", "Delegated") so the distinction
  survives for screen readers. This keeps `home.tsx`'s activity list
  (line 101, previously `"always"`) able to distinguish scheduled rows
  without pills; update both `home.tsx` call sites to stop passing
  `sourceVisibility`.
- `format.ts`: `sourceLabel` and `SOURCE_LABELS` — delete if the sr-only
  labels above are their last consumers inline; keep if reused. Knip
  will confirm.

### 4. Verify

- `cd apps/web && pnpm check` passes.
- Manual QA against `pnpm dev`, both themes, desktop + mobile:
  - New-conversation page: header is one compact row, no badges; the
    saved vertical space goes to the content area.
  - A direct conversation: one-row header, no source marker, compact
    updated time with full datetime on hover.
  - A scheduled conversation: meta line reads as a sentence with the
    calendar icon; "Support details" still expands; approval and
    run-status badges still appear when a run is waiting.
  - Sidebar + home lists: no pills; scheduled rows show the icon; VoiceOver
    (or devtools accessibility tree) exposes the sr-only source label.
  - Long titles truncate without pushing the badges off-row.

## STOP conditions

- Any other surface turns out to depend on `sourceVisibility` or
  `sourceLabel` beyond the call sites listed above — stop and list them
  rather than half-migrating.
- The one-row detail header cannot fit title + meta + status badges on a
  375px viewport without wrapping into more than two lines — stop and
  propose the mobile arrangement before shipping.
- Anything requires a new color or badge variant not already in
  `src/index.css` tokens — stop; this plan adds no tokens.
