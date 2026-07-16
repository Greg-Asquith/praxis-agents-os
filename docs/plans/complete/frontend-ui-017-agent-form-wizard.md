# Plan 017: Agent form — create and edit wizards

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Verification**: `cd apps/web && pnpm check` passed (23 test files,
  116 tests); `git diff --check` passed. Browser automation was intentionally
  not used per maintainer instruction.
- **Implementation note**: Maintainer review simplified model choices to
  human-readable names with the workspace default selected for new agents and
  requested wrapped, vertically centered wizard labels. The shared wizard
  received that narrowly scoped presentation refinement; validation,
  navigation, and submit behavior are unchanged. Skills now sit with identity
  and instructions on the Profile step; the optional Collaboration step is
  reserved for delegation. Agent slugs are now entirely system-managed and
  absent from user-facing forms, headers, lists, and pickers.
- **Updated**: 2026-07-16 (reconciled with completed plan 016 and the current
  working tree based on `01104f7`)
- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM — the agent form spans profile, model configuration, tool
  policy, skills, delegation, and availability. The shared wizard is already
  proven; the risk is preserving every field and tool-policy behavior while
  decomposing the form.
- **Depends on**: completed plan 016 (`FormWizard` and the Skill wizard
  configuration/test pattern). Can run in parallel with 018 because the plans
  touch separate feature directories and shared wizard changes are out of
  scope.

## Goal

Agent creation becomes a four-step wizard and agent editing becomes a five-step
wizard using the same state model, payload builders, and validation rules.
Successful creation and editing return to `/agents`. The detail page no longer
shows a redundant success banner or a duplicate top-level back button.

The result must carry forward the implementation lessons from plan 016:

- Reuse `src/components/forms/form-wizard.tsx`; do not build another stepper.
- Both create and edit use the wizard. Editing must not fall back to a long
  form.
- Next is never a native submit. The shared shell already prevents the click's
  default action and gives Next and Submit distinct React keys; preserve this.
- Per-step validation filters the existing validation entries by `fieldId`.
  Final submit runs full validation and sends the user to the earliest invalid
  step.
- Form state lives above step content so unmounting a step loses nothing.
- Successful create/edit navigates to the list. Do not remount the edit form or
  show an "Agent updated" banner first.
- The wizard footer is the list escape. Remove the duplicate `Agents` button
  from the edit-page header.
- Keep headers compact: routine status metadata sits beside the name. Do not
  spend a separate row on an Active badge.
- Split orchestration, step configuration, and focused sections instead of
  growing `agent-form.tsx` or `agent-runtime-section.tsx` into god components.

## Current state (verified 2026-07-16)

- `src/components/forms/form-wizard.tsx` is the shared, generic wizard. It
  exposes `FormWizardNavigation.goToStep`, accepts a form id and dirty-submit
  gating, renders responsive progress, and contains the corrected
  Next-to-final-step behavior.
- `features/agents/components/agent-form.tsx` (188 lines) renders one long form
  with `FormActionBar`. It owns state, payload construction, dirty gating, and
  all-form validation.
- `agent-runtime-section.tsx` (228 lines) combines model fields, advanced
  runtime fields, Availability/Favorite, and `AgentToolsSection`.
- `validateAgentFormState` in `agent-form-model.ts` emits `agent-name`,
  `agent-slug`, `agent-instructions`, `agent-max-steps`, and `agent-model`.
- `new-agent-route.tsx` currently navigates successful creation to the new
  agent detail route.
- `agent-detail-route.tsx` has a duplicate top `Agents` button, a separate row
  of status/slug badges, `saved` state, an "Agent updated" banner, and an
  `onChange` callback used only to clear that banner.
- The reference implementation is the completed Skill flow:
  `features/skills/components/skill-form.tsx`,
  `skill-form-wizard-config.ts`, and
  `tests/features/skills/components/skill-form-wizard-config.test.ts`.

## Scope

**In scope**:

- `apps/web/src/features/agents/components/agent-form.tsx`
- focused Agent form section/config modules under the same directory
- `apps/web/src/features/agents/routes/new-agent-route.tsx`
- `apps/web/src/features/agents/routes/agent-detail-route.tsx`
- Agent wizard tests under `apps/web/tests/features/agents/components/`

**Out of scope**:

- `src/components/forms/form-wizard.tsx` behavior or styling; plan 016 already
  fixed and verified it
- API contracts, mutation implementations, runtime tool semantics, model
  catalog behavior, delegation rules, or backend code
- changing `AgentStatusBadges` in tables; compact the detail header locally so
  list status remains explicit
- introducing a form/schema library or duplicating validation rules

## Steps

### 1. Add a tested Agent wizard configuration

Create `agent-form-wizard-config.ts` following the Skill configuration pattern.
It owns typed create/edit step arrays, the fieldId-to-step map, a helper that
filters `FormValidationEntry[]` for a step, and `stepForAgentField` for final
validation recovery.

Create steps:

1. `profile` — **"Who is this agent?"**; owns `agent-name`, `agent-slug`, and
   `agent-instructions`.
2. `model` — **"How should it think?"**; owns `agent-model` and
   `agent-max-steps`.
3. `tools` — **"What can it use?"**; no validation fieldIds.
4. `collaboration` — **"Who can it work with?"**, optional; Skills and
   Delegation; no validation fieldIds.

Edit uses those four steps plus a final `availability` step named
**"Availability"**. The final edit submit therefore cannot appear on Tools or
Collaboration.

