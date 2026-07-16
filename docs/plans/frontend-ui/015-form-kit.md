# Plan 015: Form kit — shared sections, action bar, and alerts

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-16 (anchors verified against the live tree at
  `9d597e1` with plan 013's then-uncommitted label sweep applied — land
  013's commit before starting)
- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM — pure extraction plus spacing. No validation,
  payload, or submission logic changes. Main hazard is subtle prop drift
  while merging three near-identical copies of the same scaffolding.
- **Depends on**: 011 (landed), 013 (in tree; commit first). This is the
  foundation for 016–018 (the per-entity form redesigns) — nothing else
  runs against these files until this lands.

## Goal

Maintainer directive (2026-07-16): the Agent, Skill, and Schedule forms
are the worst surfaces in the app. Create flows become **wizards**; edit
flows stay single pages but get **clearer sections and more breathing
room**; all three share one consistent look and feel. And the governing
product constraint: **the target user is not necessarily technical** —
abstract complexity away wherever possible.

This series is four plans, executed one at a time:

- **015 (this plan)** — extract the shared form kit and apply the
  spacing/clarity baseline to all three forms. No behavior change.
- **016** — Skill form: builds the create-wizard shell and converts the
  skill create flow (smallest form proves the shell).
- **017** — Agent form: create wizard + edit clarity.
- **018** — Schedule form: create wizard + edit clarity.

## Current state (verified 2026-07-16)

The three forms triplicate the same scaffolding, drifting slightly:

- **Section wrapper ×3, near identical** — `bg-card rounded-md border
  p-4` with an eyebrow/title/description header (`mb-4`):
  `features/agents/components/agent-form-section.tsx` (27 lines),
  `features/skills/components/skill-form-section.tsx` (27 lines),
  `features/schedules/components/schedule-form-section.tsx` (32 lines —
  the only one with an optional `icon` slot).
- **Sticky action bar ×3, byte-for-byte styling** — the
  `sticky -bottom-6 … backdrop-blur` bar with the dirty-state message,
  outline Cancel, and amber submit with pending swap:
  `agent-form-shell.tsx:68-96`, `skill-form.tsx:281-320` (this one
  targets the form via `form={formId}` because the skill edit page
  renders `props.children` between form and bar — `skill-form.tsx:62,279,303`),
  `schedule-form.tsx:268-306`.
- **Error + validation alert pair ×3** — a destructive "not saved" alert
  plus a "Review required fields" list whose entries anchor-link to
  `#fieldId`: `agent-form-shell.tsx:44-64`, `skill-form.tsx:126-146`,
  `schedule-form.tsx:121-141`.
- **Density** — form pages stack sections at `gap-4`
  (`agent-form.tsx:124`, `skill-form.tsx:117-119`,
  `schedule-form.tsx:115`), sections pad at `p-4`, headers sit at
  `mb-4`. Six sections of the agent form run together with no room to
  scan.
- The validation seam the wizard will build on already exists and is
  shared: `lib/forms.ts:14` (`FormValidationEntry` =
  `{fieldId, label, message}`) and `buildFieldErrors` (`lib/forms.ts:20`).
  Do not touch it in this plan.

## Steps

### 1. Create `src/components/forms/`

A new directory for app-specific shared form scaffolding. It is **not**
`components/ui/` (that stays vendored shadcn output) and it must not
import from `src/features/` — entity data arrives via props; keep it as
generic as `components/ui` in practice even though no depcruise rule
polices this directory yet. Three components:

- **`form-section.tsx`** — `FormSection`, the superset of the three
  wrappers: `{ eyebrow, icon?, title, description, id?, children }`
  (`icon` from the schedule variant; `id` so later plans can anchor
  section jumps). New spacing: card padding `p-5 sm:p-6`, header block
  `mb-6` with `gap-1.5`. Keep `bg-card rounded-md border` — form
  sections keeping their card surface is a settled decision from
  plan 011.
- **`form-action-bar.tsx`** — `FormActionBar`:
  `{ stateMessage, cancelLabel, cancelTo, submitLabel, pendingLabel,
  isSubmitting, disableSubmit, form? }`. Markup and classes lifted from
  the current triplicate, icons included (`CheckIcon` idle, `SaveIcon`
  pending). The optional `form` prop preserves the skill form's
  external-submit wiring.
- **`form-alerts.tsx`** — `FormAlerts`:
  `{ errorTitle, error, validationEntries }`, rendering the destructive
  error alert and the "Review required fields" list with its `#fieldId`
  anchor links, exactly as today.

Do **not** add the wizard shell in this plan — knip fails `pnpm check`
on unused exports, so the shell ships with its first consumer (plan 016).

### 2. Rewire the three forms; delete the four dead files

- `agent-form.tsx` / the five agent section components switch to
  `FormSection`; `agent-form-shell.tsx` dissolves into
  `FormAlerts` + `FormActionBar` inline in `agent-form.tsx`; delete
  `agent-form-shell.tsx` and `agent-form-section.tsx`.
- `skill-form.tsx` switches sections, alerts, and bar; delete
  `skill-form-section.tsx`. Keep the `formId` + children-between
  structure (`skill-form.tsx:277-320`) working via the `form` prop.
- `schedule-form.tsx` switches likewise (its sections pass `icon`);
  delete `schedule-form-section.tsx`.
- Bump the page-level section stack from `gap-4` to `gap-6` in all three
  forms. Field `id`s, labels, validation entries, payload building, and
  the dirty-state gating change **not at all**.

### 3. Verify

- `cd apps/web && pnpm check` passes (knip confirms the four deleted
  files left no orphans; depcruise accepts `components/forms`).
- `grep -rn "form-section\|form-shell" apps/web/src/features` returns
  nothing.
- Visual QA against `pnpm dev`, both themes, desktop + mobile: all three
  edit forms and all three create forms render as before but airier;
  submitting with invalid fields still shows the alert list and its
  links still scroll to the offending field; the sticky bar still pins,
  blurs, and disables correctly on pristine edit forms.

## STOP conditions

- depcruise or the layering rules reject `src/components/forms/`
  importing what it needs (or features importing it) — restructure, and
  if that fails stop; do not edit `.dependency-cruiser.cjs` rules.
- Merging the three wrappers forces a behavior-affecting prop change
  (anything beyond classNames and prop plumbing) — stop and report the
  divergence instead of papering over it.
