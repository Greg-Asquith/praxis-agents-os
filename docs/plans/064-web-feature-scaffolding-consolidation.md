# Plan 064: Consolidate the web app's copy-pasted per-feature scaffolding

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat d326b68..HEAD -- apps/web/src/features apps/web/src/lib`
> If the form models, the eight query-key modules, or `lib/forms.ts` changed
> since this plan was written, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the primary mutation surfaces; protected by plan 063's tests)
- **Depends on**: 063 (hard — the form-model and formatter tests are the safety net)
- **Category**: tech-debt
- **Planned at**: commit `d326b68`, 2026-07-07

## Why this matters

Every web feature was built by copying the previous feature's plumbing, and
the copies are drifting:

- The workspace-scoped query-key factory (including the `"__no_workspace__"`
  sentinel that keeps cache entries tenant-scoped) is pasted verbatim into
  **8** feature api modules. A fix to the scoping convention is currently an
  8-file edit.
- Mutation invalidation has already drifted: `create-agent` invalidates
  `lists()` while `update-agent`/`delete-agent` invalidate `all` (which spans
  *other workspaces'* cache entries).
- The form plumbing (`FormValidationEntry` shape, `buildFieldErrors`, the
  setField/handleSubmit/showValidation/formError scaffolding) is duplicated
  across the agents, schedules, and skills forms — `buildFieldErrors` is
  copy-pasted verbatim three times.
- Date/time formatting exists in four places: `lib/format.ts`, a bespoke
  relative formatter siloed in `features/files/format.ts`, and a
  timezone-aware formatter in `features/schedules/format.ts`.
- One route (`new-skill-route.tsx`) uses blocking `window.alert(...)` where
  every other surface uses the inline `Alert` component pattern.

After this plan, adding a feature means writing its field schema and JSX, not
re-implementing ~150 lines of plumbing — and the tenant-scoping convention has
exactly one implementation.

## Current state

- Repo conventions (from AGENTS.md): TanStack Query per-operation files in
  `features/<f>/api/`; layering enforced by `.dependency-cruiser.cjs`
  (`pnpm arch`) — **`lib/` must not import from `features/`**; `type` aliases
  only; no form libraries; `pnpm check` must pass with zero warnings and
  clean knip (no unused exports).
- The duplicated query-key block, identical in all 8 files
  (`features/{agents,skills,schedules,conversations,files,audit,tools}/api/list-*.ts`
  — tools has two: `list-tool-catalog.ts`, `list-tool-presentations.ts`);
  excerpt from `features/agents/api/list-agents.ts:15-26`:

  ```ts
  export const agentsQueryKeys = {
    all: ["agents"] as const,
    workspace: () => [...agentsQueryKeys.all, activeWorkspaceQueryScope()] as const,
    details: () => [...agentsQueryKeys.workspace(), "detail"] as const,
    detail: (agentId: string) => [...agentsQueryKeys.details(), agentId] as const,
    lists: () => [...agentsQueryKeys.workspace(), "list"] as const,
    list: (params: ListAgentsParams = {}) => [...agentsQueryKeys.lists(), params] as const,
  }

  function activeWorkspaceQueryScope() {
    return getActiveWorkspaceSlug() ?? "__no_workspace__"
  }
  ```

  `getActiveWorkspaceSlug` comes from
  `features/workspaces/workspace-context` — which is why the shared factory
  must live in `features/workspaces/`, NOT `lib/` (dependency-cruiser forbids
  lib→features).
- The invalidation drift (`features/agents/api/`): `create-agent.ts:22`
  invalidates `agentsQueryKeys.lists()`; `update-agent.ts:27` and
  `delete-agent.ts` invalidate `agentsQueryKeys.all`.
- The triplicated form plumbing; `buildFieldErrors` verbatim in
  `agent-form.tsx:179-184`, `schedule-form.tsx:~293`, `skill-form.tsx:~325`:

  ```ts
  function buildFieldErrors(entries: AgentFormValidationEntry[]) {
    return entries.reduce<Record<string, string>>((errors, entry) => {
      errors[entry.fieldId] = entry.message
      return errors
    }, {})
  }
  ```

  Each form model declares its own structurally identical
  `XFormValidationEntry = { fieldId: string; label: string; message: string }`
  (`agent-form-model.ts:80-84`, and the schedules/skills equivalents), and each
  form component owns the same `state/setField/showValidation/formError/
  handleSubmit(validate → build → string-error → onSubmit → getErrorMessage)`
  scaffold (`agent-form.tsx:60-120` is the exemplar).
- `lib/forms.ts` currently holds only `formString`/`formNumber` (13 lines).
- Formatters: `lib/format.ts` (`formatDateTime`, `formatTime`, …);
  `features/files/format.ts:56-79` `relativeDateTime(value)` (the app's only
  relative formatter); `features/schedules/format.ts:46-60`
  `formatDateTimeInTimeZone(value, timezone)` (falls back to
  `formatDateTime`).
- `features/skills/routes/new-skill-route.tsx:40,43` — the two
  `window.alert(...)` calls, in `handleCreateSkill` after
  `createSkillMutation.mutateAsync` succeeds. The established alternative
  pattern is local error state rendered through the `Alert` ui component —
  exemplar: `features/agents/routes/agent-detail-route.tsx` (`deleteError`
  state + `<Alert>`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Typecheck | `cd apps/web && pnpm typecheck` | exit 0 |
| Tests | `cd apps/web && pnpm test` | all pass (incl. plan 063's) |
| Layering | `cd apps/web && pnpm arch` | exit 0 |
| Full gate | `cd apps/web && pnpm check` | exit 0 |

## Scope

**In scope**:

- `apps/web/src/features/workspaces/query-keys.ts` (create)
- The 8 query-key-owning api modules listed above, plus every sibling
  mutation file in those features that references the key objects
  (`grep -rln "QueryKeys" apps/web/src/features` is the authoritative list)
- `apps/web/src/lib/forms.ts` (extend)
- `apps/web/src/features/agents/components/{agent-form.tsx,agent-form-model.ts}`
- `apps/web/src/features/schedules/components/{schedule-form.tsx,schedule-form-model.ts}`
- `apps/web/src/features/skills/components/{skill-form.tsx,skill-form-model.ts}`
- `apps/web/src/lib/format.ts`, `apps/web/src/features/files/format.ts`,
  `apps/web/src/features/schedules/format.ts` and their import sites
- `apps/web/src/features/skills/routes/new-skill-route.tsx`
- Import-path updates in plan 063's test files (assertions unchanged)

**Out of scope** (do NOT touch):

- `src/components/ui/` (vendored shadcn output).
- The conversations stream/message-parts modules.
- The responsive table shells (`*-table.tsx`) — a recorded follow-up, not this plan.
- `app/router.tsx` / navigation / breadcrumbs — recorded follow-up.
- `conversation-composer.tsx` — recorded follow-up.
- Backend files.
- No new dependencies.

## Git workflow

- Work on `main` unless told otherwise; one commit per step is fine; style:
  `Web - Feature Scaffolding Consolidation`.
- Do NOT push unless instructed.

## Steps

### Step 1: One workspace-scoped query-key factory

Create `apps/web/src/features/workspaces/query-keys.ts`:

```ts
// apps/web/src/features/workspaces/query-keys.ts

