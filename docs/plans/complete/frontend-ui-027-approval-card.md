# Plan 027: The approval card — form-first, one-click decisions

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-17
- **Written**: 2026-07-17, anchors verified against the working tree at
  `19ace81` with plan 022 applied. Part of the tool-surface series —
  see the series preamble in plan 025 and `reference-tool-card.png`.
- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH — approvals are the product's highest-risk surface,
  and this plan changes the decision *flow* (one-click submission), not
  just its look. Frozen: the merge semantics in `buildMergedArgs`, the
  resume payload contract (`AgentRunResumeDecision`), and the rule that
  a run resumes only when every pending request has a decision.
  Changing: how and when the client submits.
- **Depends on**: 025, 026. Web-only; no backend contract changes.

## Completed implementation

- Replaced staged approval decisions and the global "Send Decisions" bar with
  per-card commits that submit as soon as every pending request is decided,
  including mixed approve/decline batches.
- Added the shared form-first approval card with declared-order inputs,
  selects, read-only wells, secondary-field reveal/focus/removal, semantic
  warning treatment, action-specific approve copy, and locked
  approved/declined states. Maintainer review widened the card and made long
  editable text multiline so requests remain readable.
- Added the decline note confirmation and Back flow, card-local failed-resume
  alert with retained decisions and Try Again, in-flight locking/progress, and
  duplicate-submit protection without changing resume payload or merge
  semantics.
- Moved delegation approvals onto the same card with task and tool fields;
  resolved history and non-approval tool calls keep their existing collapsible
  rows. Maintainer review also removed the generic Technical Details disclosure
  from conversation tool UI entirely; underlying activity data is unchanged.
- Corrected assistant-turn hierarchy so the single collapsed Thinking
  disclosure always precedes tool activity in both persisted and live turns;
  plan 030 now orders only the visible text/tool timeline beneath it.
- Verification passed: full frontend `pnpm check` with 32 test files and 151
  tests, typecheck, zero-warning lint, formatting, dead-code analysis,
  dependency-cruiser, and production build. Focused tests cover all-decided
  submission (including denials), unchanged merge/payload behavior, the
  always-open pending card, and its locked waiting state. Browser verification
  was intentionally not used per maintainer instruction.

## Goal

This is the reference card made real: when an agent asks to act, the
request renders as the app it is about to touch. Header with the tool's
identity; every argument a labeled form field in one column — editable
ones ready to type in, choices as selects, optional ones behind an
"Add …" affordance; a footer whose primary button says what approving
*does* ("Approve & Search") **and does it in one click**.

Today the same request is a collapsed log line that opens into an
indented column with a bordered sub-block, prompt-sentence-first,
generic Approve/Decline that only *stage* a decision, plus a second
"Send Decisions" button below (`approval-submit-bar.tsx:36-39`). Two
layers of buttons for one yes/no is exactly the technical feel this
series retires (maintainer direction, 2026-07-17): a non-technical user
at home in SaaS dashboards clicks one button and the thing happens.

## Current state (verified 2026-07-17, working tree at `19ace81` + 022)

- Awaiting-approval rows are ordinary `<details>` rows forced open
  (`tool-call-row.tsx:49`), headline "Permission needed: {title}"
  (`:125-131`), children indented under a left border
  (`tool-activity-row-shell.tsx:84-87`).
- Inside: read-only fields first (`tool-call-row.tsx:108`), then
  `ApprovalDecisionBlock` — a `bg-card` bordered box with the prompt
  sentence and Approve/Decline side by side
  (`approval-decision-block.tsx:38-61`), editable fields below
  (`:62-77`), denial message when declined (`:78-90`).
- Decisions stage into a local map; `shouldAutoSubmitDecisions`
  (`approval-decisions.ts:44-51`) auto-submits only when the *last*
  undecided request is approved with zero denials; any denial routes
  through `ApprovalSubmitBar`'s "Send Decisions"
  (`approval-submit-bar.tsx:10-43`), driven by
  `use-inline-approvals.ts`.
- `buildResumeDecisions` requires a decision for every pending request
  before producing a payload (`approval-decisions.ts:63-65`) — the
  runtime resumes with the complete decision set.
- Delegation approvals reuse the block inside their own row
  (`delegation-tool-row.tsx:90-93`).
- Settled constraints (README): approvals render inline in the
  tool-row slot; native `<details>` stays for *collapsible* rows; users
  never see JSON; the target user is non-technical.

## Design decisions (this plan)

- **One click decides; nothing else to press.** "Approve & {verb}"
  commits that card's decision immediately. When it is the only (or
  last) undecided request, the client submits the full decision set
  right then — the approve click *is* the send. `ApprovalSubmitBar` and
  "Send Decisions" are **deleted, not restyled**.
  `shouldAutoSubmitDecisions` generalizes: submit whenever every
  pending request has a decision, denials included.
- **Decline is one confirm, because of the note.** Clicking "Decline"
  flips the card body to the optional "Tell the agent why" field with
  "Decline Request" (commits, same all-decided rule) and "Back"
  (returns to the undecided form, edits intact). Two clicks for
  decliners, one for approvers, zero global buttons.
- **Decided cards lock and say so.** After its click, a card renders a
  quiet decided state — "Approved ✓" / "Declined" with its final field
  values — and, when other requests in the turn remain undecided, one
  muted line: "Waiting for your decision on 1 more request." No
  un-stage/edit-after-decide: a decision is final at click time, like
  any SaaS confirm. (Multi-approval turns are rare; per-card finality
  beats reintroducing a review step for them.)
