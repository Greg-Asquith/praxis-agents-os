# Plan 027: Registry-driven tool catalog in the agent form

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat f83d210..HEAD -- apps/web/src/features/agents/ apps/web/src/features/models/ apps/web/src/features/conversations/components/tool-call-row.tsx apps/web/src/features/conversations/components/delegation-tool-row.tsx`
> Plan 025 must be DONE (the catalog endpoint must exist). If the agent-form
> files differ structurally from the "Current state" excerpts, STOP.
>
> **Known benign drift (verified 2026-07-03 at `9208c47`)**: commit `603fff7`
> heavily reshaped `features/conversations/` (new `delegation-tool-row.tsx`,
> `message-parts/` package, rewritten `tool-call-row.tsx`). The agent-form
> files were untouched. Expect that churn; the chat-side consumers are
> already re-anchored below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM (agent configuration UI; a payload bug could silently
  drop tool grants — pinned by the payload tests-by-hand below)
- **Depends on**: 025 (hard); 023 + 026 (soft — only for the audit-viewer
  additive step)
- **Category**: harness spine, frontend slice (roadmap
  `000_MASTER_ROADMAP.md` Phase 1; donor design A3)
- **Planned at**: commit `f83d210`, 2026-07-02

## Decisions taken

1. **`RuntimeToolName` stops being a compile-time union.** The catalog is
   server data now; tool names are `string` and `toolModes` becomes
   `Record<string, RuntimeToolMode>`. The type-safety the union provided
   moves to runtime behavior (unknown-name handling, decision 3).
2. **Backend labels win.** Plan 025 seeded the registry `label`s with the
   exact strings the frontend hardcodes ("Runtime context", "Add numbers"),
   so switching the source produces no visible label change. **Descriptions
   DO change**: the frontend hardcodes longer copy than the backend registry
   descriptions ("Read the current Praxis workspace, conversation, agent,
   and run identifiers." / "Add two integers."), so the form's description
   text becomes the backend's terser strings — expected, not a regression.
3. **Tools configured on an agent but absent from the catalog render as
   "Unavailable" rows, preserved on save.** Saving an agent must never
   silently strip a grant because the catalog momentarily lacks the tool
   (deploy skew, disabled provider). The row is disabled with an explanatory
   note; only an explicit user change to "Off" removes it.
4. **Mode options per tool come from `supported_policies`** — a tool that
   does not support `auto` simply has no Auto option, and switching a tool
   on defaults its mode to the tool's `default_policy` (not always `auto`
   as today's UI implies).
5. **The remaining "agent form tidy" from NOTES is scoped to the tools
   section**: grouping by provider, descriptions inline, a "Writes" effect
   badge, and approval-count coherence. The broader form flow was already
   reworked (rework plans 005/007); skills editing belongs to plan 019 — not
   re-opened here.

## Why this matters

The frontend tool list is hardcoded with a comment begging for this exact
plan (`runtime-tools.ts:4-5`: "Keep this list aligned with … until the
backend exposes a public runtime-tool catalog endpoint"). Plan 028 adds real
tools and Phases 3–6 add dozens more; without this plan, every one of them
requires a hand-synced frontend edit and a deploy-ordering dance. After it,
new registry entries appear in the agent form and chat labels with zero
frontend changes.

## Current state

- Catalog endpoint (after 025): `GET /api/v1/tools/catalog` →
  `{tools: [{name, provider, label, description, effect, default_policy,
  supported_policies, defer_loading}]}`.
- The exact frontend precedent to copy: the model catalog —
  `apps/api/routes/models/list_catalog.py` →
  `apps/web/src/features/models/api/list-model-catalog.ts`
  (`useModelCatalogQuery`) → consumed by `agent-form-model.ts` /
  `agent-runtime-section.tsx`.
- The hardcoded list: `apps/web/src/features/agents/runtime-tools.ts` —
  `RUNTIME_TOOL_OPTIONS` (lines 7–19), `RuntimeToolName` derived as a
  compile-time union (line 20), `runtimeToolLabel(name)` (line 23, **also
  consumed by TWO chat components** — `tool-call-row.tsx:3` import / `:49`
  usage, and `delegation-tool-row.tsx:7` import / `:50` usage, the latter
  added by `603fff7`), `RuntimeToolMode = "off" | ToolPolicyValue` and
  `RUNTIME_TOOL_MODE_LABELS` (lines 21, 27–31).
- Couplings in `agent-form-model.ts`: `AgentFormState.toolModes:
  Record<RuntimeToolName, RuntimeToolMode>` (line 79); `initialToolModes`
  (295–309) with a **hardcoded fallback object literal**
  `{add_numbers: "off", get_runtime_context: "off"}`; `toolModesEqual`
  (319–324); `buildToolPayload` (355–373) emitting `tool_names` +
  `tool_policies`.
- Renderer: `agent-runtime-section.tsx:226-261` maps `RUNTIME_TOOL_OPTIONS`
  to per-tool Off/Auto/Approval `<Select>` rows.
- Approval metric: `apps/web/src/features/agents/agent-metrics.ts:10-11`
  counts approval policies from `tool_policies` (catalog-independent — no
  change needed, verify only).
- Audit viewer (after 023/026): `features/audit/` filter bar + table;
  `audit_events` rows carry `tool_name`/`tool_provider` after 026.

## Commands you will need

| Purpose | Command (from `apps/web`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `pnpm lint` | exit 0 |
| Build | `pnpm build` | exit 0 |
| Dev | `pnpm dev` (API running with 025 landed) | manual checks |

## Scope

**In scope:**

- `apps/web/src/features/tools/types.ts`,
  `apps/web/src/features/tools/api/list-tool-catalog.ts` (create — its own
  feature folder, mirroring how the model catalog lives in
  `features/models/`)
- `apps/web/src/features/agents/runtime-tools.ts` (shrink: keep
  `RuntimeToolMode` + `RUNTIME_TOOL_MODE_LABELS`; delete
  `RUNTIME_TOOL_OPTIONS`, `RuntimeToolName`, `runtimeToolLabel`)
- `apps/web/src/features/agents/components/agent-form-model.ts`
- `apps/web/src/features/agents/components/agent-form.tsx`,
  `agent-runtime-section.tsx`
- `apps/web/src/features/conversations/components/tool-call-row.tsx` (label
  lookup)
- `apps/web/src/features/conversations/components/delegation-tool-row.tsx`
  (label lookup — second `runtimeToolLabel` consumer since `603fff7`)
- `apps/web/src/features/tools/use-tool-labels.ts` (create — shared label
  hook)
- Conditional (only if 023 AND 026 are DONE):
  `apps/web/src/features/audit/` filter bar + table gain
  `tool_name`/`tool_provider` filter and columns
- `apps/web/src/features/agents/agent-metrics.ts` (verify-only; change only
  if the read shape forces it)

**Out of scope (do NOT touch):**

- Anything under `apps/api/`.
- Skills display/editing in the form (plan 019).
- Delegation section, model/thinking selects, profile section — the form
  beyond the tools block.
- `defer_loading` UI (nothing to configure until D7 revisits).

## Git workflow

- Branch: `advisor/027-frontend-tool-catalog`
- Commit style: `Web - Registry-Driven Tool Catalog`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Tool catalog feature module

- `features/tools/types.ts`: `ToolCatalogEntry` and `ToolCatalogResponse`
  mirroring 025's schema; `ToolEffect = "read" | "write"`.
- `features/tools/api/list-tool-catalog.ts`: copy
  `list-model-catalog.ts` structurally — `toolsQueryKeys` (workspace-scoped
  via `activeWorkspaceQueryScope()`), `toolCatalogQueryOptions()`
  (`staleTime: 60_000` like the model catalog), `useToolCatalogQuery()`
  (suspense).
- `features/tools/use-tool-labels.ts`: a **non-suspense** hook returning
  `(name: string) => string` — catalog label when loaded, else the raw name.
  Non-suspense because the chat transcript must render before/without the
  catalog (tool names are acceptable fallbacks mid-load).

**Verify**: `pnpm lint` → exit 0.

### Step 2: Untangle `runtime-tools.ts`

Reduce the file to `RuntimeToolMode`, `RUNTIME_TOOL_MODE_LABELS`, and a
`toolModeOptions(entry)` helper deriving the mode list for one catalog entry
(`["off", ...entry.supported_policies]`). Delete `RUNTIME_TOOL_OPTIONS`,
`RuntimeToolName`, `runtimeToolLabel`, and the sync comment. Fix every
compile error this surfaces — that is the point; the compiler enumerates the
coupling sites listed in "Current state".

**Verify**: `pnpm lint` fails only in the files named in Steps 3–4 (no
hidden consumers — if a new consumer appears, read it before changing it).

### Step 3: Form model + renderer

- `agent-form-model.ts`: `toolModes: Record<string, RuntimeToolMode>`;
  `initialToolModes(catalog: ToolCatalogEntry[], agent?)` builds Off
  defaults from the catalog then overlays the agent's `tool_names`/
  `tool_policies` — **including names not in the catalog** (decision 3);
  drop the hardcoded fallback literal; `buildToolPayload` iterates the
  state's own keys (emit `tool_names` = keys with mode ≠ off,
  `tool_policies` = their modes). `toolModesEqual` keys off the union of
  both key sets.
- `agent-form.tsx`: fetch the catalog with `useToolCatalogQuery()` (the
  form already renders under Suspense with the model catalog) and thread it
  into initial state + the runtime section. Keep the
  `key={id:updated_at}` reset pattern intact.
- `agent-runtime-section.tsx`: render catalog entries grouped by `provider`
  (group heading Title Case; single "Core" group today), each row: label,
  description (`text-muted-foreground text-sm`), a "Writes" outline `Badge`
  when `effect === "write"`, and the mode `<Select>` built from
  `toolModeOptions(entry)`. Switching Off → on selects the entry's
  `default_policy` (decision 4). Below the catalog groups, render any
  unavailable configured tools (decision 3) as disabled rows with note
  "No longer available — set to Off to remove". Keep the section's existing
  `Field`/validation wiring.

**Verify**: `pnpm lint` → exit 0.

### Step 4: Chat labels + metrics

- `tool-call-row.tsx` AND `delegation-tool-row.tsx`: replace
  `runtimeToolLabel` with `useToolLabels()` from Step 1 in both (fallback =
  raw name covers delegation tools and any uncatalogued names).
  `delegation-tool-row.tsx:50` currently does
  `runtimeToolLabel(activity.name) ?? activity.name` — the hook's built-in
  fallback replaces that `??` chain.
- `agent-metrics.ts`: confirm the approval count still derives purely from
  `tool_policies` (expected: no change).

**Verify**: `pnpm lint` → exit 0 and `pnpm build` → exit 0.

### Step 5 (conditional): audit viewer tool columns

Only if plans 023 and 026 are both DONE: add `tool_name` (text input) and
`tool_provider` filters to `audit-filter-bar.tsx` and the two columns to
`audit-events-table.tsx`, using the label hook for display. If either is not
landed, record this step as a follow-up in your completion note instead.
(As of 2026-07-03 neither is landed — no `features/audit/` and no audit
routes exist — so expect to skip this step unless they ship first.)

**Verify**: `pnpm lint && pnpm build` → exit 0.

## Test plan

No frontend harness — `pnpm lint`, `pnpm build`, and this manual matrix
against a dev API:

1. Agent form (create): both core tools listed with backend labels +
   descriptions; enabling "Add numbers" defaults its mode to Auto; payload
   in devtools shows `tool_names: ["add_numbers"]`,
   `tool_policies: {add_numbers: "auto"}`.
2. Agent form (edit) round-trip: existing agent's grants render correctly;
   toggling to Approval and saving persists; **saving without touching the
   tools section produces an identical payload to before this plan** (diff
   the PATCH bodies — this is the no-silent-drop check).
3. Unavailable tool: hand-set an agent's `tool_names` in the DB to include
   `"ghost_tool"` → form shows the disabled Unavailable row; saving without
   touching it keeps `ghost_tool` in `tool_names`; setting it Off removes
   it.
4. Chat: run a tool call → row shows the catalog label; while throttling the
   catalog request, the raw name renders (no crash, no suspense of the
   transcript).
5. If a plan-028 tool has landed by execution time: it appears in the form
   with no frontend change (the actual acceptance test of this plan).

## Done criteria

- [ ] `pnpm lint` exits 0
- [ ] `pnpm build` exits 0
- [ ] `grep -rn "RUNTIME_TOOL_OPTIONS\|RuntimeToolName" apps/web/src` returns
      nothing
- [ ] `grep -rn "Keep this list aligned" apps/web/src` returns nothing (the
      sync comment is dead)
- [ ] Manual matrix above completed (call out any step you could not run)
- [ ] No modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `GET /tools/catalog` is absent or its shape differs from 025's schema.
- `agent-form-model.ts` / `agent-runtime-section.tsx` no longer match the
  quoted line ranges structurally (the form was reworked again).
- Step 2's compile errors reveal consumers of `RUNTIME_TOOL_OPTIONS` /
  `runtimeToolLabel` beyond the files this plan lists.
- The manual payload-diff check (test 2) shows any difference for an
  untouched form.

## Maintenance notes

- From this plan on, **adding a tool is backend-only** (a `@runtime_tool`
  registration). If a future plan edits frontend code to "add a tool", that
  is a regression of this plan's contract.
- `use-tool-labels.ts` is the single place chat/audit surfaces resolve tool
  display names; plan 028's planning tool and 041's integration tools get
  labels there for free.
- The Unavailable-row behavior (decision 3) becomes more important with
  integrations (a disconnected provider hides tools via `is_tool_allowed`);
  revisit its copy when 040/042 land.
- Reviewers should scrutinize: payload equivalence for untouched forms,
  unknown-name preservation, and that the transcript never suspends on the
  catalog query.