import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"

export function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
}

export function createWorkspaceScopedQueryKeys<Root extends string>(root: Root) {
  const keys = {
    all: [root] as const,
    workspace: () => [...keys.all, activeWorkspaceQueryScope()] as const,
    details: () => [...keys.workspace(), "detail"] as const,
    detail: (id: string) => [...keys.details(), id] as const,
    lists: () => [...keys.workspace(), "list"] as const,
    list: (params: Record<string, unknown> = {}) => [...keys.lists(), params] as const,
  }
  return keys
}
```

Migrate all 8 modules to
`export const agentsQueryKeys = createWorkspaceScopedQueryKeys("agents")`
(same for skills/schedules/conversations/files/audit/tool-catalog/
tool-presentations, keeping each module's existing root string **byte
identical** — check each `all:` literal before replacing). Delete the 8 local
`activeWorkspaceQueryScope` copies. If a feature's key object has extra
members beyond the six (check each file), keep them by spreading:
`{ ...createWorkspaceScopedQueryKeys("files"), extraKey: ... }`. The `list`
param types were feature-specific (`ListAgentsParams`); the generic
`Record<string, unknown>` accepts them — callers keep their typed param
objects.

**Verify**: `pnpm typecheck && pnpm test && pnpm arch` all exit 0, and
`grep -rn "__no_workspace__" apps/web/src --include="*.ts" -l` returns exactly
one file (the new `query-keys.ts`).

### Step 2: Consistent mutation invalidation

Sweep every `useMutation` in `features/*/api/` (grep `invalidateQueries`).
Apply one rule: **create → invalidate `lists()`; update/delete → invalidate
`workspace()`** (covers lists + details for the current workspace without
nuking other workspaces' cache). Known drift sites: `update-agent.ts:27` and
`delete-agent.ts` currently use `.all`. Files already seeding/updating the
cache for details may keep those `setQueryData` calls; only normalize the
invalidation keys. Do not change any mutation that deliberately invalidates a
*different* feature's keys (cross-feature invalidation is intentional — e.g.
file uploads invalidating usage).

**Verify**: `grep -rn "queryKey: \w*QueryKeys.all" apps/web/src/features` →
no matches inside `invalidateQueries` calls; `pnpm test` green.

### Step 3: Shared form plumbing in `lib/forms.ts`

Add to `apps/web/src/lib/forms.ts` (framework-light — types and pure
functions only, no React imports, so dependency-cruiser stays happy):

```ts
export type FormValidationEntry = {
  fieldId: string
  label: string
  message: string
}

export function buildFieldErrors(entries: readonly FormValidationEntry[]) {
  return entries.reduce<Record<string, string>>((errors, entry) => {
    errors[entry.fieldId] = entry.message
    return errors
  }, {})
}
```

Then, in each of the three form models, replace the local
`XFormValidationEntry` declaration with a re-export or direct use of
`FormValidationEntry` (keep the old name as an alias only if other files
import it — prefer updating the importers; knip will flag a dead alias). In
each of the three form components, delete the private `buildFieldErrors` and
import the shared one.

Do **not** attempt a generic `useEntityForm` hook in this plan — the three
forms' submit flows have real differences (skills uploads documents after
create; schedules threads timing payloads). Extracting state management is a
follow-up once the shapes converge further.

**Verify**: `grep -rn "function buildFieldErrors" apps/web/src` → exactly one
match (`lib/forms.ts`); `pnpm test` green (plan 063's form-model tests may
need import updates only — assertions must not change).

### Step 4: One home for date/time formatting

- Move `relativeDateTime` from `features/files/format.ts` into
  `lib/format.ts` unchanged; update its importers
  (`grep -rn "relativeDateTime" apps/web/src`); delete it from the files
  module (keep that file if it still has file-specific formatters like
  `shortHash`).
- Move `formatDateTimeInTimeZone` from `features/schedules/format.ts` into
  `lib/format.ts` (it already calls `formatDateTime`, which lives there);
  update importers; keep schedule-specific formatters (e.g. the next-run
  formatter) where they are.

**Verify**: `pnpm check` exits 0 (knip confirms no orphaned exports);
`grep -rn "export function relativeDateTime\|export function formatDateTimeInTimeZone" apps/web/src`
→ both only in `lib/format.ts`.

### Step 5: Replace `window.alert` with the Alert pattern

In `new-skill-route.tsx`, add local state
(`const [postCreateWarning, setPostCreateWarning] = useState<string | null>(null)`),
set it where the two `window.alert(...)` calls are, and render it with the
same `Alert` component usage as `agent-detail-route.tsx`. Note the current
code navigates away immediately after the alert — decide placement so the
message is actually visible: set the warning into a search param or render it
before navigating (simplest correct option: block navigation until the user
dismisses, i.e. render the Alert with a "Continue to skill" button that
performs the existing `navigate(...)`). Keep the mutation flow otherwise
identical.

**Verify**: `grep -rn "window.alert\|[^.]alert(" apps/web/src/features --include="*.tsx" | grep -v Alert`
→ no matches; `pnpm check` exits 0.

## Test plan

- Plan 063's suites are the regression net: `pnpm test` must stay green with
  **assertion changes = 0** (import-path changes allowed).
- Add one new test file `apps/web/src/features/workspaces/query-keys.test.ts`:
  the factory's output for a fixed root equals the previous literal key shapes
  (`["agents"]`, `["agents", "<scope>", "list", {…}]` …), and the sentinel is
  returned when no workspace slug is set. Model after `reducer.test.ts`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `cd apps/web && pnpm check` exits 0
- [ ] Exactly one `activeWorkspaceQueryScope` and one `buildFieldErrors` definition in `apps/web/src` (grep)
- [ ] `"__no_workspace__"` appears in exactly one source file
- [ ] No `window.alert` in `apps/web/src/features`
- [ ] Plan 063 test assertions unchanged (`git diff --stat` on those test files shows import-line changes only)
- [ ] Status row updated in `docs/plans/000_README.md`

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 063's tests are not present/green before you start (dependency not met).
- Any feature's key object diverges structurally from the six-member shape in
  a way spreading can't preserve (report the file; don't force it).
- `pnpm arch` rejects the new `features/workspaces/query-keys.ts` import graph.
- Query keys change byte-wise for any existing entry (the step-1 test file
  must prove they don't; if it can't, stop).
- Fixing invalidation reveals a consumer that *relied* on cross-workspace
  invalidation.

## Maintenance notes

- New features must use `createWorkspaceScopedQueryKeys` — reviewers should
  reject fresh copies of the key boilerplate.
- Deferred follow-ups recorded in `docs/plans/000_README.md`: shared
  `<DataTable>` responsive shell (5 near-identical table components), a
  route-descriptor to collapse the router/navigation/breadcrumbs lockstep,
  splitting `conversation-composer.tsx` into hooks, and a generic
  entity-form state hook.
- Do not reference this plan number from implementation code or comments
  (AGENTS.md rule).
