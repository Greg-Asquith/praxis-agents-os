# Plan 018: Schedule form — create and edit wizards

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Updated**: 2026-07-16 (reconciled with completed plan 016 and the current
  working tree based on `01104f7`)
- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM — cadence and preview behavior are already correct and must
  not be rebuilt. The main risk is accidentally submitting during step
  navigation or changing time/cadence semantics while reorganizing the UI.
- **Depends on**: completed plan 016 (`FormWizard` and the Skill wizard
  configuration/test pattern). Can run in parallel with 017 because the plans
  touch separate feature directories and shared wizard changes are out of
  scope.

## Goal

Schedule creation and editing both become three-step wizards ending in a clear
review/options step. Successful creation and editing return to `/schedules`.
The detail page retains its operational actions and Run history tab but loses
the redundant saved banner and duplicate top-level back button.

Schedule names are user-authored and persisted. The Run step collects the name,
Review confirms it, and list/detail/breadcrumb/conversation surfaces use it as
the title while cadence remains separate timing information.

Carry forward every relevant implementation lesson from plan 016:

- Reuse `src/components/forms/form-wizard.tsx`; do not create another stepper.
- Use the wizard for edit as well as create.
- Next is a pure step transition. Preserve the shell's `preventDefault()` and
  distinct Next/Submit keys; do not recreate navigation buttons in the form.
- Filter the existing validation entries by `fieldId`. Final submit validates
  everything and returns to the earliest invalid step.
- Keep all form and preview-driving state above conditionally mounted steps.
- Successful create/edit returns to the list; no detail-page success banner.
- Remove the detail header's duplicate `Schedules` back button because the
  wizard footer already provides `Back to Schedules`.
- Keep header metadata compact by placing status badges inline with the title,
  not in a separate vertical row.
- Split the 268-line form into focused run, options/review, and wizard-config
  modules instead of making `schedule-form.tsx` larger.

### Completion amendment: persisted names

After the original wizard passed its UI-only gate, maintainer review identified
that the existing "Name" display was generated from cadence and duplicated the
adjacent Cadence column. The follow-up explicitly widened this plan across the
database and schedule API:

- a nullable `agent_schedules.name` column preserves existing rows without
  fabricating names from prompts or timing;
- new API-created schedules require a trimmed name of at most 255 characters;
- legacy rows read as "Unnamed schedule" until edited, and the edit wizard
  requires a real name before saving;
- schedule titles now use the persisted name everywhere, while cadence
  formatting is used only for timing information.

This amendment supersedes the original backend/API exclusion only for the
persisted name field. Worker execution, cadence, preview, and runtime semantics
remain unchanged.

## Current state (verified 2026-07-16)

- `src/components/forms/form-wizard.tsx` is the proven shared shell with
  responsive progress, native final submit, dirty gating, imperative
  `goToStep`, and corrected Next-to-final-step behavior.
- `features/schedules/components/schedule-form.tsx` (268 lines) is one long form
  using `FormActionBar`. Its Agent/Prompt section also contains Active and
  Allow external writes, followed by timing and `SchedulePreviewPanel`.
- `validateScheduleFormState` emits `schedule-agent`, `schedule-prompt`,
  `schedule-timezone`, `schedule-cron`, `schedule-interval`, and
  `schedule-once`.
- Cadence cards, cron builder, interval/one-time fields, timezone field, preview
  mutation, and error states already exist and are to be reused.
- `format.ts` formats persisted schedules; its cadence wording must not be
  duplicated for form-state review.
- `new-schedule-route.tsx` currently redirects successful creation to the new
  detail route.
- `schedule-detail-route.tsx` has a duplicate top `Schedules` button, separate
  status row, route `saved` state/banner, Settings/Run history tabs, and Pause,
  Enable, Run Now, and Delete actions.
- Reference implementation:
  `features/skills/components/skill-form.tsx`,
  `skill-form-wizard-config.ts`, and
  `tests/features/skills/components/skill-form-wizard-config.test.ts`.

## Scope

**In scope**:

- the nullable core migration and Schedule model/request/read/service name seam
- `apps/web/src/features/schedules/components/schedule-form.tsx`
- focused Schedule form review/options/config/format helpers under the same
  feature
- `apps/web/src/features/schedules/routes/new-schedule-route.tsx`
- `apps/web/src/features/schedules/routes/schedule-detail-route.tsx`
- Schedule wizard/format tests under
  `apps/web/tests/features/schedules/components/`

**Out of scope**:

- changes to `src/components/forms/form-wizard.tsx`
- API/backend scheduling semantics beyond the persisted name field, preview
  endpoint behavior, worker behavior, timezone/cadence contracts, or run history
- replacing the cadence cards, cron builder, or preview panel
- changing Pause/Enable, Run Now, Delete, or tab behavior
- introducing a form/schema library or duplicating validation/format rules

## Steps

### 1. Add a tested Schedule wizard configuration

Create `schedule-form-wizard-config.ts` following the Skill pattern. Both create
and edit use the same three typed steps:

1. `run` — **"What should run?"**; owns `schedule-name`, `schedule-agent`,
   and `schedule-prompt`.
2. `timing` — **"When should it run?"**; owns `schedule-timezone`,
   `schedule-cron`, `schedule-interval`, and `schedule-once`.
3. `review` — **"Review and options"**; no validation fieldIds; final submit.

The Agent select stays disabled in edit exactly as today, but it remains visible
on the Run step with its existing explanation.

Add `schedule-form-wizard-config.test.ts` mirroring the Skill test. Assert exact
step order for both modes, validation partitioning for every cadence fieldId,
unknown/undefined fallback to Run, and an empty Review partition.

