# Plan 009: Implement Agent Delegation Runtime

> **Executor instructions**: Follow this plan step by step. This slice turns the
> existing `agents.allowed_agent_ids` field into real runtime delegation. Preserve
> the architecture decision that one conversation has one primary, user-visible
> agent: delegation is an internal tool call that returns a result to the primary
> agent. Do not add a per-message agent selector. Do not install or wire
> `pydantic-ai-harness` Code Mode in this first slice.
>
> **Drift check (run first)**:
> `git diff --stat 4c7122f..HEAD -- apps/api/models apps/api/alembic/versions apps/api/services/agent_runs apps/api/services/agents apps/api/tests/services/agents apps/api/tests/services/agent_runs apps/web/src/features/agents apps/web/src/features/conversations docs/architecture docs/plans`
>
> Also check the local working tree with `git status --short`. As of the
> 2026-07-02 refresh (HEAD `da621d3`), Plans 006-008 have landed on `main`:
> agent management with `allowed_agent_ids` editing, the approval-state and
> resume routes under `apps/api/routes/agent_runs/`, and the conversation chat
> surface all exist. The working tree still carries uncommitted approval-flow
> work in `apps/api/services/agents/runtime/` (`approval_events.py`,
> `execute_run.py`, `persistence.py`, `run_persistence.py`),
> `apps/api/tests/services/agents/runtime/test_runtime_core.py`, and the
> conversation approval components under
> `apps/web/src/features/conversations/`. Those files overlap this plan's
> scope; commit (or deliberately stash) them before starting so delegation
> changes do not mix with unrelated approval work.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: Plan 006 frontend stream transport, Plan 007 conversation chat surface, Plan 008 agent management for the full UI slice
- **Category**: feature
- **Planned at**: commit `4c7122f`, 2026-07-01
- **Refreshed**: 2026-07-02 against HEAD `da621d3`; Plans 006-008 have landed
- **Status**: TODO

## Why This Matters

Agents can now run, stream, persist messages, and pause for approval, but
`allowed_agent_ids` is still just configuration. Delegation is the missing piece
that lets a primary agent route specialist work to another configured agent while
remaining accountable for the final user-facing answer.

This plan implements delegation as Pydantic AI tools on the primary agent. That
keeps the main chat simple, preserves visibility and auditability, and avoids
copying the old donor app's AI SDK runtime.

## Current State

The Python runtime already has the right core seams:

```python
# apps/api/services/agents/runtime/loop.py:39
agent=PydanticAgent(
    runtime_model,
    name=_agent_name(agent),
    instructions=agent.instructions,
    deps_type=RuntimeDeps,
    output_type=[str, DeferredToolRequests],
    tools=build_runtime_tools(agent),
    capabilities=build_runtime_capabilities(agent),
)
```

Runtime tools receive the state needed to enforce delegation scope:

```python
# apps/api/services/agents/runtime/context.py:17
class RuntimeDeps:
    db: AsyncSession
    user: User
    workspace: Workspace
    conversation: Conversation
    agent: Agent
    run: AgentRun
    sink: EventSink
```

Agents already have an allowlist, and create/update validation already checks
same-workspace active agents and blocks self-delegation:

```python
# apps/api/models/agent.py:62
allowed_agent_ids = Column(
    JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
)

# apps/api/services/agents/utils.py:74
if current_agent_id is not None and str(current_agent_id) in normalized_agent_ids:
    raise AppValidationError("Agent cannot delegate to itself", field="allowed_agent_ids")
```

The run identity table currently accepts only interactive and scheduled triggers:

```python
# apps/api/models/agent_run.py:79
CheckConstraint(
    "trigger IN ('interactive', 'scheduled')",
    name="agent_runs_trigger_check",
)
```

Conversations already permit delegated child conversations, so no conversation
migration is needed:

```python
# apps/api/models/conversation.py:76
CheckConstraint(
    "source IN ('direct', 'scheduled', 'agent_call')",
    name="conversations_source_check",
)
```

The architecture doc already chooses delegation tools, not a chat-level agent
selector:

```text
Specialist agents are reached through Pydantic AI multi-agent delegation, not by
turning the chat into a multi-speaker selector. The primary agent receives
delegation tools for its allowed_agent_ids.
```

## Donor App Lessons

Use the donor app only as behavioral reference. Do not port its AI SDK runtime.

Preserve these ideas:

- Discovery first, then call: the old prompt used `internal-list_sub_agents`
  before `internal-call_sub_agent`, and told the model to use the exact returned
  id.
- Visibility is an allowlist: direct sub-agent chat received
  `allowedSubAgentIds: subAgentData.allowed_sub_agent_ids ?? []`.
- Empty allowlist means no delegation tools.
- Delegated children could not delegate further: `isDelegated` stripped the
  delegation tools even if stale tool names existed in the DB.
- The child had its own `agent_call` conversation/session linked to the parent,
  so its transcript was inspectable without cluttering the main chat.
- The runner re-checked allowlist membership at execution time, including resume
  paths, so stale sessions could not bypass revoked visibility.

Reject these ideas for this port:

- A special master agent with `allowedSubAgentIds: null` that can call any agent.
  In this Python runtime, every runtime agent should use explicit
  `allowed_agent_ids`.
- Forwarding raw child text deltas into the parent assistant message. The parent
  remains responsible for the final user-facing response.
- Rebuilding AI SDK step aggregation. Reuse `execute_run`, Pydantic AI message
  history, `AgentRun`, `Conversation`, and the existing stream events.

## Pydantic AI And Harness Decisions

Core delegation should use Pydantic AI's native agent-as-tool pattern:

- expose delegation as `@agent.tool` or `Tool(...)` entries that take
  `RunContext[RuntimeDeps]`;
- use structured Pydantic inputs and outputs for delegation tools;
- pass shared usage into child runs so delegated work is budgeted with the
  parent turn; the installed pydantic-ai 2.1.0 exposes `usage=` on
  `run_stream_events` (verified 2026-07-02), and tools receive `ctx.usage`
  through `RunContext`;
- keep hooks/capabilities for audit and stream fan-out, not for business logic.

`pydantic-ai-harness` is not the first implementation primitive. Code Mode is
useful later when an agent needs to collapse many safe, local, non-deferred tool
calls into one sandboxed Python execution. Do not put `delegate_to_agent`,
approval-required tools, deferred tools, or high-risk side-effect tools behind
Code Mode in this slice. If a later spike wraps MCP tools with Code Mode, create
those tools with `native=False` so the local sandbox actually mediates calls.

## Commands You Will Need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| API lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Alembic check | `cd apps/api && uv run alembic check` | no pending model drift |
| Migration smoke | `cd apps/api && uv run alembic upgrade heads` | all heads apply |
| Runtime tests | `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agents/runtime/test_runtime_core.py tests/services/agents/runtime/test_delegation.py` | all selected tests pass |
| Agent-run tests | `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_runs` | all selected tests pass |
| Web typecheck | `cd apps/web && pnpm typecheck` | exit 0 |
| Web lint | `cd apps/web && pnpm lint` | exit 0 |
| Web build | `cd apps/web && pnpm build` | exit 0 |

If Postgres is not running for API tests, start it with `make db-up`.

## Scope

**In scope**:

- `apps/api/models/agent_run.py`
- A new Alembic core migration for delegated run identity
- `apps/api/services/agent_runs/domain.py`
- `apps/api/services/agent_runs/create.py`
- `apps/api/services/agents/runtime/context.py`
- `apps/api/services/agents/runtime/loop.py`
- `apps/api/services/agents/runtime/tools/`
- `apps/api/services/agents/runtime/execute_run.py`
- `apps/api/services/agents/runtime/run_persistence.py`
- `apps/api/services/conversations/list_conversations.py` (exclude `agent_call`
  conversations from the default list)
- Focused tests under `apps/api/tests/services/agents/runtime/`
- Small frontend rendering for delegation tool calls/results under
  `apps/web/src/features/conversations/` or the existing conversation component
  location after Plans 006-008
