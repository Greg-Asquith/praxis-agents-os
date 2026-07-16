# Plan 024: "Configure" dies — Edit language sweep

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-16 (anchors verified against the live tree at
  `01104f7`)
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — copy and one icon swap.
- **Depends on**: 023 (touches the same `agents-table.tsx`; land 023
  first so this sweep runs over final content). Grazes files 021/022
  do not touch — safe in parallel with those.

## Goal

"Configure" is developer language for what users experience as editing
a thing they made. Every user-facing "Configure"/"configure" goes:
navigation buttons say **Edit**, and descriptive copy is rewritten as
outcomes rather than mechanisms. The convention going forward:
**Edit** for the action that opens an existing entity's form, **Save
Changes** (already standard per plan 013) for committing it. "Update"
is reserved for API naming and stays out of the UI.

## Current state (verified 2026-07-16 at `01104f7`)

User-facing occurrences (`grep -rni "configur" apps/web/src`, filtered
to rendered copy):

| File | Line(s) | Text |
|------|---------|------|
| `features/agents/components/agents-table.tsx` | 120, 189 | "Configure" row button (with `Settings2Icon`) |
| `features/skills/components/skills-table.tsx` | 105, 151 | same |
| `features/schedules/components/schedules-table.tsx` | 117, 168 | same |
| `features/agents/routes/agents-route.tsx` | 28 | page description "Configure agents, models, tools, delegation, and approval policies." |
| `features/agents/components/agents-table.tsx` | 46 | empty state "…start conversations and configure approval policies." |
| `features/agents/components/agent-runtime-section.tsx` | 70 | select group label "Configured models" |
| `features/agents/components/agent-tools-section.tsx` | ~187 | "{n} configured tools are unavailable…" (verify exact copy in place) |
| `features/agents/components/agent-form-model.ts` | 133 | option description "Use the backend default configured for agent runs." |
| `features/agents/components/agent-form-model.ts` | 154 | "This saved model is not present in the configured catalog response." |
| `features/workspaces/components/create-invitation-dialog.tsx` | 115 | "…if email delivery is not configured." |

Non-user-facing matches (comments, `env.ts` variable names) are out of
scope — this is a copy sweep, not a rename.

## Steps

### 1. Row action buttons → Edit

In all six button instances (three tables, desktop + mobile each):
label becomes **"Edit"** and `Settings2Icon` becomes `PencilIcon` — the
gear icon says "configure" as loudly as the word did. Keep size,
variant, and `data-icon` placement; Title Case per plan 013 (single
word, trivially satisfied).

### 2. Descriptive copy → outcomes

Per the 015-series rule (plain-language copy states outcomes, not
mechanisms):

- `agents-route.tsx:28` → "Create and manage the agents that work in
  this workspace."
- `agents-table.tsx:46` (empty state) → "Create the first agent to
  start conversations in this workspace." (the approval-policies clause
  is create-flow detail, not empty-state motivation).
- `agent-runtime-section.tsx:70` group label "Configured models" →
  **"Ready to use"** (its counterpart group, if labeled, should read as
  "Needs an API key" — align the pair while in the file; verify the
  actual sibling label in place).
- `agent-tools-section.tsx:~187` → keep the fact, drop the word, e.g.
  "{n} selected tools are currently unavailable" (match the sentence
  that exists in place).
- `agent-form-model.ts:133` → "Use the workspace default model."
- `agent-form-model.ts:154` → "This model is no longer in the catalog.
  Pick a replacement."
- `create-invitation-dialog.tsx:115` → "Share this token with the
  invitee if the email doesn't arrive." (states the user-visible
  condition, not the server's).

### 3. Sweep check

`grep -rni "configur" apps/web/src --include="*.tsx" --include="*.ts"`
— every remaining hit must be a code comment, identifier, or `env`
plumbing, not rendered copy. List survivors in the completion note.

### 4. Verify

- `cd apps/web && pnpm check` passes.
- Manual QA against `pnpm dev`: the three list pages show "Edit" with
  the pencil icon on desktop rows and mobile cards; agents page
  header/empty-state read naturally; the model select group labels make
  sense against a workspace with and without missing API keys.

## STOP conditions

- A "Configure" occurrence turns out to be a genuine configuration
  surface (settings that are not an entity the user created) — stop
  and flag it instead of forcing "Edit" onto it. None are known at
  time of writing.
- The `agent-tools-section` / `agent-runtime-section` copy has drifted
  from the quoted text — reconcile against the live code (it wins on
  mechanics) and keep the intent: no user-facing "configure(d)".
