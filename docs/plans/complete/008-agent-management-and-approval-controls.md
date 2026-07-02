# Plan 008: Add Agent Management And Approval Controls

> **Executor instructions**: Follow this plan step by step. This slice adds
> practical agent configuration screens and human approval controls on top of the
> conversation surface from Plan 007. It also adds the small backend read surface
> needed to recover pending approval details after refresh. Do not implement full
> schedule CRUD screens in this plan. When done, update the status row for this
> plan in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat fdf7220..HEAD -- apps/api/routes/agent_runs apps/api/services/agent_runs apps/api/services/agents/runtime/approval_state.py apps/api/services/agents/runtime/approval_events.py apps/api/tests/routes/conversations apps/api/tests/services/agents/runtime apps/web/src/app/router.tsx apps/web/src/config/navigation.ts apps/web/src/features/agents apps/web/src/features/conversations apps/web/src/features/models apps/web/src/components apps/web/src/routes/home.tsx docs/plans`
>
> If any in-scope file changed since this plan was written, compare the "Current
> State" excerpts below against the live code before proceeding. If approval
> state moves out of `agent_runs.metadata["approval_state"]`, treat that as a
> STOP condition until this plan is refreshed.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: Plan 006 frontend stream transport, Plan 007 conversation chat surface
- **Category**: feature
- **Planned at**: commit `fdf7220`, 2026-07-01
- **Status**: DONE

## Why This Matters

After Plans 006 and 007, users can talk to existing agents, but they still need a
way to configure those agents and approve tools that suspend a run. The backend
already has agent CRUD, model catalog, and approval resume endpoints; the missing
pieces are the web screens and a safe read endpoint for pending approval details
after refresh.

This plan makes the runtime usable by workspace editors: they can create and edit
agent instructions/model/tool policy, start conversations from those agents, see
pending tool approvals, approve or deny them, and stream the resumed run. It keeps
schedule CRUD out of scope because schedule REST routes do not exist yet at the
planned commit.

## Current State

Agent API routes exist:

```python
# apps/api/routes/agents/list_agents.py:16
@router.get("/")
async def list_agents(...):
    ...

# apps/api/routes/agents/create_agent.py:14
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_agent(...):
    ...

# apps/api/routes/agents/update_agent.py:17
@router.patch("/{agent_id}")
async def update_agent(...):
    ...
```

Model catalog API exists:

```python
# apps/api/routes/models/list_catalog.py:14
@router.get("/catalog")
async def list_model_catalog(_actor: CurrentUserDep) -> ModelCatalogResponse:
    return list_model_catalog_service()
```

Approval resume API exists, but there is no read endpoint for pending approval
details:

```python
# apps/api/services/agent_runs/resume_run_stream.py:60
suspended_state = load_suspended_run_state(run)
deferred_tool_results = _build_deferred_tool_results(
    pending_tool_call_ids=suspended_state.pending_tool_call_ids,
    decisions=payload.decisions,
)
```

Approval state currently stores the data needed for a safe read response:

```python
# apps/api/services/agents/runtime/approval_state.py:43
metadata[APPROVAL_STATE_METADATA_KEY] = {
    "version": APPROVAL_STATE_VERSION,
    "run_id": str(run.id),
    "conversation_id": str(conversation.id),
    "agent_id": str(run.agent_id),
    "message_history": _dump_messages(message_history),
    "deferred_tool_requests": to_jsonable_python(deferred_tool_requests),
    "pending_tool_call_ids": pending_tool_call_ids(deferred_tool_requests),
}
```

Live stream approval events contain pending tool names and args:

```python
# apps/api/services/agents/runtime/approval_events.py:40
for approval in deferred_tool_requests.approvals:
    await sink.emit(
        EVENT_TOOL_APPROVAL_REQUIRED,
        {
            "tool_call_id": approval.tool_call_id,
            "name": approval.tool_name,
            "args": to_jsonable_python(approval.args),
        },
    )
