# Plan 017: Agent form — create wizard & edit clarity

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-16 (anchors verified against the live tree at
  `9d597e1` with plan 013 applied)
- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM — the agent form is the largest (six sections, tool
  policy matrix, delegation). The wizard shell is proven by 016; the
  risk here is scope, not machinery.
- **Depends on**: 016 (wizard shell). Can run in parallel with 018 —
  they touch disjoint feature directories.

## Goal

Agent creation becomes a **four-step wizard**; the agent edit page gets
restructured sections, an Advanced disclosure for the fields a
non-technical user should never have to look at, and a plain-language
copy pass. Follows 016's wizard design language (plain-question step
titles, one primary action, optional steps say so, safe defaults leave
the create flow).

## Current state (verified 2026-07-16)

- `features/agents/components/agent-form.tsx` (177 lines) composes four
  section components inside `AgentFormShell`: Profile
  (`agent-profile-section.tsx` — name `agent-name`, description,
  instructions `agent-instructions`), Runtime
  (`agent-runtime-section.tsx` — actually **two** sections: "Model
  selection" with model `agent-model` / thinking / conditional Azure
  deployment at lines 47-138, and "Step budget and availability" with
  max steps `agent-max-steps` / Availability / Favorite selects at
  lines 140-206, plus it nests `AgentToolsSection` at line 208),
  Delegation (`agent-delegation-section.tsx` — picker + allowed list),
  and Skills (`agent-skills-section.tsx` — picker + attached list).
- `agent-tools-section.tsx` (224 lines): search, provider filter,
  grouped tool rows with per-tool mode (off / auto / approval), an
  "Unavailable" group for configured-but-gone tools, and a summary
  strip.
- `validateAgentFormState` (`agent-form-model.ts:225`) emits fieldIds
  `agent-name`, `agent-slug`, `agent-instructions`, `agent-max-steps`,
  `agent-model` — the wizard partition below covers all five
  (`agent-slug` has no visible field; its entry surfaces on the Profile
  step).
- The model defaults max steps, thinking, availability (`"true"`), and
  favorite (`"false"`); `modelSelection` defaults to the
  workspace-default option built by `buildModelOptions`.
- Routes: `new-agent-route.tsx` (header + create form),
  `agent-detail-route.tsx` (header with identity icon/badges, delete,
  "Agent updated" alert at lines 106-111, edit form remounted via
  `key={agent.id:updated_at}` at line 115).

## Steps

### 1. Create wizard — four steps

Convert `agent-form.tsx`'s create mode to `FormWizard`:

1. **"Who is this agent?"** — name, description, instructions
   (fieldIds `agent-name`, `agent-slug`, `agent-instructions`). The
   existing `AgentProfileSection` fields, full step width for the
   instructions editor.
2. **"How should it think?"** — the model select (workspace default
   preselected, so Next works untouched; fieldIds `agent-model`,
   `agent-max-steps`), and below it an **Advanced** disclosure (native
   `<details>`, the settled pattern) containing Thinking, Max steps,
   and — only when an Azure model is selected — Azure deployment.
   Closed by default; a one-line hint says the defaults are sensible.
3. **"What can it use?"** — the tools & approval section as-is
   (defaults already come from the catalog via
   `initialAgentFormState`). Reframe the intro copy for a non-technical
   reader: what a tool is in one sentence, and "Approval means a person
   confirms each use before it runs. You can change all of this later."
   No fieldIds; never blocks.
4. **"Who can it work with?"** — Skills + Delegation, both marked
   optional. Final step; submit reads "Create Agent".

Availability and Favorite leave the create flow entirely (model
defaults: active, not favorite). If the Advanced disclosure is closed
and `agent-max-steps` fails validation, the disclosure must open so the
inline error is visible — a `#fieldId` anchor into a closed `<details>`
is a dead link.

### 2. Edit page — restructure the sections

Edit mode stays one page on the 015 kit, reorganized so each section
answers one question:

- **Profile** — unchanged.
- **Model** — model select plus the same Advanced disclosure from
  step 1 (Thinking, Max steps, Azure deployment). This dissolves the
  current "Step budget and availability" grid — max steps moves into
  Advanced.
- **Tools** — unchanged mechanics, same copy pass as wizard step 3.
- **Skills**, **Delegation** — unchanged mechanics.
- **Status** — new last section holding Availability and Favorite,
  described in outcomes ("Inactive agents can't start new runs or be
  delegated to; existing history is kept").

Same disclosure-opens-on-error rule as the wizard. The route-level
pieces (`agent-detail-route.tsx` header, delete dialog, saved alert,
remount key) are untouched.

### 3. Copy pass (both modes)

Plain language, outcomes over mechanisms, one line each. Anchor
examples — executor applies the register everywhere it's off:

- Max steps: "The most actions one run may take before it stops."
- Thinking: keep the option descriptions; the field description should
  not assume the reader knows what extended thinking is.
- Delegation section description: "Let this agent hand work to other
  agents during a run."

### 4. Verify

- `cd apps/web && pnpm check` passes.
- Manual QA against `pnpm dev`, both themes, desktop + mobile:
  - Create an agent touching only step 1 and Next through everything
    else — it succeeds with defaults (workspace-default model, default
    step budget, catalog-default tools, no skills/delegates).
  - Step 1 blocks on empty name/instructions; a max-steps error on
    step 2 opens the Advanced disclosure and shows inline.
  - Back/forward retains all state including tool-mode changes, search
    text cleared or kept (component-local; either is fine), and
    attached skills/delegates.
  - Edit: dirty gating, save, "Agent updated" alert, delete flow, and
    the Status section all work; changing availability round-trips.
  - Keyboard-only wizard pass; focus visible throughout.

## STOP conditions

- The tools section cannot render inside a wizard step without
  behavioral surgery (its local expand/search state is fine to keep) —
  stop rather than fork the component.
- Per-step gating can't be built by filtering
  `validateAgentFormState` entries by fieldId — stop; do not duplicate
  rules.
- The `<details>` Advanced disclosure cannot be made to open on
  contained-field error without replacing it with a JS accordion —
  stop and report (native disclosures are a settled decision).
