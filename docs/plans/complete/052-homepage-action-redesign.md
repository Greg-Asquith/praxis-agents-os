# Plan 052: Action-driven homepage redesign

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c65f946..HEAD -- apps/web/src/routes/home.tsx apps/web/src/features/conversations/ apps/web/src/features/schedules/ apps/web/src/features/agents/ apps/web/src/app/router.tsx apps/api/routes/agent_runs/ apps/api/services/agent_runs/`
> Compare the "Current state" excerpts against live code before proceeding;
> treat a structural mismatch (suspended-run-state seam, conversation list
> response shape, schedule `health`/`latest_run` fields) as a STOP
> condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (one new read endpoint touches the suspended-run-state
  seam; everything else is frontend recomposition of existing data)
- **Depends on**: none hard — consumes landed surfaces from 007/008
  (conversations + approvals), 021/022 (schedule health), 019 (agents UI).
  Soft: none.
- **Category**: Lane O operational surfaces (post-roadmap addition; plan
  numbers 021–051 were reserved by `000_MASTER_ROADMAP.md`, this is the
  first plan past that range)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07.
  **Re-verified and updated 2026-07-28 at `c65f946`** — since planning,
  the stat tiles and nav-duplicate cards were already removed from
  `home.tsx` by unrelated tidying commits, the new-conversation page
  moved agent selection into `ConversationComposer`, run cancellation
  added a third `/agent-runs/{run_id}` route, and the web app grew a
  real Vitest suite (SSR-string component tests). All anchors below
  reflect `c65f946`.
- **Execution progress**: **Complete 2026-07-28.** The actor-scoped
  pending-approvals endpoint, action-led Home composition, polling query,
  schedule/unread/recent partitions, agent launcher, and validated
  composer preselection are implemented. API lint/format passed; the
  complete agent-run service/route slice passed 34 tests; and `pnpm check`
  passed 84 web test files / 408 tests plus typecheck, lint, formatting,
  dead-code, architecture, and production-build gates. The local web app
  responded on port 3000, but interactive visual QA was unavailable
  because the execution environment exposed no browser instance.

## Product intent

The current homepage is a status report. The redesign makes it a work
surface. The test for every element: *a workspace member logging in on a
normal morning should be able to act on it* — decide something, read a
result, resume work, or start work. Anything that is merely informative
(counts of agents, workspace metadata, account cards) is navigation-duplicated
noise and goes.

What that member actually needs, in priority order:

1. **What is blocked on me?** Agent runs suspended on approval decisions.
   Today the home page shows a count and an undifferentiated conversation
   list; it should show *which agent wants to do what, where, since when* —
   one click from the decision.
2. **What came back while I was away?** Unread conversations — especially
   scheduled and delegated runs that completed overnight and are sitting on
   results nobody has read.
3. **What is broken?** Schedules whose latest runs are failing
   (`needs_attention` / `retrying`) — silent failures are missed work.
4. **Let me continue.** Recent conversations, one click to re-enter.
5. **Let me start.** Active agents as launch targets, not a count — pick an
   agent, land in the composer with it preselected.

## Decisions taken

1. **Kill all aggregate stats.** Largely already done: commits
   `33427c8 Web - UI Tidying` and `b011664 Web - Remove Cards` deleted
   the four `SummaryTile`s (including the "Approval-gated agents" tile
   hardcoded to `value={0}`) and the nav-duplicate bottom card row after
   this plan was written. The decision stands as the page's bar — no
   stats, counts, or nav-duplicate cards come back — but the remaining
   work is recomposition of what's left (two panels + a "Dashboard"
   title), not demolition.
2. **One aggregated pending-approvals read endpoint.**
   `GET /api/v1/agent-runs/pending-approvals` returns every top-level run
   awaiting approval for the actor in the workspace, with enough context to
   render an inbox row without further requests: conversation id + title,
   agent name, awaiting-since timestamp, pending tool names, and delegated
   child agent names. The alternative — client-side fan-out calling the
   existing per-run `GET /agent-runs/{run_id}/approval-state` for each
   `needs_approval` conversation — was rejected: N+1 request waterfalls on
   the landing page, and the conversation list only says *that* something is
   pending, never *what*.
3. **Approve/deny stays in the conversation.** No inline decision buttons on
   home. Resuming a run streams over SSE bound to the conversation surface
   (`resume-run-stream.ts`), and deciding responsibly needs context — the
   tool args and the prior turns. Home shows tool *names* only (scannable),
   never args, and deep-links to the conversation where the existing
   approval controls render. If inline decisions are ever wanted, that is a
   separate plan with its own approval-UX review.
4. **The endpoint reuses the suspended-state seam, scoped like every other
   run read.** Query: `AgentRun` where `status = awaiting_approval`,
   `workspace_id`, `user_id = actor.id`, `deleted = false`, **and
   `parent_run_id IS NULL`** — delegated child runs awaiting approval
   surface through their parent (the same rule that keeps delegated
   conversations out of the conversation list,
   `services/conversations/list_conversations.py:37`). Per run, reuse
   `load_suspended_run_state` + `tool_args_for_display`-adjacent projection
   exactly as `get_agent_run_approval_state` does
   (`services/agent_runs/get_approval_state.py:60-113`), but project names
   only (decision 3). Ordered oldest-waiting first; capped at 20 with a
   `total` so the UI can say "and N more". Awaiting runs are structurally
   few (each blocks a conversation), so per-run state loading is bounded.
5. **"New results" and "Continue" ride the existing conversations list.**
   `GET /conversations/` is already actor-scoped
   (`list_conversations.py:36` — `user_id == actor.id`), so home is
   inherently "my work" with no backend change. Unread conversations
   (`unread` flag) render as the results section with source badges
   (scheduled/delegated/event completions are the interesting ones —
   `ConversationSource` gained `"event"` for webhook-triggered runs, and
   `ConversationList` already renders source badges for all three);
   recent non-unread conversations render as the continue section.
   Client-side partition of one query — no new API.
6. **Failing schedules only, hidden when healthy.** A section listing
   workspace schedules whose `health` is `needs_attention` or `retrying`
   (fields already on `SchedulesListResponse` items with `latest_run`,
   `features/schedules/types.ts`), linking to the schedule detail and, when
   `latest_run.conversation_id` is set, the run's conversation. When
   nothing is failing the section renders nothing — the page stays
   action-only, no green "all systems normal" filler.
7. **Agent launcher instead of agent counts.** Active agents render as
   launch tiles that navigate to `/conversations/new?agent=<id>`; the
   new-conversation route gains a validated optional `agent` search
   param. There is no standalone agent picker on that page anymore —
   selection lives inside `ConversationComposer` (create mode holds
   `selectedAgentId` state defaulting to the first active agent,
   `conversation-composer.tsx:84-94`) — so the param preselects via a
   new optional `initialAgentId` prop on the composer that seeds that
   state when it matches an active agent, ignored silently otherwise
   (maintainer decision, 2026-07-28: adapt the preselect to the
   composer rather than drop it). Additive change to
   `new-conversation-route.tsx`, `conversation-composer.tsx`, and the
   route definition in `src/app/router.tsx:157-173`. Tiles show name +
   description line; capped display (8) with a "All agents" link.
8. **Section order = decision priority.** Waiting on you → Failing
   schedules → New results → Continue → Start with an agent. The "New
   Conversation" primary CTA stays in the header. The page title changes
   from "Dashboard" to "Home" and the subtitle describes actions, not
   telemetry.
9. **Composition:** `routes/home.tsx` becomes a thin shell; the sections
   live in a new `features/home/` feature (`components/` only — its data
   comes from the conversations/schedules/agents feature APIs). The new
   API module lives at
   `features/conversations/api/list-pending-approvals.ts` (agent-run reads
   already live in that feature: `get-approval-state.ts`). Cross-feature
   imports (home → conversations/schedules/agents) do not violate the
   dependency-cruiser layering (only feature→route-shell and cycles are
   banned); `pnpm arch` is the arbiter.
10. **Freshness is polling-light, not streaming.** The pending-approvals
    query uses `staleTime` 15s + `refetchInterval` 30s (the landing page
    should notice a newly suspended run without a manual reload); the
    conversations and schedules queries keep their existing `staleTime`
    behavior. No SSE on home, no notifications wiring — the notifications
    service still has no routes, and surfacing it is a future plan, not a
    side effect of this one.
11. **Empty states are launch states.** A brand-new member with nothing
    pending, nothing unread, and no history sees the agent launcher as the
    hero plus a single explanatory empty card — not five empty panels.
    Sections with no content collapse (approvals section always renders —
    an explicit "Nothing waiting on you" is the one permitted all-clear,
    because "am I blocked?" is the question the page exists to answer).

## Why this matters

The homepage is the highest-traffic screen in the product and currently
optimizes for the wrong persona: it reads like an admin status board
(counts, workspace metadata, account info) when the daily user is a
workspace member whose job flows *through* agents — deciding approvals,
reading results, chasing failures, starting runs. Every session that starts
with "scan four stat tiles, ignore four nav-duplicate cards, then hunt in a
mixed list" is friction on the product's core loop. An action-driven home
also gives approvals the visibility their governance role demands: a
suspended run is a person being waited on, and the current UI renders that
as a number.

## Current state

All anchors re-verified at `c65f946` (2026-07-28).

- **Homepage**: `apps/web/src/routes/home.tsx` — now a 131-line route
  file: one `useSuspenseQuery(conversationsQueryOptions({ limit: 10 }))`
  (line 20); "needs attention" filter `needs_approval || unread`
  (lines 25-29); `PageHeader` titled "Dashboard" with a "New
  Conversation" CTA (33-42); "Needs attention" panel (45-69); "Recent
  conversations" panel (71-101); local `DashboardPanel` component
  (107-130). The stat tiles, `SummaryTile`, and nav-duplicate cards are
  already gone (removed by `33427c8`/`b011664`).
  `apps/web/src/features/home/` does not exist yet.
- **Conversation list data**: `GET /conversations/` is actor-scoped and
  excludes delegated conversations
  (`services/conversations/list_conversations.py:34-39`; actor scope
  line 36, delegated exclusion line 38; pagination now goes through
  `utils.pagination.paginate`, contract unchanged); each row carries
  `unread`, `source`, `needs_approval`, `active_run_id`,
  `active_run_status`, `agent_name`, `last_message_at`
  (`features/conversations/types.ts:11-31`; `ConversationSource` now
  includes `"event"`). Frontend query: `conversationsQueryOptions` with
  `staleTime` 15s and structured workspace-scoped keys
  (`api/list-conversations.ts:20-35,71-77`).
- **Approval reads**: per-run only —
  `GET /agent-runs/{run_id}/approval-state`
  (`routes/agent_runs/get_approval_state.py`, router prefix `/agent-runs`
  in `routes/agent_runs/__init__.py`, which now composes three routers:
  `cancel_run_router`, `get_approval_state_router`, `resume_run_router` —
  all `/{run_id}/...` patterns, so the literal `/pending-approvals` must
  register before all of them). The service
  (`services/agent_runs/get_approval_state.py`, unchanged since
  `c2f08cc`) loads `load_suspended_run_state(run)` at line 60 and
  projects `PendingToolApprovalRead(tool_call_id, name, args,
  delegation)` + `PendingDelegatedApprovalRead` (lines 63-113) —
  including walking delegated child runs via
  `load_delegated_child_run_for_approval` (`utils.py:143-172`). Schemas
  at `services/agent_runs/schemas.py:56-67`. No pending-approvals
  aggregate endpoint exists anywhere. Existing service tests:
  `tests/services/agent_runs/test_approval_state.py` (the
  `approval_context` fixture and suspended-run helpers live there —
  reuse them). Frontend: `features/conversations/api/get-approval-state.ts`
  exists; `list-pending-approvals.ts` does not.
- **Run status vocabulary**: `RUN_STATUS_AWAITING_APPROVAL` et al. in
  `services/agent_runs/domain.py:15`; the conversation list already
  builds an awaiting-runs projection from the same statuses
  (`list_conversations.py:21-23,40-58`). `AgentRun` has `parent_run_id`
  (`models/agent_run.py:45-49`), `deleted` via `SoftDeleteMixin`, and
  **no dedicated awaiting-since column** (verified 2026-07-28:
  timestamps are only `started_at`/`completed_at`/`failed_at`/
  `lease_expires_at` + created/updated) — `updated_at` is the right
  ordering column, and it is stamped at suspend time because
  `transition_run_status` writes the row on the awaiting transition.
  The partial index `ix_agent_runs_workspace_status` on
  `(workspace_id, status) WHERE deleted = false`
  (`agent_run.py:114-119`) serves the planned query.
- **Schedules**: `GET /schedules` list items carry computed `health`
  (`"healthy" | "retrying" | "needs_attention" | "cancelled"`,
  `features/schedules/types.ts:7`) and `latest_run` (with
  `conversation_id`, `last_error_message`) (`types.ts:64-65`); frontend
  query module `features/schedules/api/list-schedules.ts` — note
  `schedulesQueryOptions` is module-private; only `useSchedulesQuery`
  and `schedulesQueryKeys` are exported (export the options or use the
  hook).
- **Agents**: `agentsQueryOptions({ includeInactive, limit, offset })`
  (`features/agents/api/list-agents.ts:31-37`). `countActiveAgents` was
  already removed by `33427c8`; `agent-metrics.ts` now exports only
  `countApprovalPolicyTools`.
- **New-conversation route**: `/conversations/new` defined in
  `src/app/router.tsx:157-173` as a child of `conversationRuntimeRoute`,
  with a loader prefetching agents + model catalog; no `validateSearch`.
  `new-conversation-route.tsx` no longer contains an agent picker — it
  renders stacked agent icons and delegates selection to
  `<ConversationComposer mode="create" agents={...} />`; preselection
  must go through the composer (decision 7).
- **Conversation list component**:
  `features/conversations/components/conversation-list.tsx` props are
  `conversations`, `emptyState`, `selectedConversationId`,
  `showRunStatus`; it already renders source badges for
  scheduled/delegated/event rows (lines 78-90) — no new prop needed.
- **Navigation**: sidebar currently holds Home/Agents/Skills/Memory/
  Knowledge Base/Files/Artifacts/Schedules/Integrations
  (`src/config/navigation.ts:32-87`). Plan frontend-ui/034 will
  consolidate it to five items; the two plans touch disjoint files.
- **Layering**: `.dependency-cruiser.cjs` bans cycles, feature→route-shell
  imports, and `components/ui` reaching upward; cross-feature imports are
  legal (newer rules constrain `src/integrations/**` and
  `components/tool-ui`, not `features/`). `pnpm check` = typecheck +
  eslint (0 warnings) + **vitest** + prettier + knip + depcruise + build.
  The web test suite is now ~80 files under `apps/web/tests/`
  (`vitest.config.ts` includes `tests/**/*.test.ts` only, node
  environment) and includes component tests written as
  `renderToStaticMarkup` SSR-string assertions (e.g.
  `tests/features/conversations/components/message-row.test.ts`) — no
  jsdom or testing-library.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint (API) | `cd apps/api && uv run ruff check .` | exit 0 |
| Format (API) | `cd apps/api && uv run ruff format --check .` | exit 0 |
| API tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agent_runs tests/routes/agent_runs -q` | all pass |
| Frontend gate | `cd apps/web && pnpm check` | typecheck, eslint (0 warnings), prettier, knip, depcruise, build all pass |
| Manual smoke | `make dev` then load `/` | sections render per decision 8 |