- Documentation updates in `docs/architecture/agent-runtime.md`

**Out of scope**:

- A global multi-agent graph editor.
- A per-message agent picker in the composer.
- Letting all agents see all other agents by default.
- Nested delegation beyond depth 1.
- Full delegated-run approval inboxes.
- Installing or using `pydantic-ai-harness[codemode]`.
- Replacing the custom SSE protocol.

## Git Workflow

- Suggested branch: `advisor/009-agent-delegation`.
- Commit style should match recent history, for example:
  `API/Web - Add Agent Delegation Runtime`.
- Do not push or open a PR unless the operator asks.

## Steps

### Step 1: Add Delegated Run Identity

Add first-class child runs instead of hiding delegation in parent metadata only.
This is the audit backbone.

Migration:

- add nullable `agent_runs.parent_run_id` referencing `agent_runs.id` with
  `ondelete="SET NULL"`;
- add non-null integer `agent_runs.delegation_depth` default `0`;
- update `agent_runs_trigger_check` to include `delegated`;
- add an index like `ix_agent_runs_parent_created` on
  `(parent_run_id, created_at)` where `parent_run_id IS NOT NULL`;
- add a check that `delegation_depth >= 0`.

Model/domain changes:

- add `RUN_TRIGGER_DELEGATED = "delegated"` in
  `apps/api/services/agent_runs/domain.py`;
- include it in `ALL_RUN_TRIGGERS`;
- add `parent_run_id` and `delegation_depth` columns/relationships to
  `AgentRun`;
- extend `create_agent_run(...)` with optional `parent_run_id` and
  `delegation_depth`.

Do not add scheduler state to delegated runs. The generic `agent_runs` table is
the run tree; `agent_schedule_runs` remains only the scheduled claim table.

Tests:

- `create_agent_run` accepts trigger `delegated`;
- unknown trigger still fails;
- migration-generated constraints permit delegated rows and reject invalid depth.

### Step 2: Add Delegation Visibility Services

Create a small service module, for example:

```text
apps/api/services/agents/runtime/delegation.py
```

Add structured contracts:

```python
class DelegateAgentSummary(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    model: str | None = None
    tool_count: int
    skill_count: int

class DelegateRunResult(BaseModel):
    status: Literal["completed", "awaiting_approval", "failed"]
    agent_id: UUID
    agent_name: str
    run_id: UUID | None = None
    conversation_id: UUID | None = None
    output: str | None = None
    error: str | None = None
    pending_approvals: list[dict[str, Any]] = []
    truncated: bool = False
```

Add a resolver like:

```python
async def list_visible_delegate_agents(db, *, caller: Agent, workspace: Workspace) -> list[Agent]:
    ...
```

Rules:

- if `caller.allowed_agent_ids` is empty, return `[]`;
- normalize IDs as UUID strings, matching the existing agent config validation;
- only return non-deleted, active agents in the same workspace;
- always exclude `caller.id` even though create/update validation also blocks it;
- preserve allowlist order in the returned summaries;
- never treat a missing or deleted allowed id as visible;
- never expose agents from another workspace.

Add an execution-time resolver:

```python
async def get_visible_delegate_agent(db, *, caller, workspace, target_agent_id) -> Agent:
    ...
```

It must re-check the allowlist at call time. This mirrors the donor app's
defense-in-depth resume checks and makes revocation effective immediately.

Tests:

- active same-workspace allowlisted agents are returned;
- inactive, deleted, cross-workspace, and self agents are omitted;
- arbitrary non-allowlisted target id is rejected;
- allowlist order is stable.

### Step 3: Build Delegation Tools

Add two runtime tools when delegation is enabled and the caller has visible
delegates:

```text
list_delegate_agents
delegate_to_agent
```

Tool behavior:

- `list_delegate_agents()` returns `list[DelegateAgentSummary]`;
- `delegate_to_agent(agent_id: UUID, task: str)` creates a child
  `agent_call` conversation and a delegated `AgentRun`, then runs the target agent
  server-side and returns `DelegateRunResult`;
