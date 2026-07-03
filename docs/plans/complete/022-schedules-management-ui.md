# Plan 022: Build the schedules management UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat f83d210..HEAD -- apps/web/src/app/router.tsx apps/web/src/config/navigation.ts apps/web/src/components/shell/app-breadcrumbs.tsx apps/web/src/features/agents/ apps/web/src/features/conversations/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **Known benign drift (verified 2026-07-03 at `9208c47`)**: commit `603fff7`
> rewrote `features/conversations/` (`conversation-route.tsx` slimmed to ~212
> lines; `message-parts.ts` → `message-parts/parse.ts`; new
> `message-list.tsx`, `use-conversation-run-state.ts`). This is expected — do
> not STOP on it. Conversations remains a read-only pattern reference here;
> the corrected citations are already reflected below.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: LOW (pure frontend over the plan 021 contract)
- **Depends on**: 021 (hard — every call targets its routes)
- **Category**: operational surfaces (roadmap `000_MASTER_ROADMAP.md` Lane O;
  Gate G1 input)
- **Planned at**: commit `f83d210`, 2026-07-02
- **Completed at**: 2026-07-03
- **Verification**: `pnpm check` from `apps/web`

## Decisions taken

1. **Approval decisions happen in the conversation, not here.** An
   `awaiting_approval` run row links to its conversation
   (`conversation_id`), where approval forms already render inline (rework
   plan 016). The schedules UI shows the state and provides the link; it does
   not duplicate approval controls.
2. **Active-context selection is not in this UI.** Plan 040 extends the
   schedule form with a context picker; the form is built with an obvious
   extension slot (its own section component) so 040 is additive.
3. **Timezone picker**: a plain `<Select>` populated from
   `Intl.supportedValuesOf("timeZone")` with `UTC` first/default — simple and
   accessible over a custom combobox, per frontend standards. Server-side
   validation (plan 021) remains authoritative.
4. **Cron validation is server-owned.** The form does not bundle a cron
   parser; the preview endpoint (`POST /schedules/preview`) doubles as
   validation — the editor shows the next fire times on demand and surfaces
   the problem+json error when the expression is bad.

## Why this matters

Schedules are the only way agents run unattended today, and they are
invisible: users cannot see, create, pause, or debug them without SQL. The
backend surface arrives in plan 021; this plan makes it a product screen —
list with health, editor with fire-time preview, run history with
approval-state linkage — completing the NOTES item "Schedules: UI & complete
worker!" and the operator half of Gate G1.

## Current state

- **A partial, uncommitted `src/features/schedules/` already exists on disk**
  (untracked as of 2026-07-03): `types.ts` plus all ten `api/` modules,
  matching this plan's intended shapes (workspace-scoped `schedulesQueryKeys`
  with a `runs(id)` key, `staleTime: 15_000`, `activeWorkspaceQueryScope()`).
  `components/`, `routes/`, and the router/nav/breadcrumb wiring are missing.
  Step 1 becomes a reconcile-and-verify pass, not a create.
  The app is Vite + React 19,
  TanStack Router (code-defined routes in `src/app/router.tsx`), TanStack
  Query v5 with `useSuspenseQuery`, Tailwind v4, Base UI primitives in
  `src/components/ui/` (`render`-prop polymorphism, not `asChild`).
- Feature-folder convention: `src/features/<feature>/{api,components,routes}`
  + `types.ts`. Exemplar end-to-end: agents —
  `features/agents/api/list-agents.ts` (query-key factory scoped by
  `activeWorkspaceQueryScope()`, `queryOptions` with `staleTime: 30_000`,
  `useAgentsQuery`), `create-agent.ts` (`useMutation` +
  `invalidateQueries({queryKey: agentsQueryKeys.lists()})`).
- Pages register in `router.tsx` via `createRoute({getParentRoute: () =>
  appRoute, path, component: lazyRouteComponent(import, "NamedExport")})` and
  are added to `appRoute.addChildren([...])` (lines 186–200). Nav items live
  in `src/config/navigation.ts:25-50`; breadcrumbs need a branch in
  `app-breadcrumbs.tsx` (`getBreadcrumbs`, lines 89–153; widen the
  `BreadcrumbRoute` union at line 13).
- Table pattern: `features/agents/components/agents-table.tsx` —
  `EmptyState` when empty, `<ResponsiveList>` mobile rows + `hidden md:block`
  desktop `<Table>`, `<Badge>` status chips, row action button via
  `render={<Link/>}`. Page composition: `agents-route.tsx` (eyebrow + h1 +
  action, metric cards grid, table in a `Card`).