## Scope

**In scope (API):**

- `apps/api/services/agent_runs/list_pending_approvals.py` (create)
- `apps/api/services/agent_runs/schemas.py` (add
  `PendingApprovalRunRead`, `PendingApprovalsListResponse`)
- `apps/api/services/agent_runs/__init__.py` (re-export)
- `apps/api/routes/agent_runs/list_pending_approvals.py` (create) +
  `routes/agent_runs/__init__.py` (compose)
- `apps/api/tests/services/agent_runs/test_list_pending_approvals.py` +
  a route test in the existing `apps/api/tests/routes/agent_runs/`
  directory (it already holds `test_cancel_run_route.py` — follow its
  conventions)

**In scope (Web):**

- `apps/web/src/routes/home.tsx` (rewrite as a thin shell)
- `apps/web/src/features/home/` (create): `components/approvals-inbox.tsx`,
  `components/schedule-attention.tsx`, `components/unread-results.tsx`,
  `components/recent-conversations.tsx`, `components/agent-launcher.tsx`,
  `components/home-section.tsx` (shared panel shell replacing the local
  `DashboardPanel`)
- `apps/web/src/features/conversations/api/list-pending-approvals.ts`
  (create) + `features/conversations/types.ts` (response types)
- `apps/web/src/features/conversations/routes/new-conversation-route.tsx`,
  `apps/web/src/features/conversations/components/conversation-composer.tsx`
  (`initialAgentId` prop) + `src/app/router.tsx` (`agent` search param,
  decision 7)