- tool descriptions should tell the model to call `list_delegate_agents` first
  and use the exact returned id;
- cap `task` length and final result preview length so one child cannot flood the
  parent context; keep the full child transcript in the child conversation;
- return structured failures instead of leaking stack traces into tool output.

Recommended prompt section appended only when tools are available:

```text
<agent_delegation>
You can delegate specialized tasks to allowed agents in this workspace.
Call list_delegate_agents to inspect available agents and descriptions.
Call delegate_to_agent only when a listed agent clearly matches the task.
Give the delegate complete, clear instructions and relevant context.
Handle general queries yourself.
If a delegate returns awaiting_approval or asks a question you cannot answer from
context, ask the user rather than pretending the task is complete.
</agent_delegation>
```

Runtime wiring:

- change `build_runtime_agent(...)` to accept a delegation mode flag, for example
  `enable_delegation: bool = True`;
- change `build_runtime_tools(agent, *, include_delegation: bool)` so it appends
  delegation tools after configured catalog tools;
- in `execute_run`, disable delegation for child delegated runs in the first
  implementation: `include_delegation = run.trigger != RUN_TRIGGER_DELEGATED`;
- also add `delegation_depth` to `RuntimeDeps` so future code does not infer
  depth from metadata.

This intentionally preserves the donor app rule: an agent chatted with directly
can delegate if configured; an agent currently running as a delegate cannot
delegate further.

Tests:

- an agent with empty `allowed_agent_ids` does not receive delegation tools;
- an agent with visible delegates receives both tools and the delegation prompt;
- a delegated child run strips delegation tools even if the child has its own
  `allowed_agent_ids`;
- unknown configured runtime tools still fail as before.

### Step 4: Run Child Agents Through The Existing Runtime

Prefer reusing `execute_run` for child runs. It already owns lifecycle,
message persistence, approval suspension, usage persistence, and failure state.

`delegate_to_agent` should:

1. validate the requested target agent against `allowed_agent_ids`;
2. create a child `Conversation` with:
   - `source="agent_call"`;
   - `active_agent_id` set to the delegate;
   - `agent_slug` set to the delegate slug;
   - metadata containing `parent_conversation_id`, `parent_run_id`,
     `caller_agent_id`, and `target_agent_id`;
3. create an `AgentRun` with:
   - `trigger="delegated"`;
   - `parent_run_id=ctx.deps.run.id`;
   - `delegation_depth=ctx.deps.delegation_depth + 1`;
4. call `execute_run(...)` with `sink=None` (it defaults to a `NullSink`);
5. pass shared Pydantic AI usage into the child call via `usage=ctx.usage`;
6. return `DelegateRunResult`.

Session and lease handling (important, verified against current runtime):

- Do not run the child `execute_run` on `ctx.deps.db`. The parent `execute_run`
  owns that session's transaction boundaries, and the child commits running
  state, messages, and failures itself; sharing the session would commit or
  roll back in-flight parent state mid-stream. Follow the
  `services/agents/runtime/worker.py` pattern: open an independent session via
  `get_async_db_session_factory()` plus `configure_async_db_session`, create
  and commit the child conversation and run there, then run `execute_run` on
  that session.
- `execute_run` leases the child run through `start_agent_run_with_lease`, but
  nothing renews that lease while the child streams inline in the parent's
  task. Start a `heartbeat_agent_run_lease` task for the child (as `worker.py`
  does), or a long child run will be failed by `reap_abandoned` while still
  executing. Pass an `owner_instance_id` so lease ownership is attributable.
- The parent run's own lease is safe: its worker heartbeat keeps renewing while
  the delegation tool awaits the child.

Add an optional `usage` parameter to `execute_run` to pass `ctx.usage` through
to `runtime_agent.agent.run_stream_events(...)`. The installed pydantic-ai
2.1.0 accepts `usage=` there (verified), so this is small plumbing. If a future
upgrade removes it, stop and refresh this plan rather than silently allowing
delegated work to escape the parent run budget.

Approval behavior:

- if the child completes, return its final output preview plus child
  `run_id`/`conversation_id`;
