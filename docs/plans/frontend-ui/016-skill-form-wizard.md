# Plan 016: Skill form — create wizard (builds the shell) & edit clarity

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
- **Risk**: MEDIUM — introduces the shared wizard shell every create
  flow will use. The skill form is the smallest of the three, which is
  exactly why it goes first: prove the shell on the simplest consumer
  before the agent form's six sections lean on it.
- **Depends on**: 015 (form kit). 017 and 018 depend on this plan's
  wizard shell.

## Goal

Skill creation becomes a **three-step wizard** that a non-technical user
can walk through without meeting a single concept they don't need yet.
Skill editing stays a single sectioned page (015 already gave it air)
and gets a plain-language copy pass.

Design language for every wizard in this series (016–018):

- Step titles are **plain questions or plain nouns**, not system nouns.
- One primary action per screen: **Next** (amber), with **Back**
  (outline) beside it and Cancel available at all times.
- Optional steps say they are optional and can be skipped without guilt
  ("You can add these later").
- Anything with a safe default does not appear in the create flow at
  all — it lives on the edit page. Fewer decisions, better defaults.

## Current state (verified 2026-07-16)

- `features/skills/components/skill-form.tsx` (450 lines) renders both
  modes as one long page: Identity (name `skill-name`, description
  `skill-description` — lines 148-194), Instructions
  (`skill-instructions` — lines 196-221), pending reference documents
  (create-only, lines 223-228 and the `PendingSkillDocumentsSection` at
  325-450), and Availability (Status + Favorite selects, lines
  230-276).
- The form model (`skill-form-model.ts`) already defaults `isActive` to
  `"true"` and `isFavorite` to `"false"`, and
  `validateSkillFormState` returns `FormValidationEntry` rows keyed
  `skill-name` / `skill-description` / `skill-instructions` — the
  per-step partition falls out of the existing `fieldId`s.
- `features/skills/routes/new-skill-route.tsx` owns document upload
  after create (lines 36-92) and a post-create warning state
  (lines 109-129) when uploads fail.
- `features/skills/routes/skill-detail-route.tsx` passes
  `SkillDocumentsSection` as children into the edit form (lines
  109-123).

## Steps

### 1. Build the wizard shell: `src/components/forms/form-wizard.tsx`

`FormWizard` is a presentational step machine. Validation stays owned by
the form component — the shell never learns entity rules.

- **Props**: `steps: { id, title, description?, optional? }[]`,
  `children` (the active step's content — either a render-prop of the
  active step id or per-step slots; executor picks the cleaner
  TypeScript), `validateStep: (stepId) => boolean` (form component
  validates just that step and surfaces its own inline errors; returns
  whether advancing is allowed), `onSubmit`-through-native-form (the
  final step's primary button is `type="submit"` for the surrounding
  `<form>`), `isSubmitting`, `submitLabel`, `pendingLabel`,
  `cancelLabel`, `cancelTo`.
- **Step gating**: the shell owns the active index. Next calls
  `validateStep`; Back always works; clicking a *previous* step in the
  progress header jumps back; forward jumps only happen through Next.
  Step content may unmount freely — all field state lives in the form
  state object above the wizard, so Back/Next loses nothing.
- **Progress header**: an `<ol>` of numbered markers — completed steps
  get a check on the amber token, the current step an amber ring and
  `aria-current="step"`, future steps stay muted. Titles beside markers
  on `sm:` and up; below `sm` it compresses to "Step 2 of 3" plus the
  current title. Tokens only; both themes.
- **Layout**: wizard content column at `max-w-3xl` centered. Controls
  row: Back (outline, hidden on step 1), then right-aligned Cancel
  (ghost, links to `cancelTo`) and Next / submit (default amber).
  Respect `prefers-reduced-motion` if any step transition is animated —
  a plain swap is fine.
- **Per-step validation mechanics** (in the consuming form, but
  standardized here): each wizard declares which `fieldId`s belong to
  each step; `validateStep` runs the existing full-form validate
  function and filters entries to the step's ids
  (`lib/forms.ts` `FormValidationEntry.fieldId` is the join key). The
  final step's submit still runs full validation as a safety net; if an
  earlier step somehow fails, jump to the earliest failing step and show
  its errors rather than submitting.

### 2. Convert skill create to the wizard

In `skill-form.tsx` (create mode only — the edit branch keeps the
single-page layout):

1. **"What does this skill do?"** — Name + Description
   (`skill-name`, `skill-description`). Keep the existing descriptions;
   they already explain that agents pick skills from these two fields.
2. **"How should it work?"** — Instructions (`skill-instructions`).
   The `min-h-80` editor gets the step to itself.
3. **"Reference documents"** — the pending-documents picker, marked
   optional ("Optional — you can add documents any time after
   creating"). No fieldIds; Next is never blocked here. Final step:
   submit button reads "Create Skill".

Remove the Availability section from the create flow entirely
(`skill-form.tsx:230-276` stays for edit mode only) — the model already
defaults new skills to active and not-favorite; those are post-creation
concerns. The post-create upload and warning flow in
`new-skill-route.tsx` is untouched.

### 3. Edit-page clarity pass

Edit mode keeps its sections (Identity, Instructions, Documents,
Availability) on the 015 kit. Copy pass for the non-technical reader:
section descriptions state outcomes, not mechanisms — e.g. Availability
becomes "Control whether agents can be given this skill"; Status/
Favorite field descriptions say what changes for the user, one short
sentence each. No structural change.

### 4. Verify

- `cd apps/web && pnpm check` passes (knip: `FormWizard` has a consumer;
  no orphaned exports).
- Manual QA against `pnpm dev`, both themes, desktop + mobile:
  - Create: step 1 blocks on empty name/description with inline errors;
    step 2 blocks on empty instructions; Back from step 3 to step 1 and
    forward again preserves every field; documents added on step 3
    upload after create; the upload-failure warning path still renders.
  - Progress header: markers/labels correct, back-jump via header works,
    mobile compresses to "Step n of 3".
  - Edit: unchanged behavior — dirty gating, save, documents section,
    "Skill updated" alert on the route.
  - Keyboard-only pass through the whole wizard; focus visible on every
    control.

## STOP conditions

- Per-step gating cannot be expressed by filtering
  `validateSkillFormState` entries by `fieldId` without duplicating
  validation rules — stop; do not fork the model.
- The shell design drifts toward a form/schema library or toward owning
  entity validation — both are forbidden; stop and report.
- The create/edit split forces `skill-form.tsx` into two components that
  no longer share the form model and payload builders — sharing those is
  the point; stop and report the coupling problem instead.