- `apps/web/tests/features/home/` (create): SSR-string component tests
  for the new sections, in the existing `renderToStaticMarkup` style

**Out of scope (do NOT touch):**

- Inline approve/deny on home, any resume/SSE wiring outside the
  conversation surface (decision 3).
- The notifications service and any notification routes/UI.
- The conversations list API contract (no new filters — partition
  client-side, decision 5) and the SSE protocol (no new event names).
- Schedule routes/services; the schedule health computation.
- Files/audit/skills widgets on home — future candidates, not this plan.
- Navigation config, sidebar layout, any other route shell.

## Git workflow

- Branch: `advisor/052-homepage-action-redesign`
- Commit style: `API - Pending Approvals List` / `Web - Action-Driven Home`
  (two commits; API first so the web slice always has its backend)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Pending-approvals list service

`services/agent_runs/list_pending_approvals.py` —
`list_pending_agent_run_approvals(db, *, actor, workspace, limit=20) ->
PendingApprovalsListResponse`:

1. Select top-level awaiting runs (decision 4 filters:
   `status == RUN_STATUS_AWAITING_APPROVAL`, workspace, actor,
   `deleted == False`, `parent_run_id IS NULL`) joined to `Conversation`
   (title) and `Agent` (name), ordered by `AgentRun.updated_at`
   ascending (verified 2026-07-28: no dedicated awaiting-since column
   exists, and `updated_at` is stamped at the awaiting transition —
   see Current state), limited, plus a `total` count. The
   `ix_agent_runs_workspace_status` partial index covers the filter.
