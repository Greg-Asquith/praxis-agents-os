# Plan 052: Action-driven homepage redesign

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/web/src/routes/home.tsx apps/web/src/features/conversations/ apps/web/src/features/schedules/ apps/web/src/features/agents/ apps/web/src/app/router.tsx apps/api/routes/agent_runs/ apps/api/services/agent_runs/`
> Plan 036's working-tree changes (multimodal input) may not yet be committed
> at execution time — they touch `features/conversations/` but not the files
> this plan rewrites. Compare the "Current state" excerpts against live code
> before proceeding; treat a structural mismatch (suspended-run-state seam,
> conversation list response shape, schedule `health`/`latest_run` fields)
> as a STOP condition.

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
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07 (036 in
  flight on disk; its diff does not overlap this plan's files)

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

1. **Kill all aggregate stats.** The four `SummaryTile`s
   (`routes/home.tsx:87-112`) are removed, including the "Approval-gated
   agents" tile that has been hardcoded to `value={0}` since it shipped
   (`home.tsx:110`) — evidence that the stats row is decoration, not
   information. The bottom card row (Workspace / Workspaces / Agents /
   Account, `home.tsx:178-244`) is removed too: every one of those
   destinations is already one click away in the sidebar
   (`config/navigation.ts`), and none of them is daily work.
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
   (scheduled/delegated completions are the interesting ones); recent
   non-unread conversations render as the continue section. Client-side
   partition of one query — no new API.
6. **Failing schedules only, hidden when healthy.** A section listing
   workspace schedules whose `health` is `needs_attention` or `retrying`
   (fields already on `SchedulesListResponse` items with `latest_run`,
   `features/schedules/types.ts`), linking to the schedule detail and, when
   `latest_run.conversation_id` is set, the run's conversation. When
   nothing is failing the section renders nothing — the page stays
   action-only, no green "all systems normal" filler.
7. **Agent launcher instead of agent counts.** Active agents render as
   launch tiles that navigate to `/conversations/new?agent=<id>`; the
   new-conversation route gains a validated optional `agent` search param
   that preselects that agent in the existing picker. Additive change to
   `new-conversation-route.tsx` + the route definition in
   `src/app/router.tsx:116`. Tiles show name + description line; capped
   display (8) with a "All agents" link.
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

All anchors verified on the working tree at `c2f08cc` (2026-07-07).

- **Homepage**: `apps/web/src/routes/home.tsx` — single route file holding
  the whole dashboard: `useSuspenseQueries` over current user, agents
  (`includeInactive: true, limit: 100`), and conversations (`limit: 10`)
  (lines 44-50); four `SummaryTile`s incl. the hardcoded `value={0}`
  approval tile (87-112); "Needs attention" panel filtering
  `needs_approval || unread` client-side (58-62, 115-141); "Recent
  conversations" panel (143-176); the four nav-duplicate cards (178-244);
  local `SummaryTile`/`DashboardPanel` components (249-302).
- **Conversation list data**: `GET /conversations/` is actor-scoped and
  excludes delegated conversations
  (`services/conversations/list_conversations.py:33-38`); each row carries
  `unread`, `source`, `needs_approval`, `active_run_id`,
  `active_run_status`, `agent_name`, `last_message_at`
  (`features/conversations/types.ts:9-29`). Frontend query:
  `conversationsQueryOptions` with `staleTime` 15s and structured
  workspace-scoped keys (`api/list-conversations.ts:20-34,74-80`).
- **Approval reads**: per-run only —
  `GET /agent-runs/{run_id}/approval-state`
  (`routes/agent_runs/get_approval_state.py`, router prefix `/agent-runs`
  in `routes/agent_runs/__init__.py`). The service
  (`services/agent_runs/get_approval_state.py:30-120`) loads
  `load_suspended_run_state(run)` and projects
  `PendingToolApprovalRead(tool_call_id, name, args, delegation)` +
  `PendingDelegatedApprovalRead` — including walking delegated child runs
  via `load_delegated_child_run_for_approval`. Schemas at
  `services/agent_runs/schemas.py:61-65`. Existing service tests:
  `tests/services/agent_runs/test_approval_state.py` (factories/support
  helpers for suspended runs live there — reuse them).
- **Run status vocabulary**: `RUN_STATUS_AWAITING_APPROVAL` et al. in
  `services/agent_runs/domain.py`; the conversation list already builds an
  awaiting-runs projection from the same statuses
  (`list_conversations.py:20-22,40-58`).
- **Schedules**: `GET /schedules` list items carry computed `health`
  (`"healthy" | "retrying" | "needs_attention" | "cancelled"`) and
  `latest_run` (with `conversation_id`, `last_error_message`)
  (`features/schedules/types.ts`); frontend query module
  `features/schedules/api/list-schedules.ts`.
- **Agents**: `agentsQueryOptions({ includeInactive, limit })`
  (`features/agents/api/list-agents.ts`); `Agent.is_active` and
  `countActiveAgents` helper (`features/agents/agent-metrics.ts:5-7` —
  after this plan its only remaining consumer is the agents feature;
  knip flags it if orphaned).
- **New-conversation route**: `/conversations/new` defined in
  `src/app/router.tsx:116`; `new-conversation-route.tsx` renders the agent
  picker from `useAgentsQuery({ includeInactive: false })` with no
  preselection mechanism today.
- **Navigation**: sidebar items for Home/Agents/Skills/Files/Schedules/
  Workspaces/Settings (`src/config/navigation.ts`) — everything the removed
  card row linked to.
- **Layering**: `.dependency-cruiser.cjs` bans cycles, feature→route-shell
  imports, and `components/ui` reaching upward; cross-feature imports are
  legal. `pnpm check` = typecheck + eslint (0 warnings) + prettier + knip +
  depcruise + build; there IS now a Vitest lane (C01) but it covers the
  stream parser/reducer — no component test framework.

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
  `apps/api/tests/routes/agent_runs/` route test (create dir if absent,
  following `tests/routes/README.md` conventions)

**In scope (Web):**

- `apps/web/src/routes/home.tsx` (rewrite as a thin shell)
- `apps/web/src/features/home/` (create): `components/approvals-inbox.tsx`,
  `components/schedule-attention.tsx`, `components/unread-results.tsx`,
  `components/recent-conversations.tsx`, `components/agent-launcher.tsx`,
  `components/home-section.tsx` (shared panel shell replacing the local
  `DashboardPanel`)
- `apps/web/src/features/conversations/api/list-pending-approvals.ts`
  (create) + `features/conversations/types.ts` (response types)
- `apps/web/src/features/conversations/routes/new-conversation-route.tsx` +
  `src/app/router.tsx` (`agent` search param, decision 7)
- `apps/web/src/features/agents/agent-metrics.ts` (delete
  `countActiveAgents` if knip reports it orphaned after the rewrite)

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
   (title) and `Agent` (name), ordered by the run's awaiting-since
   timestamp ascending (use `AgentRun.updated_at` — the moment the run
   suspended; verify against the model and record if a better column
   exists), limited, plus a `total` count.
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
`routes/agent_runs/__init__.py` **before** any `/{run_id}` pattern route so
the literal path cannot be captured as a run id). Standard deps
(`AsyncDbSessionDep`, `CurrentUserDep`, `CurrentWorkspaceDep`) — member
read access, same as the per-run approval-state route; no new RBAC.

**Verify**: route registry lists
`GET /api/v1/agent-runs/pending-approvals`; manual curl with a suspended
run returns the row with tool names; with none returns
`{"items": [], "total": 0}`.

### Step 3: API tests

`tests/services/agent_runs/test_list_pending_approvals.py` (reuse the
suspended-run fixtures/helpers from `test_approval_state.py`;
`pytestmark = pytest.mark.asyncio`, DB tests skip without
`TEST_DATABASE_URL`):

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
- `schedule-attention.tsx` — filters the existing schedules query for
  `health === "needs_attention" || health === "retrying"`; renders nothing
  when empty (decision 6). Rows: schedule agent/prompt summary, health
  badge, `latest_run.last_error_message` truncated, links to the schedule
  and (when present) the run conversation.
- `unread-results.tsx` — `conversations.filter(c => c.unread &&
  !c.needs_approval)` (approval rows already live in the inbox), rendered
  via the existing `ConversationList` with `sourceVisibility="always"`;
  renders nothing when empty.
- `recent-conversations.tsx` — remaining conversations (not unread, not
  needs-approval), `ConversationList`, cap 6, "View All" action.
- `agent-launcher.tsx` — active agents (`useAgentsQuery({
  includeInactive: false })`) as tiles (name + truncated description) →
  `/conversations/new?agent=<id>`; cap 8 + "All agents" link; when the
  workspace has no history at all this section leads (decision 11).
- `home-section.tsx` — the shared titled panel (port of `DashboardPanel`).

Delete the `SummaryTile` component, the stats grid, and the bottom card
row. Drop the now-unused imports; remove `countActiveAgents` only if knip
flags it.

**Verify**: `pnpm check` passes (knip will catch anything orphaned by the
rewrite; depcruise validates the home feature's imports).

### Step 6: Agent preselect on the composer route

Add `validateSearch` to the `/conversations/new` route
(`src/app/router.tsx:116`) parsing an optional `agent: string` (discard
non-UUID-ish values rather than erroring). In
`new-conversation-route.tsx`, use it as the initial picker selection when
it matches an active agent; ignore silently otherwise.

**Verify**: `pnpm check`; manual — launcher tile lands on the composer
with the agent preselected; a bogus `?agent=` value falls back to the
unselected picker.

### Step 7: Manual smoke

With `make dev` and seeded data: suspend a run on an approval-gated tool →
it appears at the top of home within the 30s poll; deciding it in the
conversation clears it; a failing schedule shows in the attention section;
an unread scheduled conversation shows under new results; empty workspace
shows launcher-led layout.

## Test plan

Backend: Step 3 (~8-10 tests) pins the new endpoint's scoping (actor,
workspace, deleted, delegated-child exclusion), projection (tool names,
delegated agent names, ordering, total), and route auth. Frontend: the
static gate (`pnpm check`) plus the Step 7 manual script — there is no
component test framework, and this plan does not introduce one.

## Done criteria

- [ ] `uv run ruff check .` and `uv run ruff format --check .` exit 0; no
      migrations added (read-only endpoint)
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/agent_runs
      tests/routes/agent_runs -q` exits 0
