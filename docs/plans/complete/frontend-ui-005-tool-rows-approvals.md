# Plan 005: Tool rows & approval styling

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM — approvals are a high-risk product flow (they gate
  agent actions); the restyle must not alter decision semantics, submit
  batching, or the deferred-approval state machine. Styling and copy only.
- **Depends on**: 001 (tokens), 004 (transcript rhythm this slots into).

## Constraint (settled decision — do not revisit)

Approvals and all per-tool-call UI render **inline in the tool row**, in
the same slot in the transcript — never as separate blocks below the
message list or floating panels. The reference's "Suggested moves" card is
the *visual* target for the row treatment; its placement in our product is
the existing inline slot.

## Goal

Tool activity should read as quiet, scannable one-liners that expand on
demand, and a pending approval should look like the reference rows: clear
title, supporting description, and a right-aligned ghost **Decline** +
filled **Approve** pair — calm, obvious, decisive.

## Current state (verified at `158de0b`)

All under `src/features/conversations/components/`.

- `tool-activity-row-shell.tsx`: `<details>`-based rows; summary
  `text-muted-foreground hover:text-foreground … gap-2` (line 78), body
  indented `mt-2 ml-5` (line 84); header = chevron + status icon +
  `font-medium` label + suffix (lines 25–55).
- `tool-activity-status.tsx:18-47`: `size-3.5` lucide status icons;
  `awaiting_approval` → `ShieldAlertIcon` (no color), failed/denied →
  `text-destructive`, running → spinning `CircleDashedIcon`, completed →
  `CheckCircle2Icon` (no color).
- `approval-decision-block.tsx:33`: framed box `border-border/70
  bg-muted/20 rounded-md border px-3 py-3` + prompt + fields.
- `approval-decision-buttons.tsx:24`: 2-col grid `md:w-56` — **"Allow"**
  (`CheckIcon`, default-when-selected) and **"Deny"** (`XIcon`,
  destructive-when-selected), `aria-pressed`.
- `approval-submit-bar.tsx`: "Send Decisions" bar, `pl-10` indent,
  rendered by `message-list.tsx:190-197` when >1 decision pending.
- `tool-friendly-blocks.tsx` / `tool-call-content-blocks.tsx`: args/result
  fields as `bg-muted/30`–`/50` rounded blocks; `TechnicalDetails` nested
  `<details>`.
- Custom presenters (`tool-call-row-registry.tsx:52-91`): delegation,
  skills, todo-list, file tools.

## Decisions taken

1. **Copy: "Allow/Deny" → "Approve/Decline"**, and "Send Decisions" →
   "Send decisions" (sentence case). An action keeps its name through the
   flow: the resulting status suffixes must say "Approved"/"Declined"
   wherever they currently echo allow/deny. Grep the whole feature for
   the old strings, including aria-labels and any test fixtures under
   `apps/web/tests/`.
2. **Status color vocabulary** (from 001 tokens): awaiting approval =
   `text-warning`, completed = `text-success`, failed/declined =
   `text-destructive`, running = `text-muted-foreground`. Today completed
   and awaiting are colorless; the reference uses green/amber glyphs for
   exactly these.
3. **Decline stays non-destructive-styled.** Declining is a normal,
   expected choice (the reference renders it as a ghost button), not a
   red event. The destructive tint remains only on the *outcome* icon of
   a failed/declined call.
4. **The `<details>` mechanism stays** (see README shared rules).

## Steps

### 1. Row shell polish (`tool-activity-row-shell.tsx`)

- Summary row: keep the one-line layout; label stays `text-foreground
  font-medium text-sm`; add `rounded-md px-1.5 -mx-1.5 py-1
  hover:bg-muted/60 transition-colors` so the whole row reads clickable,
  not just the text.
- Expanded body: `mt-1.5 ml-6 border-l border-border/60 pl-3 flex
  flex-col gap-3` — a hairline thread connecting detail to its row
  (replaces the bare `ml-5` indent).

### 2. Status colors (`tool-activity-status.tsx`)

Apply decision 2's mapping. The suffix text (line ~61) follows the same
colors; keep failed/declined suffix destructive.

### 3. Approval block (`approval-decision-block.tsx`, `approval-decision-buttons.tsx`)