2. Per run, `load_suspended_run_state(run)` and project pending tool
   names: top-level (non-delegated) approvals contribute
   `approval.tool_name`; delegated approvals contribute the child agent
   name into `delegated_agent_names` (walk
   `load_delegated_child_run_for_approval` exactly as
   `get_approval_state.py:63-96` does, but project names only — no args,
   decision 3). If a run's suspended state fails to load, skip the row and
   log — one corrupt run must not 500 the homepage (mirror whatever
   `load_suspended_run_state` raises; do not blanket-except).
3. Response shapes in `schemas.py`:

```python
class PendingApprovalRunRead(BaseModel):
    run_id: UUID
    conversation_id: UUID
    conversation_title: str | None
    agent_id: UUID | None
    agent_name: str | None
    awaiting_since: datetime
    pending_tool_names: list[str]
    delegated_agent_names: list[str]

class PendingApprovalsListResponse(BaseModel):
    items: list[PendingApprovalRunRead]
    total: int
```

**Verify**: `uv run ruff check .` exit 0.

### Step 2: Route

`routes/agent_runs/list_pending_approvals.py` — `GET /pending-approvals`
under the existing `/agent-runs` router (register in
`routes/agent_runs/__init__.py` **before** the three existing `/{run_id}`
pattern routers — cancel, approval-state, resume — so the literal path
cannot be captured as a run id). Standard deps
(`AsyncDbSessionDep`, `CurrentUserDep`, `CurrentWorkspaceDep`) — member
read access, same as the per-run approval-state route; no new RBAC.