- if the child returns `DeferredToolRequests`, the child run should remain
  `awaiting_approval`; return `status="awaiting_approval"` with child
  `run_id`, `conversation_id`, and safe pending approval descriptors;
- the parent agent prompt should make the model ask the user to review/approve
  rather than fabricating completion;
- child approval decisions still use the normal `agent_runs/{run_id}/resume`
  path from Plan 008.

Failure behavior:

- child run failures are persisted on the child `AgentRun`;
- parent tool output receives a structured `failed` result with a concise error;
- the parent run may still complete by explaining the delegation failure.

Tests:

- parent delegation creates one child conversation with `source="agent_call"`;
- child messages are persisted on the child conversation, not the parent
  conversation;
- child `AgentRun.parent_run_id` points to the parent run;
- child completion returns output to the parent tool call;
- child approval suspension returns `awaiting_approval` with safe descriptors;
- child failure does not erase the parent run state;
- parent/child usage accounting is bounded and tested.

### Step 5: Preserve Stream Visibility Without Cluttering The Main Chat

Do not add child text deltas to the parent assistant message. The parent remains
the only user-visible speaker in the main conversation.

Use existing stream events first:

- parent emits `tool.call` for `delegate_to_agent`;
- parent emits `tool.result` with `DelegateRunResult`;
- frontend renders those as a delegation card, not as a generic JSON blob.

Delegation card requirements:

- show the delegate agent name;
- show a compact task preview;
- show status: running, completed, awaiting approval, or failed;
- show an output preview when completed;
- include the child run id/conversation id in inspectable metadata;
- if status is `awaiting_approval`, link to or load the child run's approval
  state through the Plan 008 approval-state endpoint;
- offer a way to inspect the child transcript without making `agent_call`
  conversations look like normal user-created chats by default.

Frontend wiring note: `apps/web/src/features/agents/runtime-tools.ts`
(`RUNTIME_TOOL_OPTIONS`) is the user-configurable catalog mirror used by the
agent form and `runtimeToolLabel`. Delegation tools are appended by the
runtime, not configured per-agent, so do not add them to
`RUNTIME_TOOL_OPTIONS`. Branch on the tool names (`delegate_to_agent`,
`list_delegate_agents`) in the tool rendering path (`message-parts.ts` /
`tool-call-row.tsx`) to select the delegation card.

Do not introduce new SSE event names unless the existing `tool.call` and
`tool.result` events are insufficient in implementation. Both events already
exist end to end: `services/agents/runtime/events.py` emits them and
`apps/web/src/features/conversations/stream/protocol.ts` types them. If new delegation events
become necessary, bump or document the stream protocol in
`docs/architecture/agent-runtime.md` and update the frontend stream client tests.

Tests:

- delegation tool calls render with the special UI card;
- result payloads with `awaiting_approval` render a visible pending state;
- result payloads with child IDs are not treated as assistant text;
- refresh after completion can still inspect the persisted parent tool result.

### Step 6: Update Agent Management Visibility UI

Plan 008 should add create/edit support for `allowed_agent_ids`. Extend it only as
needed for visibility clarity:

- label the field as "Can delegate to";
- list only active agents in the same workspace;
- exclude the current agent;
- show the reverse relationship read-only if cheap to compute: "Visible to" or
  "Callable by" helps users understand why an agent appears in another agent's
  delegation list;
- keep `agent_call` conversations out of the default conversation list. This is
  a backend change, not just UI: `list_conversations`
  (`apps/api/services/conversations/list_conversations.py`) currently has no
  `source` filter, and child conversations share the parent's
  `user_id`/`workspace_id`, so they would appear as normal chats. Exclude
  `source='agent_call'` from the default listing and reach child conversations
  deliberately (direct fetch by id from the delegation card, or an explicit
  include parameter).

Backend validation remains authoritative; UI filters are only ergonomics.

Tests:

- `agent_call` conversations are excluded from the default conversation list;
- direct fetch of an `agent_call` conversation by id still works for its owner.

### Step 7: Harness Checkpoint