```

Frontend state after Plans 006 and 007:

- Plan 006 should provide typed agent/model/conversation clients and
  `useAgentStream`.
- Plan 007 should provide `/conversations` routes, composer streaming, message
  rendering, and the active-run heal loop.
- `apps/web/src/config/navigation.ts` still has the Agents item disabled at the
  planned commit.

## Commands You Will Need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| API lint | `cd apps/api && uv run ruff check .` | exit 0 |
| API approval tests | `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/routes/conversations/test_turn_streaming.py tests/services/agents/runtime/test_runtime_core.py` | all selected tests pass |
| Web typecheck | `cd apps/web && pnpm typecheck` | exit 0, no TS errors |
| Web lint | `cd apps/web && pnpm lint` | exit 0, no warnings |
| Web build | `cd apps/web && pnpm build` | exit 0 |

If Postgres is not running for API route tests, start it with `make db-up`.

## Scope

**In scope**:

Backend approval read surface:

- `apps/api/routes/agent_runs/__init__.py`
- `apps/api/routes/agent_runs/get_approval_state.py` (create)
- `apps/api/services/agent_runs/__init__.py`
- `apps/api/services/agent_runs/get_approval_state.py` (create)
- `apps/api/services/agent_runs/schemas.py`
- Focused API tests under `apps/api/tests/routes/conversations/` or
  `apps/api/tests/services/agent_runs/`

Frontend:

- `apps/web/src/app/router.tsx`
- `apps/web/src/config/navigation.ts`
- `apps/web/src/features/agents/`
- `apps/web/src/features/models/`
- `apps/web/src/features/conversations/`
- Small updates to `apps/web/src/routes/home.tsx`

**Out of scope**:

- Schedule CRUD/list/detail backend routes.
- Full schedule management UI.
- Changing the approval-state persistence format beyond adding a read projection.
- Storing approval decisions separately from Pydantic AI `DeferredToolResults`.
- Multi-agent delegation configuration beyond editing `allowed_agent_ids`.
- Building custom skills UI.
- Installing or using `pydantic-ai-harness` Code Mode.

## Git Workflow

- Suggested branch: `advisor/008-agent-management-approvals`.
- Commit style should match recent history, for example:
  `API/Web - Add Agent Approval Controls`.
- Do not push or open a PR unless the operator asks.

## Steps

### Step 1: Add A Backend Pending Approval Read Endpoint

Add a route:

```text
GET /api/v1/agent-runs/{run_id}/approval-state
```

Use one route file:

```text
apps/api/routes/agent_runs/get_approval_state.py
```

Add a service operation:

```text
apps/api/services/agent_runs/get_approval_state.py
```

Follow existing backend conventions: the route is thin, the service owns domain
logic, and `routes/agent_runs/__init__.py` only composes routers.

The service should:

- require the authenticated actor and current workspace;
- load a non-deleted `AgentRun` by `run_id`, `workspace_id`, and `user_id`;
- require `run.status == awaiting_approval`;
- call `load_suspended_run_state(run)`;
- return only safe pending approval details, not full message history.

Add schemas in `apps/api/services/agent_runs/schemas.py`:

```python
class PendingToolApprovalRead(BaseModel):
    tool_call_id: str
    name: str
    args: Any

class AgentRunApprovalStateResponse(BaseModel):
    run_id: UUID
    conversation_id: UUID
    approvals: list[PendingToolApprovalRead]
```

Build `approvals` from `suspended_state.deferred_tool_requests.approvals`. Do not
include the serialized `message_history` in the response.

Tests:

- awaiting-approval run returns pending tool id/name/args;
- completed run returns conflict;
- run in another workspace/user scope is not found;
- corrupt/missing approval state returns structured conflict through existing
  exception handling.

**Verify**:
`cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/routes/conversations/test_turn_streaming.py tests/services/agents/runtime/test_runtime_core.py`
-> all selected tests pass.

### Step 2: Add Agent Management Routes

Create frontend routes:

```text
apps/web/src/features/agents/routes/agents-route.tsx
apps/web/src/features/agents/routes/agent-detail-route.tsx
```

Register authenticated routes in `apps/web/src/app/router.tsx`:

- `/agents`
- `/agents/$agentId`

Update `apps/web/src/config/navigation.ts` so the Agents item links to
`/agents` and is no longer disabled.

The list route should:

- use the Plan 006 agent-list query;
- show active/inactive status, model, tool count, favorite state, and last-used
  time where available;
- include a create-agent action for users with write access. If the frontend does
  not yet expose membership role in a convenient place, let the backend enforce
  writes and show API errors through existing error helpers.

The detail route should:

- load the selected agent. Plan 006 shipped list/create/update/delete agent
  clients but no single-agent read client, while the backend already exposes
  `GET /agents/{id}` (`apps/api/routes/agents/get_agent.py`). Add
  `apps/web/src/features/agents/api/get-agent.ts` calling that endpoint, or
  derive the agent from the existing list query cache if that is simpler; do not
  assume a `getAgent` client already exists;
- provide edit controls for name, slug, description, instructions,
  model_provider/model, max_steps, tool_names, tool_policies, allowed_agent_ids,
  and is_active;
- use the model catalog query for provider/model selection;
- use the agent list query for allowed-agent selection;
- keep custom skill editing minimal: show existing `skill_ids` as read-only or a
  simple UUID list unless a skills management UI already exists.

Keep UI dense and operational. This is an agent operations screen, not a landing
page.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 3: Add Agent Create/Edit Forms

Create components under `apps/web/src/features/agents/components/`, for example:

```text
agent-form.tsx
agent-tools-field.tsx
model-select-field.tsx
allowed-agents-field.tsx
```

Form behavior:

- required `name` and `instructions`;
- optional slug and description;
- model selector shows only configured providers/models returned from
  `/models/catalog`;
- max steps numeric input bounded to backend schema (`1..100`);
- tool selector supports the current runtime catalog names exposed through agent
  records or a local small list if no catalog endpoint exists yet. At the planned
  commit the backend catalog contains `get_runtime_context` and `add_numbers`;
  do not invent unavailable tools;
- policy selector per selected tool: `auto` or `approval`;
- allowed-agent selector excludes the current agent where possible.

If the lack of a runtime-tool catalog endpoint makes a reliable tool picker
impossible, use a tiny local constant matching the current backend catalog and
add a maintenance note in the component. Do not add a backend tool-catalog route
in this plan unless the reviewer explicitly authorizes expanding scope.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 4: Add Approval Controls To Conversation Detail

Use the Plan 007 conversation detail route and Plan 006 `resumeRun` transport.

Approval UX requirements:

- live `tool.approval_required` stream events render a pending approval card;
- on refresh, if `active_run.status === "awaiting_approval"`, fetch
  `/agent-runs/{run_id}/approval-state` and render the same approval cards;
- each approval card shows tool name and args in a compact, inspectable format;
- default action is deny unless the user explicitly approves;
- approve supports optional JSON `override_args`;
- deny supports optional message;
- submitting decisions must cover exactly all pending tool approvals in one
  `POST /agent-runs/{run_id}/resume` call, matching backend validation;
- after resume stream finishes, refetch messages, active run, and conversation
  list.

Keep approval controls inside the conversation/run context. Do not add a global
approvals inbox in this plan.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 5: Surface Scheduled Approval Context Without Schedule CRUD

Scheduled approval runs use the same generic `agent_runs` and conversations as
interactive approval runs. If a scheduled run is awaiting approval and the user
opens the scheduled conversation, the approval controls from Step 4 should work
through the same `/agent-runs/{run_id}/approval-state` and resume endpoints.

Add only minimal schedule context where it is already present in conversation
metadata:

- show `conversation.source === "scheduled"` in the conversation header;
- if `conversation.metadata.schedule` exists, show schedule id/run id as
  secondary metadata;
- do not create schedule list/create/edit routes here.

Add a small pending-state card on Home or Agents if useful, but it must not imply
schedule CRUD exists. Use text like "Schedule management is pending" only if the
existing UI already uses placeholder cards; do not add an in-app explanation page.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 6: Run The Full Focused Gate

Run:

```bash
cd apps/api
uv run ruff check .
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest \
  tests/routes/conversations/test_turn_streaming.py \
  tests/services/agents/runtime/test_runtime_core.py