**Verify**: route registry lists
`GET /api/v1/agent-runs/pending-approvals`; manual curl with a suspended
run returns the row with tool names; with none returns
`{"items": [], "total": 0}`.

### Step 3: API tests

`tests/services/agent_runs/test_list_pending_approvals.py` (reuse the
`approval_context` fixture and suspended-run helpers from
`test_approval_state.py`; `pytestmark = pytest.mark.asyncio`, DB tests
skip without `TEST_DATABASE_URL`):

- returns awaiting runs with correct `pending_tool_names` and
  `awaiting_since`, oldest first
- excludes: other users' runs, other workspaces' runs, non-awaiting
  statuses, deleted runs, **delegated child runs** (a parent+child awaiting
  pair yields exactly one row, with the child agent's name in
  `delegated_agent_names`)
- `total` reflects rows beyond `limit`
- route test: 200 shape, workspace header required, unauthenticated 401

**Verify**: the API tests command in the table passes.

### Step 4: Frontend data module

`features/conversations/api/list-pending-approvals.ts` — one operation:
`pendingApprovalsQueryOptions()` (workspace-scoped key under
`conversationsQueryKeys.workspace()`, `staleTime` 15s,
`refetchInterval` 30s per decision 10) + `useSuspenseQuery` hook. Types in
`features/conversations/types.ts` (`type` aliases). All through
`lib/api/client.ts`.

