# Plan 018: Schedule form — create wizard & edit clarity

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-16 (anchors verified against the live tree at
  `9d597e1` with plan 013 applied)
- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM — scheduling is the surface where a wrong abstraction
  bites hardest (a schedule that silently fires at the wrong time). The
  cadence/preview machinery already exists and is good; this plan
  repackages it, it does not rebuild it.
- **Depends on**: 016 (wizard shell). Can run in parallel with 017 —
  disjoint feature directories.

## Goal

Schedule creation becomes a **three-step wizard** ending in a review
screen — for a non-technical user, "check what will happen before it
starts happening" is the single most valuable screen in this whole
series. The edit page gets its options untangled from the prompt
section. Follows 016's wizard design language.

## Current state (verified 2026-07-16)

- `features/schedules/components/schedule-form.tsx` (309 lines): one
  "Agent and prompt" section that also hides two raw checkboxes —
  Active (lines 217-233) and "Allow external writes" (lines 235-251) —
  under the prompt; then `ScheduleTimingSection` (cadence radio cards +
  per-type fields + timezone) and `SchedulePreviewPanel` (live next-run
  preview from the preview endpoint).
- The cadence UX is already non-technical-friendly: three card options
  "Recurring / Interval / One-time" (`schedule-cadence-field.tsx`), a
  no-syntax cron builder (`schedule-cron-advanced-builder.tsx`), and
  the preview panel. Keep all of it.
- `validateScheduleFormState` (`schedule-form-model.ts`) emits fieldIds
  `schedule-agent`, `schedule-prompt`, `schedule-timezone`,
  `schedule-cron`, `schedule-interval`, `schedule-once` — a clean
  two-step partition plus a free review step.
- Edit mode locks the agent (select disabled with "Existing schedules
  keep their original agent", `schedule-form.tsx:151-195`).
- Routes: `new-schedule-route.tsx` (bare header — it has no description
  line today), `schedule-detail-route.tsx` with header actions
  (Pause/Enable, Run Now, Delete) and Settings / Run history tabs
  (lines 187-213).
- `features/schedules/format.ts` has `formatScheduleCadence` — already
  used by the detail route header for a human-readable cadence.

## Steps

### 1. Create wizard — three steps

Convert `schedule-form.tsx`'s create mode to `FormWizard`:

1. **"What should run?"** — agent select + prompt (fieldIds
   `schedule-agent`, `schedule-prompt`). Prompt description stays
   outcome-shaped: "This message starts every run, exactly as if you
   had typed it to the agent."
2. **"When should it run?"** — cadence cards, the per-type fields,
   timezone, **with the live preview panel on this step** (fieldIds
   `schedule-timezone`, `schedule-cron`, `schedule-interval`,
   `schedule-once`). Seeing "Next runs: …" update while picking the
   cadence is the abstraction — nobody has to understand cron.
3. **"Review"** — read-only summary plus the two options:
   - Summary rows: agent (name + identity icon via the existing agent
     select item pieces or a plain row), the prompt, the cadence in
     words (derive from form state; `formatScheduleCadence` works on a
     schedule object — reuse its wording, executor picks the clean
     seam), and the preview panel's next few run times.
   - Options, as the only inputs on the step: **Active** (checked by
     default) — "Start running on schedule as soon as it's created.
     Uncheck to create it paused." — and **Allow external writes** —
     "Let runs make changes outside this workspace, like updating
     connected apps or permanent files. Leave off for read-only
     schedules." No fieldIds; submit reads "Create Schedule".

### 2. Edit page — untangle the options

Edit mode stays one page on the 015 kit:

- **"Agent and prompt"** slims to exactly that: locked agent + prompt.
- **New "Options" section** (last, after timing + preview) holding the
  Active and external-writes checkboxes with the step-3 copy above.
- Timing section and preview panel unchanged.
- Route-level pieces (tabs, header actions, saved alert) untouched.

### 3. Verify

- `cd apps/web && pnpm check` passes.
- Manual QA against `pnpm dev`, both themes, desktop + mobile:
  - Create one schedule of **each cadence type** (recurring, interval,
    one-time) through the wizard; the review step's cadence wording and
    next-run preview match what the detail page then shows.
  - Step 1 blocks on missing agent/prompt; step 2 blocks per cadence
    type (bad cron, empty interval, past/missing one-time date) and on
    timezone; Back/forward retains cadence choices and field values.
  - An unchecked Active on review creates a paused schedule; Enable on
    the detail page starts it.
  - Edit: options section saves both flags; dirty gating and the locked
    agent notice unchanged; Run history tab intact.
  - Keyboard-only wizard pass; focus visible; the cadence radio cards
    remain reachable and announce state (`role="radiogroup"` already
    exists — keep it working).

## STOP conditions

- The review step cannot get human cadence wording from form state
  without duplicating `formatScheduleCadence`'s rules — stop and
  propose the extraction rather than forking the wording.
- The preview panel misbehaves when mounted on a wizard step (e.g.
  fires requests for incomplete state it previously never saw) — stop
  and report; do not suppress its error states to make the step look
  clean.
- Per-step gating can't be built by filtering
  `validateScheduleFormState` entries by fieldId — stop; do not
  duplicate rules.