- Form pattern: controlled `useState<FormState>` + a pure `*-form-model.ts`
  (`initialState`, `validate…` returning `{fieldId, label, message}[]`,
  `build…Payload`, `isDirty`), validation shown after first submit, per-field
  `Field data-invalid` + `FieldError`, submit via `mutateAsync` with errors in
  `<Alert variant="destructive">` (see `agent-form.tsx:82-92`,
  `agent-form-model.ts`).
- Status badges: `run-status-badge.tsx` maps `AgentRunStatus` → `Badge`
  variants; `formatDateTime` (returns "Never" for null), `pluralize`,
  `titleFromSegment` in `src/lib/format.ts`.
- Conversation linkage target: the chat surface renders approval forms inline
  — `approval-controls.tsx` (`ApprovalControls`) is rendered by
  `message-list.tsx:143` from props (`approvals`, `onApprovalSubmit`,
  `approvalError`, …) that `conversation-route.tsx` computes and passes
  through `<MessageList>` — so a link to the run's conversation is a complete
  approval-decision path.
- Backend contract (plan 021): `/schedules` CRUD, `pause`/`enable`/`run-now`,
  `GET /schedules/{id}/runs`, `POST /schedules/preview`; read models carry
  `health` (`healthy|retrying|needs_attention|cancelled`), `latest_run`, and
  runs carry `status` (9 values), `conversation_id`, `agent_run_id`,
  `last_error_code/message`.
- `health` is effectively never null: `AgentScheduleRead.health` is typed
  `str | None` (`schemas.py:72`) but the service always populates it —
  `schedule_health_from_run(None)` returns `"healthy"` (`runs.py:73-74`), and
  `AgentScheduleRunRead.health` is a required `str`. Model it as non-nullable
  `ScheduleHealth` (the existing `types.ts:52` already does); the metric
  cards and badge maps need no null branch.

## Commands you will need

| Purpose | Command (from `apps/web`) | Expected on success |
|---------|---------------------------|---------------------|
| Install | `pnpm install` | exit 0 |
| Lint    | `pnpm lint` | exit 0 |
| Build   | `pnpm build` | exit 0 |
| Dev     | `pnpm dev` (with the API running) | manual checks below |

## Scope

**In scope (create unless marked otherwise):**

- `apps/web/src/features/schedules/types.ts`
- `apps/web/src/features/schedules/api/`: `list-schedules.ts`,
  `get-schedule.ts`, `create-schedule.ts`, `update-schedule.ts`,
  `delete-schedule.ts`, `pause-schedule.ts`, `enable-schedule.ts`,
  `run-schedule-now.ts`, `list-schedule-runs.ts`, `preview-schedule.ts`
- `apps/web/src/features/schedules/components/`: `schedules-table.tsx`,
  `schedule-form.tsx`, `schedule-form-model.ts`, `schedule-timing-section.tsx`,
  `schedule-preview-panel.tsx`, `schedule-run-history.tsx`,
  `schedule-status-badges.tsx`
- `apps/web/src/features/schedules/routes/`: `schedules-route.tsx`,
  `new-schedule-route.tsx`, `schedule-detail-route.tsx`
- `apps/web/src/app/router.tsx` (modify: three routes)
- `apps/web/src/config/navigation.ts` (modify: nav item)
- `apps/web/src/components/shell/app-breadcrumbs.tsx` (modify: breadcrumb
  branch + `BreadcrumbRoute` union)

**Out of scope (do NOT touch):**

- Anything under `apps/api/` — the contract is plan 021's.
- Approval decision UI — link to the conversation (decision 1).
- Active-context picker (plan 040), notifications for failed runs (029/030
  territory), pagination controls (no list UI paginates yet; pass a fixed
  `limit: 100` like agents).
- `features/agents/` and `features/conversations/` — read their patterns,
  change nothing.

## Git workflow

- Branch: `advisor/022-schedules-management-ui`
- Commit style: `Web - Add Schedules Management UI`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Types and API modules (reconcile the existing untracked files)

An untracked `features/schedules/{types.ts,api/}` already exists and matches
this step's intent. Do not recreate it: diff each existing module and
`types.ts` against 021's `apps/api/routes/schedules/schemas.py` and fix any
mismatch (one shape verified good already: `ScheduleUpdateRequest =
Partial<Omit<ScheduleCreateRequest, "agent_id">>` matches the backend
`AgentScheduleUpdateRequest`, which has no `agent_id`). The target shapes:

`types.ts`: mirror plan 021's Pydantic read/request models —
`AgentSchedule`, `AgentScheduleRun`, `SchedulesListResponse`,
`ScheduleRunsListResponse`, `ScheduleCreateRequest`,
`ScheduleUpdateRequest = Partial<...>`, `SchedulePreviewRequest/Response`,
plus string unions for `ScheduleType` (`cron|interval|once`),
`ScheduleRunStatus` (the nine backend values), and `ScheduleHealth`.

API modules copy the agents shapes exactly:

- `list-schedules.ts`: `schedulesQueryKeys` factory (workspace-scoped via
  `activeWorkspaceQueryScope()`), `schedulesQueryOptions({agentId?,
  includeInactive?})` with `staleTime: 15_000` (schedules change state from
  the worker side, keep it fresher than agents), `useSchedulesQuery`.
- `get-schedule.ts`: `detail(id)` key + suspense hook.
- `list-schedule-runs.ts`: `runs(id)` key, non-suspense `useQuery` with
  `refetchInterval: 15_000` **only while the detail route is mounted** — run
  history is the one surface that changes without user action.
- Mutations (`create`/`update`/`delete`/`pause`/`enable`/`run-now`):
  `useMutation` invalidating `schedulesQueryKeys.lists()` and the detail key;
  `run-now` also invalidates the runs key.
- `preview-schedule.ts`: a mutation (it's a POST with a payload, not cached
  state).

**Verify**: `pnpm lint` → exit 0.

### Step 2: Router, nav, breadcrumbs

- `router.tsx`: `/schedules`, `/schedules/new`, `/schedules/$scheduleId`
  under `appRoute`, `lazyRouteComponent` named exports, added to
  `addChildren`.
- `navigation.ts`: `{ label: "Schedules", to: "/schedules", icon:
  CalendarClockIcon, disabled: false }` placed after the Agents entry
  (`navigation.ts:32-37`). `NavigationItem` requires `icon: LucideIcon` (a
  component reference, not JSX) and the `disabled: false` discriminant; the
  array is `as const`.
- `app-breadcrumbs.tsx`: widen `BreadcrumbRoute` (union at line 13), add the
  `/schedules` branch mirroring the agents branch (list → "Schedules";
  detail → schedule name via a non-suspense query like the agent-name
  breadcrumb query at `app-breadcrumbs.tsx:158`, label consumed at line 116,
  disabled-query fallback `DISABLED_AGENT_BREADCRUMB_QUERY_KEY` at line 26;
  fall back to "Schedule").

**Verify**: `pnpm lint` → exit 0.

### Step 3: List route + table

- `schedules-route.tsx`: header (eyebrow "Automation", h1 "Schedules", "New
  schedule" button), metric cards (`grid md:grid-cols-3`: total active,
  needs-attention count, awaiting-approval count — all computable from the
  list response), `Card` wrapping `SchedulesTable`.
- `schedules-table.tsx`: `EmptyState` (icon + "No schedules yet" + New
  button) when empty; `ResponsiveList` mobile rows + desktop `Table` with
  columns Name/agent, Cadence (humanized: `Every 15 min` / cron string +
  timezone / `Once at …`), Status (`Active`/`Paused` badge + health badge),
  Next run (`formatDateTime`), Last run (from `latest_run`), Actions
  (Configure link).
- `schedule-status-badges.tsx`: health → `Badge` variant map
  (`needs_attention` → destructive, `retrying` → secondary, `healthy` →
  outline, `cancelled` → ghost) and a run-status badge for the nine run
  states (`awaiting_approval` → secondary with shield icon, terminal/failed →
  destructive, completed → default) — follow `run-status-badge.tsx` as a
  pattern only and use the Title Case label helpers. Do NOT import
  `RunStatusBadge`: it is typed to `AgentRunStatus`, a different enum
  (`failed`/`cancelled`, no `retryable_failed`/`terminal_failed`).

**Verify**: `pnpm lint` → exit 0; with `pnpm dev`, `/schedules` renders the
empty state.

### Step 4: Form model + editor