**Verify**: typecheck passes.

### Step 5: Home rewrite

`features/home/components/` per decision 9, composed by a thin
`routes/home.tsx` (header: workspace name, "Home" title, action subtitle,
"New Conversation" CTA — then sections in decision 8 order):

- `approvals-inbox.tsx` — always renders. Rows: agent name + conversation
  title, pending tool names as badges (delegated entries as
  "via {child agent}"), relative awaiting-since, whole row links to
  `/conversations/$conversationId`. Footer "and N more" when
  `total > items.length`. Empty: one-line "Nothing waiting on you"
  (decision 11).
- `schedule-attention.tsx` — filters the existing schedules query
  (`useSchedulesQuery`, or export the module-private
  `schedulesQueryOptions`) for
  `health === "needs_attention" || health === "retrying"`; renders nothing
  when empty (decision 6). Rows: schedule agent/prompt summary, health
  badge, `latest_run.last_error_message` truncated, links to the schedule
  and (when present) the run conversation.
- `unread-results.tsx` — `conversations.filter(c => c.unread &&
  !c.needs_approval)` (approval rows already live in the inbox), rendered
  via the existing `ConversationList` (it already shows
  scheduled/delegated/event source badges — no new prop needed);
  renders nothing when empty.
- `recent-conversations.tsx` — remaining conversations (not unread, not
  needs-approval), `ConversationList`, cap 6, "View All" action.
- `agent-launcher.tsx` — active agents (`useAgentsQuery({
  includeInactive: false })`) as tiles (name + truncated description) →
  `/conversations/new?agent=<id>`; cap 8 + "All agents" link; when the
  workspace has no history at all this section leads (decision 11).
- `home-section.tsx` — the shared titled panel (port of `DashboardPanel`).

Retire the local `DashboardPanel` (its replacement is
`home-section.tsx`) and drop any now-unused imports. The stat tiles and
bottom card row are already gone — nothing to delete there.

**Verify**: `pnpm check` passes (knip will catch anything orphaned by the
rewrite; depcruise validates the home feature's imports).

### Step 6: Agent preselect on the composer route

Add `validateSearch` to the `/conversations/new` route
(`src/app/router.tsx:157-173`) parsing an optional `agent: string`
(discard non-UUID-ish values rather than erroring). In
`new-conversation-route.tsx`, read the param and pass it to
`ConversationComposer` as a new optional `initialAgentId` prop
(create mode only); the composer seeds its `selectedAgentId` state with
it when it matches an active agent, and ignores it silently otherwise
(decision 7).

**Verify**: `pnpm check`; manual — launcher tile lands on the composer
with the agent preselected; a bogus `?agent=` value falls back to the
composer's default (first active agent).

### Step 7: Component tests

`apps/web/tests/features/home/` — SSR-string tests in the existing
style (`renderToStaticMarkup` + `QueryClientProvider` wrapper, `.ts`
files only — the vitest include glob is `tests/**/*.test.ts`; see
`tests/features/conversations/components/message-row.test.ts`):

- approvals inbox: renders a row's agent name, tool-name badges,
  "via {child agent}" for delegated entries, and the "and N more"
  footer; renders "Nothing waiting on you" when empty
- schedule attention: renders only `needs_attention`/`retrying`
  schedules; renders nothing when all healthy
- unread/recent partition: an unread non-approval conversation lands in
  results, a read one in continue, an approval one in neither

**Verify**: `pnpm test` passes.

### Step 8: Manual smoke

With `make dev` and seeded data: suspend a run on an approval-gated tool →
it appears at the top of home within the 30s poll; deciding it in the
conversation clears it; a failing schedule shows in the attention section;
an unread scheduled conversation shows under new results; empty workspace
shows launcher-led layout.

## Test plan

Backend: Step 3 (~8-10 tests) pins the new endpoint's scoping (actor,
workspace, deleted, delegated-child exclusion), projection (tool names,
delegated agent names, ordering, total), and route auth. Frontend: the
static gate (`pnpm check`, which now includes vitest) plus Step 7's
SSR-string component tests (maintainer decision, 2026-07-28 — the repo
now has an established component-test convention) and the Step 8 manual
script.

