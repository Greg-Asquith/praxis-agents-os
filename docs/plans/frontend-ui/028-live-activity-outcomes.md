# Plan 028: The live activity card — every tool, the whole lifecycle

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-17, anchors verified against the working tree at
  `19ace81` with plan 022 applied. Part of the tool-surface series —
  see the series preamble in plan 025. Scope per maintainer direction
  (2026-07-17): the dashboard treatment covers the **entire tool
  process** — auto-run tools included — not only approvals.
- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM — presentation plus one client-side timer and
  default-open behavior in the live transcript. The timer touches the
  `useEffect` policy; it qualifies as external-system sync (an
  interval) and must be justified in plan-014 style. The main product
  risk is noise: rich cards must not turn a 15-tool run into 15
  billboards.
- **Depends on**: 026 (field wells), 027 (card shell — reused here).
  Web-only.

## Goal

Approval or not, a tool call should feel like the agent doing real work
in front of you. Today an auto-run tool is a gray one-line `<details>`
row with a spinning dashed circle (`tool-activity-status.tsx:25-29`) —
plain, static, identical whether it is running or long finished until
opened. The target: while a tool runs in the live conversation it
renders as an **activity card** — the 027 shell with the tool's icon,
its arg fields as labeled wells, a moving status line, an elapsed
count — and when it finishes it settles into a compact **outcome row**
that leads with what happened ("Searched the Web for UK pricing · ✓"),
expandable to the full field view, outcome first. The transcript reads
like a job dashboard: one live card, a tidy list of finished work above
it. Plan 029 then makes those outcomes actionable; this plan gives them
their shape.

## Current state (verified 2026-07-17, working tree at `19ace81` + 022)

- Statuses: `running | awaiting_approval | completed | failed | unknown`
  (`message-parts/types.ts:16`). Args arrive **whole** with the
  tool-call stream event — the reducer assigns `args` once
  (`stream/reducer.ts:163,189,206`); the protocol has no incremental
  arg streaming.
- Status labels come from presentation templates
  (`tool-ui.ts:116-127`); icon/color from
  `ActivityStatusIcon`/`statusColor`
  (`tool-activity-status.tsx:18-47,63-74`) — running is muted-gray +
  `animate-spin`, completed a green check, failed a red triangle.
- All non-approval rows render collapsed regardless of status
  (`tool-call-row.tsx:49` opens only approvals); open-state order is
  args → results → technical (`:108-121`).
- No timing is shown anywhere; `ToolActivity` does not expose call
  timestamps.
- Live-run awareness exists (`live-activity-visibility.ts`) — the
  transcript knows which activities belong to the in-flight run.
- Custom presenter rows (todo, files, skills, delegation —
  `tool-call-row-registry.tsx:52-91`) bypass the default row entirely.

## Design decisions (this plan)

- **Card while active, row when done.** In the live run, a `running`
  activity (without a custom presenter) renders as the 027 card shell —
  header with tool icon + running label, body of resolved arg-field
  wells, no footer actions. On completion/failure it transitions to the
  compact row. Historical transcripts and `compact` contexts always use
  rows. One rich card per running tool; transcripts never bloat.
- **Liveness without protocol changes.** Args arrive whole, so no fake
  "typing" animation and no SSE work. Liveness = a subtle CSS shimmer
  on the running status line (disabled under
  `prefers-reduced-motion`), arg wells visible at a glance, and an
  elapsed-time suffix ("· 12s").
- **Elapsed time is client-measured and live-run only.** The clock
  starts when the running activity first appears in the live stream;
  history shows nothing — never fabricate timing on replay. Persisted
  call timings would be a separate backend vertical.
- **Outcome rows lead with the outcome.** Collapsed: `completed_label`
  template + green check, plus a right-aligned outcome metric when the
  first declared result field resolves short (the README's "calm,
  scannable rows: title, right-aligned outcome metric"). Open: result
  fields render **before** arg fields; `url` result fields also render
  as a small outline action button ("Open File"), mirroring
  delegation's "Open Transcript"
  (`delegation-tool-row.tsx:125-135`).
- **Failed calls get the plain-language treatment.** Live failed
  activities open by default: a destructive-accented "What went wrong"
  field (026) with one line of framing — "The agent saw this error and
  can adjust." Raw output stays in Technical details. Historical failed
  rows stay collapsed but show the same content when opened.
- **No new status taxonomy**; denied/unknown keep current treatment.

## Steps

### 1. Elapsed timer

- Hook `use-elapsed-seconds.ts` in `features/conversations/hooks/`:
  given `running: boolean`, ticks a 1s interval while true (effect
  justified as timer sync; cleared on stop/unmount). Render the tick in
  a leaf component so long transcripts do not re-render per second.
- Surface through `ActivityStatusSuffix`
  (`tool-activity-status.tsx:49-61`) as muted "· {n}s", gated to
  live-run activities via the live-activity visibility plumbing. Wire
  into `delegation-tool-row.tsx` for running delegations too.

### 2. Running card

- `tool-call-row.tsx`: live `running` activities render the 027 card
  shell (no footer) with `ToolFieldGrid` arg wells. The shimmer utility
  lands in `src/index.css` (tokens only,
  `@media (prefers-reduced-motion: reduce)` guard) and applies to the
  running headline. Non-live or `compact` running activities keep the
  current one-liner, spinner intact.
- The card→row transition on completion must not jump the scroll
  position in the pinned-to-bottom transcript.

### 3. Outcome rows

- Reorder open-state content for completed activities: result fields,
  result text, arg fields, technical (`tool-call-row.tsx:108-121`).
- Collapsed suffix: when the first declared result field resolves to
  ≤ ~40 chars, show it as the right-aligned metric via
  `ActivityStatusSuffix`; otherwise just the check.
- `url`-format result fields render the outline action-button variant
  of the 026 link treatment (`ExternalLinkIcon` + field label).

### 4. Failed treatment

- Live failed activities get `defaultOpen={true}`; add the framing line
  + destructive-labeled error field sourced from
  `friendlyResultText(activity.result)` when present, otherwise the
  framing line alone with detail left to Technical details.

### 5. Verify

- `cd apps/web && pnpm check`.
- Manual QA (`pnpm dev`, both themes; web_search for a slow call, a
  missing-file read for failure):
  - Running: full card with wells, shimmering label, counting suffix;
    on completion it settles into the compact outcome row and the
    timer disappears (no stale "14s" beside the check).
  - A run with several sequential calls stays readable: finished rows
    compact, only the active call is a card.
  - Reduced motion: no shimmer; spinner unchanged from today.
  - Completed web_search open: Answer before Search; the collapsed
    metric appears only when short.
  - Failed: opens itself live with plain-language framing; raw detail
    only under Technical details.
  - Refresh mid-run: rows only, no elapsed suffix, no cards for
    finished calls.
  - Scroll position holds through card→row transitions.

## STOP conditions

- The timer or shimmer causes visible re-render jank in long
  transcripts — stop and isolate the ticking component; never ship a
  per-second full-list render.
- You find yourself adding timing fields to the SSE protocol or run
  persistence — stop; that is a backend vertical.
- The card→row transition fights the user (rows they expanded collapse
  on stream events, or scroll jumps) — stop and report; user intent and
  reading position win over liveness.
- A custom presenter row (todo, files, skills) needs restructuring to
  fit — stop; aligning those is plans 029/031, not this one.