cd ../web
pnpm typecheck
pnpm lint
pnpm build
```

Expected result: all commands exit 0.

## Test Plan

Backend tests:

- approval-state read endpoint succeeds for awaiting approval;
- rejects non-awaiting runs;
- respects workspace/user scope;
- does not leak message history.

Frontend verification:

- create an agent with default model;
- edit agent instructions/model/max steps;
- select `add_numbers` with `approval` policy;
- start a conversation with that agent;
- observe pending approval;
- approve with override args and see resumed assistant response;
- deny and see resumed assistant response handles denial;
- refresh on `awaiting_approval` and confirm pending approvals reload from the
  backend read endpoint;
- open a scheduled conversation with pending approval and confirm the same
  controls appear.

## Done Criteria

- [x] `GET /api/v1/agent-runs/{run_id}/approval-state` exists and returns only
      pending approval descriptors.
- [x] API tests cover approval-state success, conflict, and scope checks.
- [x] `/agents` and `/agents/$agentId` frontend routes exist.
- [x] Agents navigation is enabled.
- [x] Agent create/edit forms support model selection and current runtime tool
      policies.
- [x] Conversation detail can approve or deny all pending tool approvals and
      stream the resumed run.
- [x] Refresh on awaiting approval recovers pending approval details.
- [x] Scheduled conversations show enough context for approval, without schedule
      CRUD.
- [x] API Ruff and focused API tests pass.
- [x] Web typecheck, lint, and build pass.
- [x] `docs/plans/000_README.md` status row updated.

## STOP Conditions

Stop and report back if:

- Pending approval details cannot be derived from `load_suspended_run_state`
  without exposing full message history.
- The approval UI needs partial approval submission, which conflicts with the
  backend's exact-coverage resume validation.
- Backend schedule CRUD becomes necessary to complete this plan. That should be
  a separate schedule-management plan.
- The agent form cannot present tool selection safely because runtime tools are
  no longer a static backend catalog.
- Implementing role-aware write gating requires broad workspace membership API
  changes.
- Any check fails twice after reasonable fixes.

## Maintenance Notes

Schedule CRUD is deliberately deferred. The backend has schedule domain helpers
and a worker, but no public REST routes for users to create or manage schedules
at the planned commit. Add a dedicated plan for schedule CRUD and schedule UI
after this slice.

When the runtime tool catalog grows, replace any frontend local tool-name list
with a backend catalog endpoint. Do not let frontend-only constants become the
source of truth for available tools.