## Done criteria

- [x] `uv run ruff check .` and `uv run ruff format --check .` exit 0; no
      migrations added (read-only endpoint)
- [x] `TEST_DATABASE_URL=... uv run pytest tests/services/agent_runs
      tests/routes/agent_runs -q` exits 0
- [x] `GET /api/v1/agent-runs/pending-approvals` returns tool names for a
      suspended run and exactly one row for a delegated parent+child pair
- [x] `cd apps/web && pnpm check` exits 0 (includes the new home
      component tests)
- [x] `routes/home.tsx` is a thin shell over `features/home/`; the page
      title is "Home"; no stats, counts, or nav-duplicate cards return;
      every section on the page links to an action
- [x] Approvals render with tool names and deep-link to the conversation;
      no approve/deny controls exist on home
- [x] `/conversations/new?agent=<id>` preselects the agent in the
      composer; invalid values degrade silently
- [x] No SSE protocol changes (`stream/protocol.ts` untouched); no new
      conversation list filters
- [x] Plan-owned changes remain within the in-scope list;
      `docs/plans/000_README.md` row updated. Concurrent unrelated
      worktree edits were preserved unchanged.

## STOP conditions

Stop and report back (do not improvise) if:

- `load_suspended_run_state` / `load_delegated_child_run_for_approval`
  have changed shape since `c65f946` such that projecting tool names
  requires new deserialization logic — do not fork the seam.
- A pending-approvals (or notifications-backed) aggregate endpoint already
  exists.
- The conversation list response no longer carries `unread` /
  `needs_approval` / `source`, or schedules no longer expose `health` +
  `latest_run` — the frontend partition depends on them.
- `pnpm arch` rejects the home feature's cross-feature imports — restructure
  per the rules, and if that forces moving shared pieces into `lib/`,
  report before doing a layering refactor.
- The new-conversation surface has been redesigned again such that
  `ConversationComposer` no longer owns agent selection in create mode
  (the `initialAgentId` mechanism in decision 7 assumes it does).
- You feel the need to add inline approve/deny, a home SSE stream, a
  notifications feed, or new conversation-list query parameters — scope
  creep; record a follow-up instead.

## Maintenance notes

- **The homepage bar**: future additions must pass the Product-intent test —
  each element is something a member acts on. Stats, charts, and counts go
  to a future admin/reporting surface, not here.
- **Notifications**: when the notifications service grows routes, the
  30s poll on pending approvals (decision 10) is the first thing it should
  replace. Keep the query module's surface small so swapping the transport
  is contained.
- **Pending-approvals endpoint** is deliberately names-only. If a future
  surface needs args (e.g. an approvals-review screen), extend the per-run
  `approval-state` contract, not this list — the list stays cheap and
  scannable.
- **Files/audit widgets**: the files processing status endpoint
  (`/api/v1/files/processing`) and the audit feed were considered and left
  out — neither is daily-member work. Revisit if file extraction failures
  become a recurring user-visible problem.
- Reviewers should scrutinize: the `parent_run_id IS NULL` exclusion (a
  delegated child leaking in double-counts a decision), the literal-route
  registration order in `routes/agent_runs/__init__.py`, and that the
  corrupt-run skip in Step 1 logs rather than silently hiding rows.