- [ ] `GET /api/v1/agent-runs/pending-approvals` returns tool names for a
      suspended run and exactly one row for a delegated parent+child pair
- [ ] `cd apps/web && pnpm check` exits 0
- [ ] `routes/home.tsx` contains no stat tiles, no hardcoded values, and no
      workspace/account cards; every section on the page links to an action
- [ ] Approvals render with tool names and deep-link to the conversation;
      no approve/deny controls exist on home
- [ ] `/conversations/new?agent=<id>` preselects the agent; invalid values
      degrade silently
- [ ] No SSE protocol changes (`stream/protocol.ts` untouched); no new
      conversation list filters
- [ ] `git status` clean outside the in-scope list;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `load_suspended_run_state` / `load_delegated_child_run_for_approval`
  have changed shape since `c2f08cc` such that projecting tool names
  requires new deserialization logic — do not fork the seam.
- A pending-approvals (or notifications-backed) aggregate endpoint already
  exists.
- The conversation list response no longer carries `unread` /
  `needs_approval` / `source`, or schedules no longer expose `health` +
  `latest_run` — the frontend partition depends on them.
- `pnpm arch` rejects the home feature's cross-feature imports — restructure
  per the rules, and if that forces moving shared pieces into `lib/`,
  report before doing a layering refactor.
- The new-conversation route has been redesigned (no picker to preselect).
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