- Block: promote from tinted wash to a proper card in the row slot:
  `bg-card rounded-lg border shadow-xs px-4 py-3`. When the tool call is
  `awaiting_approval`, the *row's* container gets a soft attention edge:
  `border-warning/40` on this card (not a filled amber wash — the
  reference stays white with subtle affordances).
- Layout inside: prompt/question `text-sm text-foreground` first; the
  action pair moves to the right on wide viewports: header-ish row
  `flex flex-wrap items-center justify-between gap-2` with the prompt
  left and buttons right, details (override-args / denial-message fields)
  below full-width. Buttons: **Decline** = `variant="ghost"` (selected
  state: `secondary`), **Approve** = `variant="secondary"` (selected
  state: `default`, i.e. accent-filled once chosen), both `size="sm"`,
  drop the `CheckIcon`/`XIcon` (the words carry it; icons add noise at
  this size). Keep `aria-pressed` exactly as-is.
- Single-approval fast path: today one pending decision still goes
  through the same buttons + submit flow — do not change the flow;
  only ensure the submit bar (below) appears consistently.

### 4. Submit bar (`approval-submit-bar.tsx`)

Restyle to a right-aligned row aligned with the cards: keep the pending
count (`text-muted-foreground text-xs`), button = `default` (accent)
"Send decisions", `ShieldCheckIcon` stays. Replace the `pl-10` magic
indent with the same `ml-6 pl-3` thread geometry from step 1 or plain
right alignment — whichever lines up with the cards in situ.

### 5. Field/result blocks (`tool-friendly-blocks.tsx`, `tool-call-content-blocks.tsx`)

- Unify tint: everything `bg-muted/40`, `rounded-md`, labels
  `text-muted-foreground text-xs font-medium` (they already are — just
  reconcile the `/30` vs `/50` inconsistency).
- `TechnicalDetails` summary gets the same hover treatment as step 1.

### 6. Custom presenters sweep

`delegation-tool-row.tsx`, `todo-list-row.tsx`, `skill-activation-row.tsx`,
file-tool rows: adopt the new status colors and body-thread geometry; the
todo in-progress icon is already `text-primary` (now brand amber — keep);
completed todo icon → `text-success`. The delegation `run …` chips keep
their mono treatment.

### 7. Verify

- `pnpm check` passes, including any tests that asserted Allow/Deny copy.
- Live QA (make dev) with an approval-gated agent: pending approval shows
  the warning-edged card with Decline/Approve; choosing and sending
  decisions works for single and multiple pending approvals; approved and
  declined calls show the right suffix + color afterwards; orphan
  approvals (message-list.tsx:169-175) still render; both themes.
- Confirm zero behavioral diff: the only changed props/strings are
  classNames, labels, and icon usage — no handler, state, or api changes.

## STOP conditions

- Any restyle step would require changing decision state shape, submit
  batching, or the SSE/approval api files — stop; styling only.
- Backend or tests depend on the literal strings "Allow"/"Deny" crossing
  the wire (check what the mutation sends — it should send enum values,
  not labels). If labels leak into the payload, stop and report.

## Execution record

- The shared row shell now gives every expandable tool presenter the same
  clickable hover surface and bordered detail thread. Delegation, skills,
  todos, file tools, and the generic presenter inherit the treatment without
  presenter-specific layout forks.
- Approval cards use the warning edge, responsive prompt/action layout, and
  quiet Decline plus decisive Approve controls from the design target. The
  submit bar is aligned to the same thread and renders consistently for both
  single and multiple pending sets.
- Tool status icons and suffixes now share the semantic warning, success,
  destructive, and muted vocabulary. User-facing decision copy consistently
  says Approve/Decline and Approved/Declined; the wire contract remains the
  existing `approved`/`denied` enums, and no handler, state shape, SSE, or API
  code changed.
- Field, result, and technical-detail surfaces now use one `bg-muted/40`
  treatment, while completed todo items use the shared success color and
  delegation metadata keeps its compact mono chips.
- Maintainer QA caught a redundant empty live assistant shell beneath an
  already-running transcript tool. Live activity visibility now suppresses
  that duplicate while retaining the initial Thinking state and every stream
  that has text or tool activity.
- `pnpm check` passed on 2026-07-16: typecheck, ESLint, 85 Vitest tests,
  Prettier, Knip, dependency-cruiser, and the production build. Automated
  browser QA was not run at the maintainer's direction; maintainer screenshot
  QA identified the redundant live shell fixed above.