Add `agent-form-wizard-config.test.ts` mirroring the Skill test. Assert exact
create/edit step order, validation partitioning, unknown/undefined field
fallback to Profile, and that active/not-favorite defaults remain outside the
create steps.

**Verify**: `cd apps/web && pnpm test -- agent-form-wizard-config` → the new
tests pass.

### 2. Split model, tools, collaboration, and availability UI

Refactor the current `AgentRuntimeSection` so focused pieces can be mounted by
wizard step without copying fields:

- Model section: Model plus a native `<details>` Advanced disclosure containing
  Thinking, Max steps, and conditional Azure deployment.
- Tools section: reuse `AgentToolsSection` unchanged mechanically; only update
  its introductory copy.
- Collaboration section: compose the existing Skills and Delegation components,
  both explicitly optional.
- Availability section: Availability and Favorite, edit-only.

Advanced is closed by default. If `agent-max-steps` fails validation, open it
before showing/focusing the error; an error link into closed content is not
acceptable. Keep this disclosure state above the conditionally mounted step if
needed so Back/Next does not reset it unexpectedly.

Availability copy must state outcomes: inactive agents cannot start new runs or
receive delegated work, while existing history remains. Favorite is an
organizational shortcut, not runtime behavior.

Do not move field state into the section components. `agent-form.tsx` remains
the single state and submit orchestrator, but should become smaller through
composition.

**Verify**: `cd apps/web && pnpm typecheck` → exit 0 with strict TypeScript.

### 3. Convert create and edit to `FormWizard`

Replace `FormActionBar` in `agent-form.tsx` with the shared `FormWizard` for
both modes. Follow Skill's `useRef<FormWizardNavigation<...>>` and
`validationStep` structure:

- Next validates only the active step.
- Final submit validates the entire form, navigates to the earliest invalid
  step, and displays only that step's validation entries.
- Back and completed-step navigation preserve name, instructions, model,
  advanced values, tool modes, skills, and delegates.
- Create excludes Availability/Favorite and relies on existing defaults.
- Edit dirty gating disables Save Changes until something differs.
- Submit labels are `Create Agent` and `Save Changes`; pending labels are
  `Creating` and `Saving`; cancel targets `/agents`.

Copy requirements:

- Tools: explain a tool in one sentence. "Approval means a person confirms each
  use before it runs. You can change this later."
- Max steps: "The most actions one run may take before it stops."
- Thinking: explain the outcome without assuming knowledge of extended
  thinking.
- Delegation: "Let this agent hand work to other agents during a run."

Do not add a form-level effect or autosave. Moving between steps must never call
the mutation. In particular, advancing from Tools to Collaboration must not
submit simply because the same DOM position becomes the final button.

**Verify**: `cd apps/web && pnpm test -- agent-form-wizard-config && pnpm typecheck`
→ both commands pass.

### 4. Align completion and detail-page behavior

In `new-agent-route.tsx`, navigate to `/agents` after a successful mutation.
In `agent-detail-route.tsx`, navigate to `/agents` after a successful update.
Mutation errors still remain in the form and must not navigate.

Remove `saved`, the "Agent updated" alert, the form `onChange` prop/callback,
and any now-unused imports. Remove the top `Agents` back button from the detail
header because `Back to Agents` remains in the wizard footer.

Compact the identity header: icon and name remain primary; slug, Favorite, and
an exceptional Inactive badge sit inline after the name. Do not show a routine
Active badge in the detail header. Keep delete behavior and delete errors
unchanged.

**Verify**: `cd apps/web && pnpm lint && pnpm typecheck` → exit 0 with no
warnings or errors.

### 5. Full verification

- `cd apps/web && pnpm check` passes.
- `git diff --check` passes.
- Confirm the diff contains no backend/API/runtime changes and no changes to
  the shared wizard.

Maintainer QA checklist (do not use automated browser tooling unless the
maintainer requests it):

- Create with only required Profile data and defaults; Next through all steps;
  mutation happens once, only on `Create Agent`, then route is `/agents`.
- Empty name/instructions block Profile. Invalid max steps opens Advanced on
  Model. Final-submit validation returns to the earliest invalid step.
- Back/forward retains every field, tool mode, attached skill, and delegate.
- Edit uses all five steps, dirty gating works, Save mutates once and returns to
  `/agents`; no success banner or duplicate header back button appears.
- Mutation failure stays on the active wizard with a useful error.
- Desktop/mobile, both themes, keyboard-only focus and progress semantics.

## Done criteria

- [x] Create is a four-step wizard; edit is a five-step wizard.
- [x] Existing validation/payload/tool/delegation behavior is reused, not forked.
- [x] Next never submits; only the final primary action mutates.
- [x] Final validation routes to the earliest invalid step.
- [x] Successful create and edit both return to `/agents`.
- [x] Edit has no saved banner, duplicate top back button, or routine Active
      badge row.
- [x] Agent form orchestration and focused sections are split cleanly.
- [x] Focused wizard-configuration tests and full `pnpm check` pass.

## STOP conditions

- Tool, skill, or delegation behavior cannot survive conditional step mounting
  without changing its public/runtime semantics — stop rather than fork it.
- Per-step gating requires validation rules outside
  `validateAgentFormState` — stop; do not duplicate rules.
- Native `<details>` cannot be opened when a contained field fails — stop and
  report before replacing the settled disclosure pattern.
- Correct completion navigation would require changing mutation/API contracts —
  stop; route-level navigation should be sufficient.
- The work requires modifying `FormWizard` to work around consumer logic — stop
  and report the exact incompatibility before changing the shared primitive.