**Verify**: `cd apps/web && pnpm test -- schedule-form-wizard-config` → new
tests pass.

### 2. Extract focused Run and Review/Options sections

Move Agent/Prompt UI out of `schedule-form.tsx` into a focused section. Move
Active and Allow external writes into a focused Review/Options section with
this outcome copy:

- Active: "Start running on schedule as soon as it's created. Turn this off to
  create or keep it paused."
- Allow external writes: "Let runs change connected apps or permanent files.
  Leave this off for read-only schedules."

The Review step shows read-only rows for:

- schedule name
- selected agent name/identity
- prompt
- cadence in plain language
- timezone
- the current preview result/next run times

Extract one form-state cadence formatter in the Schedule feature and share the
underlying wording with persisted-schedule formatting. Do not cast form state
to `AgentSchedule`, construct a fake schedule object, or fork cron/interval/
one-time wording. Add focused unit tests for recurring, interval, and one-time
review wording.

`SchedulePreviewPanel` stays on Timing so users can request/inspect upcoming
runs while configuring cadence. The Review step must reuse the current preview
result rather than issuing a surprise request on mount. If that requires
lifting preview result state or giving the panel a controlled seam, keep the
API call and error behavior unchanged and make the smallest focused extraction.
Do not silently hide stale, incomplete, or failed preview states.

**Verify**: `cd apps/web && pnpm test -- schedule-form && pnpm typecheck` →
focused tests and strict typecheck pass.

### 3. Convert create and edit to `FormWizard`

Replace `FormActionBar` with the shared `FormWizard` for both modes. Follow the
Skill form's navigation-ref and validation-step structure:

- Next validates only the active step.
- Final submit validates the whole form and navigates to the earliest invalid
  step before showing its validation summary/inline errors.
- Back and completed-step navigation preserve agent, prompt, cadence subtype,
  all subtype values, timezone, preview state, Active, and external-writes.
- Edit dirty gating disables Save Changes until a value differs.
- Submit labels: `Create Schedule` / `Save Changes`; pending labels:
  `Creating` / `Saving`; cancel target: `/schedules`.

Do not add autosave or submit-on-step-change behavior. Advancing from Timing to
Review must not call the mutation on the first visit, even though the primary
button at that DOM position changes from Next to Submit.

The prompt copy is: "This message starts every run, exactly as if you had typed
it to the agent."

**Verify**: `cd apps/web && pnpm test -- schedule-form-wizard-config && pnpm typecheck`
→ both pass.

### 4. Align completion and detail-page behavior

In `new-schedule-route.tsx`, navigate to `/schedules` after a successful create.
In `schedule-detail-route.tsx`, navigate to `/schedules` after a successful
update. Mutation failures remain in the wizard and must not navigate.

Remove route `saved` state, the "Schedule updated" banner, the form `onChange`
prop/callback, and unused imports. Remove the top `Schedules` button from the
detail header; the wizard footer provides the escape from Settings.

Move `ScheduleStatusBadges` alongside the title so status does not consume its
own row. Keep status semantics and operational action buttons unchanged. Keep
the Settings/Run history tabs; the wizard renders only inside Settings.

**Verify**: `cd apps/web && pnpm lint && pnpm typecheck` → exit 0 with no
warnings or errors.

### 5. Full verification

- `cd apps/web && pnpm check` passes.
- `git diff --check` passes.
- Confirm backend/API changes are limited to the persisted name seam and that no
  worker, preview, mutation-hook, run-history, or shared-wizard changes entered
  the diff.

Maintainer QA checklist (do not use automated browser tooling unless the
maintainer requests it):

- Create recurring, interval, and one-time schedules. Each reaches Review
  without submitting; summary wording and preview match the configured state.
- Mutation fires once only on `Create Schedule`, then returns to `/schedules`.
- Run blocks on missing agent/prompt. Timing blocks on the relevant cadence and
  timezone errors. Final validation returns to the earliest invalid step.
- Back/forward retains subtype-specific values, timezone, options, and the
  current preview/error state.
- Edit uses the same three steps, keeps Agent locked, dirty gating works, Save
  returns to `/schedules`, and no success banner or duplicate header back button
  remains.
- Settings and Run history tabs, Pause/Enable, Run Now, Delete, and error
  handling remain intact.
- Desktop/mobile, both themes, keyboard-only focus and radio-group semantics.

## Done criteria

- [x] Create and edit both use the same three-step wizard structure.
- [x] Timing never auto-saves/submits when Review is first entered.
- [x] Existing validation, cadence, timezone, preview, and payload behavior is
      reused rather than forked.
- [x] Review has human-readable agent, prompt, cadence, timezone, preview, and
      options without fake schedule objects or duplicated format rules.
- [x] Schedule names are user-authored, persisted, validated, and used for every
      title surface; legacy rows remain explicitly unnamed until edited.
- [x] Successful create and edit both return to `/schedules`.
- [x] Edit has no saved banner, duplicate top back button, or separate status
      row.
- [x] The form is decomposed into focused orchestration/config/section modules.
- [x] Focused wizard/format tests and full `pnpm check` pass.

## STOP conditions

- Human cadence wording cannot be shared between form state and persisted
  schedules without changing observable wording — stop and propose the seam;
  do not duplicate it.
- Preview state cannot persist from Timing to Review without changing endpoint
  semantics or hiding current errors — stop and report.
- Per-step gating requires validation rules outside
  `validateScheduleFormState` — stop; do not duplicate rules.
- Correct completion navigation would require changing mutation/API contracts —
  stop; route-level navigation should be sufficient.
- The work requires modifying `FormWizard` to work around consumer logic — stop
  and report the exact incompatibility before changing the shared primitive.