- **Awaiting approval is not a disclosure state — it's a card.** While
  undecided, the row renders as a bordered card in the same transcript
  slot (still "inline in the tool row" — the card *is* the row). No
  `<details>` while a decision is required; once the run resumes, the
  row reverts to the standard collapsible form (which 028 turns into
  the outcome row). This refines, not reverses, the "native `<details>`
  stays" decision — details remain the mechanism for every collapsible
  state.
- **Form-first order**: header (tool icon + `approval_title` +
  warning-tinted "Needs your approval" chip), optional one-line
  `approval_prompt` as muted supporting text, then **all arg fields in
  declared order** — editable inputs, selects, and read-only wells
  (026) interleaved; no separate read-only list above the block.
  Technical details are omitted from the conversation UI; declared fields are
  the complete user-facing review surface (maintainer correction, 2026-07-17).
- **Secondary fields** (025): empty → ghost "+ Add {label}" reveals the
  field; agent-supplied → renders normally; read-only secondary with no
  value stays hidden.
- **Footer**: right-aligned ghost "Decline" + filled primary
  `approve_label || "Approve"` (amber `default` variant — the surface's
  single primary action per the 001 token rules). In-flight: both
  disable, primary shows progress ("Approving…"), `aria-busy` set.
- **Delegation approvals use the same card** — task preview and tool
  name as read-only fields, no editable fields (settled, plan 022).
- **Width**: the card spans the transcript content width, capped at `max-w-3xl`
  after maintainer review so long requests stay readable without becoming a
  full-bleed banner.

## Steps

### 1. Decision flow: one-click submission

- `approval-decisions.ts`: replace `shouldAutoSubmitDecisions` with an
  all-decided check (submit when `summary.allDecided`, regardless of
  denials). `LocalApprovalDecision`, `buildResumeDecisions`, and
  `buildMergedArgs` stay unchanged — the payload contract is frozen.
- `use-inline-approvals.ts`: submit on any decision change that
  completes the set (approve click, or decline-confirm). Remove the
  bar-driven manual path. Submission failure surfaces as an inline
  destructive alert in the card region with "Try Again"; a failed
  submit must not lose the decision or the edits.
- Delete `approval-submit-bar.tsx` and its render site; knip must come
  up clean.

### 2. Card shell

- New `tool-approval-card.tsx` in
  `features/conversations/components/`: header (reuse `ToolUiIcon`,
  title from `approval_title || label`, chip on the `--warning` token),
  body slot, footer slot, decided-state variant. Plain `div` card
  (`bg-card border rounded-lg shadow-xs`), `border-warning/40` accent
  while undecided (precedent: `approval-decision-block.tsx:42`).
- `tool-call-row.tsx`: when `approvalDecision` is present, render the
  card path instead of `ToolActivityRowShell`, feeding it the field
  resolution the row already computes (`:70-84`). Rows without a live
  decision (history, other viewers) keep the standard rendering.

### 3. Body: unified fields

- Compose 026's `ToolField`/well primitives with editable inputs:
  iterate `ui.arg_fields` in declared order; `editable` → input seeded
  from args wired to `decision.edits` (reuse the handlers in
  `approval-decision-block.tsx:62-77`); `options.length > 0` → shadcn
  `Select` (vendor it if absent) staging the chosen string into
  `edits`; otherwise a read-only well. Fields not declared fall back to
  `autoUiFields` wells as today.
- Secondary-field "+ Add {label}" reveal: local state; revealing
  focuses the input; hiding again clears its edit.
- Decline flow: body swaps to `ApprovalDenialMessageField` + "Decline
  Request"/"Back".

### 4. Footer

- Extend `ApprovalDecisionButtons` (or fold it into the card footer)
  with `approveLabel`, in-flight, and decided states. The
  `aria-pressed` staging semantics leave with staging itself; the
  locked summary communicates the decided state.

### 5. Delegation

- `delegation-tool-row.tsx`: awaiting-approval delegation renders the
  card (task preview + tool as read-only fields); other states
  unchanged.

### 6. Tests & verify

- Rework `approval-decisions.test.ts` for the all-decided submit rule
  (denials auto-submit; partial sets never do). Merge/payload tests
  must pass **unchanged** — needing to edit one is a STOP condition,
  not a test update.
- `cd apps/web && pnpm check`.
- Manual QA (`pnpm dev`, agent with web_search on approval, both
  themes, desktop + mobile):
  - Single approval: card with title, chip, pre-filled query input,
    provider well; one click on "Approve & Search" resumes the run —
    no second button anywhere. Network tab: `override_args: null`
    untouched, merged object when edited.
  - Decline: Decline → note → "Decline Request" resumes with the
    denial; "Back" restores the form.
  - Two simultaneous approvals: first click locks its card with the
    waiting line; second click submits both. Mixed approve+decline
    submits with no extra step.
  - Submission failure (stop the API briefly): inline error + Try
    Again; nothing lost.
  - History after resolution: normal collapsible row.
  - Keyboard-only: tab order fields → Decline → Approve; Enter on the
    primary decides; typing never submits; "+ Add" is a real button.

## STOP conditions

- Any change is needed to `buildMergedArgs`, the resume payload shape,
  or the all-decisions-before-resume rule — stop; the flow change is
  client-side sequencing only.
- The runtime rejects a resume because per-card finality raced a new
  stream state (approvals list changed between click and submit) — stop
  and report; do not paper over with retries that could double-submit.
- The card cannot render in the tool-row slot without moving approval
  UI elsewhere in the transcript — stop; inline-in-slot is settled.
- A Select stages a value the tool's signature would reject (options
  drifted from the function) — stop and fix the backend declaration,
  not with client-side validation.