- `schedule-form-model.ts` (pure): `ScheduleFormState` (agent id, type,
  cron expression, interval minutes, run-once datetime-local string,
  timezone, prompt, is_active), `initialScheduleFormState`,
  `validateScheduleFormState` (required agent, required prompt, per-type
  required timing field, interval ≥ 1), `buildSchedulePayload`,
  `isScheduleFormDirty`.
- `schedule-form.tsx`: discriminated `mode: "create" | "edit"` props like
  `agent-form.tsx`; agent `<Select>` fed by the existing `useAgentsQuery`
  (edit mode renders the agent read-only per plan 021 — no re-targeting);
  `schedule-timing-section.tsx` renders the type select and swaps
  cron/interval/once fields plus the timezone select
  (`Intl.supportedValuesOf("timeZone")`, UTC default); prompt `Textarea`;
  active toggle. Keep timing in its own section component — plan 040 adds a
  context section beside it.
- `schedule-preview-panel.tsx`: "Preview next runs" button firing the
  preview mutation with the current timing state; renders the returned
  datetimes or the API error message. Disable while timing fields are
  incomplete.

**Verify**: `pnpm lint` → exit 0; creating a cron schedule via `pnpm dev`
round-trips and redirects to the detail route.

### Step 5: Detail route + run history

- `schedule-detail-route.tsx`: `Tabs` (as `workspace-settings-route.tsx:22-37`)
  with **Settings** (the edit form, keyed `${id}:${updated_at}` to reset on
  refetch, exactly like `agent-detail-route.tsx:139`) and **Run history**.
  Header actions: Pause/Enable (state-dependent), Run now (disabled +
  pending label while the mutation runs; show the 409-on-paused API error via
  `getErrorMessage` in an `Alert`), Delete (confirm via `Dialog`, then
  navigate to the list).
- `schedule-run-history.tsx`: table of runs — Scheduled for, Status badge,
  Attempts, Error (code + truncated message when failed), and links:
  `awaiting_approval` rows get a prominent "Review in conversation" button →
  `/conversations/$conversationId` (decision 1); completed rows get a quiet
  "Open conversation" link when `conversation_id` is set. `EmptyState` for
  no runs.

**Verify**: `pnpm lint` → exit 0 and `pnpm build` → exit 0.

## Test plan

No frontend test harness exists — the checks are `pnpm lint`, `pnpm build`,
and this manual pass against a running API:

1. Create a cron schedule (`*/5 * * * *`, UTC) → appears in list with next
   run populated; audit row visible in DB.
2. Preview with an invalid cron → inline API error; with a valid one → five
   future datetimes.
3. Pause → badge flips to Paused; Run now → 409 alert. Enable → next run
   recomputed. Run now (active) → run appears in history after the worker
   poll.
4. A run that suspends for approval shows the `awaiting_approval` badge and
   the conversation link lands on the inline approval form.
5. Mobile viewport: list collapses to `ResponsiveList` rows; no horizontal
   scroll.

## Done criteria

- [ ] `pnpm lint` exits 0
- [ ] `pnpm build` exits 0
- [ ] `/schedules`, `/schedules/new`, `/schedules/$scheduleId` all render;
      nav item and breadcrumbs present
- [ ] Manual pass above completed (call out any step you could not run, e.g.
      no worker running)
- [ ] No modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 021's routes are absent or their response shapes differ from the
  "Current state" contract (021 not landed or drifted — do not stub the API).
- `src/features/schedules/components/` or `.../routes/` are already
  populated. (The untracked `types.ts` + `api/` modules noted in "Current
  state" are the sanctioned Step 1 starting point — they do NOT trigger this
  STOP.)
- The router/nav/breadcrumb files have structurally changed (e.g. file-based
  routing adopted) since `f83d210`.
- The conversation surface no longer feeds inline approval controls through
  `MessageList` (decision 1 collapses; approval linkage needs a rethink, not
  improvisation).

## Maintenance notes

- Plan 040 adds the active-context section to `schedule-form.tsx` and a
  context column/badge where relevant — keep `schedule-timing-section.tsx`
  self-contained so that lands as a sibling section.
- Plan 023's viewer will render audit events for `agent_schedule` resources;
  the labels introduced in `schedule-status-badges.tsx` should be reused
  there rather than re-mapped.
- The `refetchInterval` on run history is a stopgap for worker-driven state;
  if/when a schedules SSE or notification channel exists (029 notification
  policy), remove the polling.
- Reviewers should scrutinize: no duplicated approval UI, form reset on
  refetch (`key`), and that every new API module scopes its query keys by
  workspace.