After native delegation is working and tested, evaluate whether Code Mode is
actually useful for this product path. Do not implement it in this plan.

Possible future use cases:

- a research-style agent needs to call many read-only local tools and aggregate
  results;
- a delegate needs safe parallel calls to read-only internal tools;
- repeated tool-call overhead becomes a measurable latency/cost issue.

Required gates before using `pydantic-ai-harness`:

- install `pydantic-ai-harness[codemode]` only after a concrete benchmarked use
  case exists;
- keep approval-required and deferred tools outside Code Mode;
- keep `delegate_to_agent` outside Code Mode unless there is a strict
  `max_delegate_calls` budget and the delegate set is side-effect-safe;
- if wrapping MCP tools, set `native=False`;
- add tests proving sandbox errors and permission failures are visible in normal
  tool results.

## Test Plan

Backend:

```bash
cd apps/api
uv run ruff check .
uv run alembic check
uv run alembic upgrade heads
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \
  uv run pytest \
  tests/services/agents/runtime/test_runtime_core.py \
  tests/services/agents/runtime/test_delegation.py \
  tests/services/agent_runs
```

Frontend:

```bash
cd apps/web
pnpm typecheck
pnpm lint
pnpm build
```

Manual smoke:

- create Agent A and Agent B;
- configure Agent A with `allowed_agent_ids=[Agent B]`;
- start a conversation with Agent A;
- ask for a task clearly matching Agent B;
- confirm the UI shows a delegation card;
- confirm the main conversation gets only Agent A's final response;
- inspect the child `agent_call` conversation/run and confirm Agent B's transcript
  and usage are persisted;
- remove Agent B from Agent A's allowlist and confirm a stale/direct call to B is
  rejected.

## Done Criteria

- [ ] `agent_runs` supports `trigger="delegated"`, `parent_run_id`, and
      `delegation_depth`.
- [ ] Runtime delegation tools are exposed only when the current agent has visible
      allowed delegates.
- [ ] `delegate_to_agent` validates visibility at execution time.
- [ ] Delegated child runs create linked `agent_call` conversations and child
      `AgentRun` rows.
- [ ] Delegated child transcripts do not clutter the parent conversation.
- [ ] `agent_call` conversations are excluded from the default conversation
      list but remain reachable from delegation cards.
- [ ] Child approval suspension returns a visible, actionable
      `awaiting_approval` result.
- [ ] Delegated runs are disabled from delegating further in this first slice.
- [ ] Frontend renders delegation tool calls/results as delegation cards.
- [ ] Tests cover visibility, child run persistence, child approval, failure, and
      no parent-message clutter.
- [ ] `docs/architecture/agent-runtime.md` is updated so delegation is no longer
      listed as pending once implemented.

## STOP Conditions

- Pydantic AI's installed run API cannot share parent usage with delegated runs
  and there is no acceptable bounded alternative. (Verified available in
  pydantic-ai 2.1.0; this triggers only if an upgrade regresses it.)
- Implementing child runs requires replacing `execute_run` rather than extending
  it.
- Approval-required child tool calls cannot be surfaced to the user without
  hiding pending work.
- Plan 008's approval-state endpoint and conversation UI landed before the
  2026-07-02 refresh. If they have materially changed by execution time and the
  frontend slice cannot safely show delegated approval state, stop after
  backend delegation tests or split the UI work into a follow-up plan.
- The implementation needs a new global permissions model for agent visibility.
  Keep this slice scoped to `allowed_agent_ids`.

## Maintenance Notes

- `allowed_agent_ids` is runtime visibility, not just UI preference. Always
  enforce it in backend tool execution.
- Keep delegated child conversations durable but visually secondary. They are
  audit artifacts, not normal top-level chat threads.
- If nested delegation becomes necessary later, raise the depth limit deliberately
  and add cycle detection plus UI for run trees.
- If the runtime tool catalog grows large, use Pydantic AI deferred tool loading
  or tool search before reaching for Code Mode.
- Code Mode remains an optimization for safe local tool orchestration, not the
  security boundary for external side effects.
