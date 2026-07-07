# Plan 001: Implement The Scheduled Agent Runner

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP Conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md` unless a reviewer dispatched you and told you they maintain
> the index.
>
> **Drift check (run first)**:
> `git diff --stat 9f47ccd..HEAD -- apps/api/services/agent_schedules apps/api/services/agent_runs apps/api/services/agents/runtime apps/api/services/conversations apps/api/models apps/api/core/settings apps/api/tests docker-compose.yml makefile apps/api/.env.example`
>
> If any in-scope file changed since this plan was written, compare the
> "Current State" excerpts against the live code before proceeding. On a
> semantic mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `9f47ccd`, 2026-07-01

## Why This Matters

The runtime architecture requires scheduled execution to use the same
`execute_run` path as interactive turns, with `agent_schedule_runs` as the only
handoff table. The repository has the claim helper, generic `agent_runs`, runtime
core, and approval suspend/resume, but no worker process currently claims due
schedules and executes them.

This plan also picks up the hanging cleanup work for failed first conversations.
Both interactive create-conversation streams and scheduled runs can create a
conversation before the first runtime call succeeds. If that first run fails
before any durable messages are written, the product should prune the empty
conversation instead of leaving a dead shell in conversation lists.

## Current State

- `docs/architecture/agent-runtime.md` says the worker is part of the target
  process topology and step 7 is still pending: add `workers/agent_runner.py`,
  scan/claim schedule rows, create/link a generic run, call `execute_run` with
  `NullSink`, then mark schedule runs complete/retry/terminal.
- `apps/api/services/agent_schedules/runs.py` owns schedule run claim/final
  state helpers:

```python
# apps/api/services/agent_schedules/runs.py:256
async def claim_due_schedule_runs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    claim_ttl_seconds: int = DEFAULT_CLAIM_TTL_SECONDS,
) -> list[ClaimedScheduleRun]:
    """Claim due schedule fire times with row locks so overlapping workers split work."""
```

```python
# apps/api/services/agent_schedules/runs.py:201
def mark_run_completed(
    schedule: AgentSchedule,
    run: AgentScheduleRun,
    *,
    now: datetime,
) -> None:
    """Mark a run completed and advance or retire its schedule's next fire time."""
```

```python
# apps/api/services/agent_schedules/runs.py:331
def mark_run_retryable_failure(
    run: AgentScheduleRun,
    *,
    now: datetime,
    code: str,
    message: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> bool:
    """Record a retryable trigger failure, returning True when retry cap is exhausted."""
```

- `apps/api/services/agent_runs/create.py` creates the generic run identity but
  does not commit:

```python
# apps/api/services/agent_runs/create.py:15
async def create_agent_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    agent_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    trigger: str,
    model_name: str | None = None,
    metadata: dict | None = None,
) -> AgentRun:
    """Insert a pending run for one agent turn and return it (flushed, not committed)."""
```

- `apps/api/services/agent_runs/link_schedule_run.py` links a schedule claim row
  to the generic run and validates that the run trigger is `scheduled`:

```python
# apps/api/services/agent_runs/link_schedule_run.py:12
async def link_schedule_run(
    db: AsyncSession, schedule_run: AgentScheduleRun, run: AgentRun
) -> AgentScheduleRun:
    """Point a scheduler claim row at the generic run a worker created for it."""
```

- `apps/api/services/agents/runtime/execute_run.py` already supports background
  execution with `NullSink` when no live sink is supplied:

```python
# apps/api/services/agents/runtime/execute_run.py:59
async def execute_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    user_prompt: str | None,
    sink: EventSink | None = None,
    model: Model | None = None,
    client_message_id: str | None = None,
    owner_instance_id: str | None = None,
    expected_status: str | None = RUN_STATUS_PENDING,
    message_history: Sequence[ModelMessage] | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
) -> ExecuteRunResult:
```

```python
# apps/api/services/agents/runtime/execute_run.py:89
event_sink = sink or NullSink(run_id=run.id, conversation_id=conversation.id)
```

- `apps/api/services/conversations/create_conversation_stream.py` creates a
  conversation before starting the first interactive run:

```python
# apps/api/services/conversations/create_conversation_stream.py:69
conversation = Conversation(
    user_id=actor.id,
    workspace_id=workspace.id,
    created_by=actor.id,
    title=title.title,
    active_agent_id=agent_id,
    agent_slug=agent_slug,
    metadata_json=_title_metadata(title),
)
```

- `apps/api/models/conversation.py` already supports scheduled conversations:

```python
# apps/api/models/conversation.py:39
source = Column(String(32), nullable=False, default="direct", server_default=text("'direct'"))
schedule_id = Column(
    UUID(as_uuid=True),
    ForeignKey("agent_schedules.id", ondelete="SET NULL"),
    nullable=True,
)
schedule_run_id = Column(
    UUID(as_uuid=True),
    ForeignKey(
        "agent_schedule_runs.id",
        name="fk_conversations_schedule_run_id_agent_schedule_runs",
        ondelete="SET NULL",
        use_alter=True,
    ),
    nullable=True,
)
```

- Local topology currently has only `postgres`, `api`, and `web`:

```yaml
# docker-compose.yml:13
services:
  postgres:
  api:
  web:
```

- Local Make targets currently run only API and web dev servers:

```make
# makefiles/local.mk:32
dev: local-env ## Start Postgres, migrate, then run API and web dev servers
	@$(MAKE) db-up
	@$(MAKE) db-wait
	@$(MAKE) migrate
	@$(MAKE) -j2 api-dev web-dev
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint API | `cd apps/api && uv run ruff check .` | exit 0, `All checks passed!` |
| Non-DB tests | `cd apps/api && uv run pytest tests/services/conversations/test_create_conversation_stream.py tests/services/conversations/test_conversation_naming.py tests/services/agents/runtime/test_runtime_streaming.py` | exit 0 |
| DB tests | `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules tests/services/conversations tests/services/agent_runs tests/services/agents/runtime tests/routes/conversations/test_turn_streaming.py` | exit 0; DB-backed tests do not skip |
| Migration drift | `cd apps/api && uv run alembic check` | exit 0, no new operations |
| Worker once smoke | `cd apps/api && uv run python -m workers.agent_runner --once` | exit 0; no exception when no schedules are due |
| Compose config | `docker compose config --services` | output includes `postgres`, `api`, `worker`, `web` |

Database-backed tests require Postgres. If local Postgres is not running, start
it from the repo root with `make db-up` and `make db-wait` before the DB test
command.

The `worker ... --once` smoke run also requires a reachable Postgres: `run_once`
reconciles and claims against the database before doing anything else. "Exits 0
when no schedules are due" means with Postgres up and an empty due-queue and
**no model/provider credentials** — not with the database absent. Start Postgres
the same way before running the smoke command.

## Scope

**In scope**:

- `apps/api/workers/__init__.py` (create)
- `apps/api/workers/agent_runner.py` (create)
- `apps/api/services/agent_schedules/__init__.py`
- `apps/api/services/agent_schedules/runs.py`
- `apps/api/services/agent_schedules/prepare_schedule_run_execution.py` (create)
- `apps/api/services/agent_schedules/finalize_schedule_run_execution.py` (create)
- `apps/api/services/agent_schedules/reconcile_schedule_run_execution.py` (create)
- `apps/api/services/agent_schedules/utils.py` (create only if shared helpers are needed)
- `apps/api/services/conversations/__init__.py`
- `apps/api/services/conversations/prune_failed.py` (create)
- `apps/api/core/settings/agents.py`
- `apps/api/.env.example`
- `docker-compose.yml`
- `makefiles/local.mk`
- `makefiles/deployment.mk`
- Focused tests under `apps/api/tests/services/agent_schedules/`
- Focused tests under `apps/api/tests/services/conversations/`
- Existing runtime/conversation tests only where needed to cover pruning integration

**Out of scope**:

- Do not implement frontend schedule or chat UI.
- Do not implement delegation tools or history summarization.
- Do not change the public SSE event protocol.
- Do not add migrations unless the implementation truly requires new persisted
  columns. The existing schema already has `Conversation.schedule_id`,
  `Conversation.schedule_run_id`, and `AgentScheduleRun.agent_run_id`.
- Do not add automatic retry for provider/runtime failures after a generic
  `AgentRun` has reached a terminal status. That requires a separate design for
  multiple generic attempts per schedule fire time.

## Git Workflow

- Branch suggestion: `advisor/001-scheduled-agent-runner`
- Commit style in this repo is short imperative area prefixes, e.g.
  `API - Add Agent Management Routes`.
- Do not push or open a PR unless the operator explicitly instructs it.

## Steps

### Step 1: Add Worker Settings And Local Entrypoints

Add scheduler worker settings to `AgentRunSettingsMixin` in
`apps/api/core/settings/agents.py`:

- `AGENT_SCHEDULE_WORKER_POLL_SECONDS`: default `5.0`, `gt=0`.
- `AGENT_SCHEDULE_WORKER_BATCH_SIZE`: default `25`, `gt=0`.
- `AGENT_SCHEDULE_RUN_CLAIM_TTL_SECONDS`: default `300`, `gt=0`.
- `AGENT_SCHEDULE_RUN_MAX_ATTEMPTS`: default `3`, `gt=0`.
- `AGENT_SCHEDULE_WORKER_SHUTDOWN_SECONDS`: default `30.0`, `gt=0`.

Document the same variables in `apps/api/.env.example`.

Create `apps/api/workers/__init__.py` with a short package docstring. Create
`apps/api/workers/agent_runner.py` with:

- a `main()` async entrypoint,
- a `--once` CLI flag for test/smoke runs,
- a long-running polling loop for normal operation,
- graceful SIGINT/SIGTERM handling via an `asyncio.Event`,
- early `setup_logging()` like `main.py`,
- no FastAPI app import.

The worker entrypoint should only orchestrate sessions, polling, and shutdown.
Domain work belongs in `services/agent_schedules/*`.

Add `worker-dev` in `makefiles/local.mk`:

```make
.PHONY: worker-dev
worker-dev: local-env ## Run the scheduled agent runner
	cd $(API_DIR) && uv run python -m workers.agent_runner
```

Update `dev` to run `api-dev`, `worker-dev`, and `web-dev` together after
migrations.

Update `docker-compose.yml` with a `worker` service using the same API image,
volumes, env files, `DATABASE_URL`, network, and Postgres dependency as `api`.
Do not expose ports. Use command:

```yaml
command: ["python", "-m", "workers.agent_runner"]
```

Update `makefiles/deployment.mk` so `compose-up`, `compose-up-detached`, and
`compose-logs` include `worker`.

**Verify**:

- `cd apps/api && uv run python -m workers.agent_runner --once` -> exits 0.
- `docker compose config --services` -> includes `worker`.
- `cd apps/api && uv run ruff check .` -> `All checks passed!`.

### Step 2: Add The Failed Empty Conversation Pruner

Create `apps/api/services/conversations/prune_failed.py` with one public service
operation:

```python
async def prune_failed_empty_conversation_for_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    deleted_by_user_id: UUID,
) -> bool:
    ...
```

Behavior:

- Load the `AgentRun` by `run_id`, non-deleted.
- Load the `Conversation` by `conversation_id`, non-deleted.
- Return `False` unless:
  - the run belongs to the conversation,
  - the run status is `RUN_STATUS_FAILED`,
  - the conversation has zero non-deleted `ConversationMessage` rows,
  - the conversation has no other non-deleted `AgentRun` rows,
  - the conversation source is either `direct` or `scheduled`.
- If all checks pass, soft-delete the conversation with
  `conversation.soft_delete(deleted_by=deleted_by_user_id, cascade=False)`,
  flush, and return `True`.

Export it from `apps/api/services/conversations/__init__.py`.

Wire this into `apps/api/services/conversations/create_conversation_stream.py`:
after `_run_initial_conversation_worker` awaits `run_turn_worker`, open a fresh
database session through `get_async_db_session_factory()`, configure it with
`configure_async_db_session`, call the pruner for the newly-created conversation
and run, then commit. This must use a fresh session because the route session is
not valid after the streaming response is returned.

Do not prune conversations where the failed run persisted a user message,
assistant message, tool message, or where the conversation already had any prior
run.

Add `apps/api/tests/services/conversations/test_prune_failed.py` covering:

- failed first run + zero messages -> conversation soft-deleted;
- failed run + one message -> not deleted;
- completed run + zero messages -> not deleted;
- failed run but another run exists for the conversation -> not deleted.

Add one integration-style route test in
`apps/api/tests/routes/conversations/test_turn_streaming.py` patterned after
`test_create_turn_stream_disconnect_completes_and_persists_with_real_worker`.
Patch `build_model` to raise a provider/configuration failure during the first
create-conversation turn, then assert the newly-created empty conversation is
hidden from `GET /api/v1/conversations/`.

**Verify**:

- `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/conversations/test_prune_failed.py tests/routes/conversations/test_turn_streaming.py` -> all selected tests pass, DB-backed tests do not skip.
- `cd apps/api && uv run ruff check .` -> `All checks passed!`.

### Step 3: Prepare A Claimed Schedule Run For Execution

Create `apps/api/services/agent_schedules/prepare_schedule_run_execution.py`
with one public operation:

```python
async def prepare_schedule_run_execution(
    db: AsyncSession,
    *,
    schedule_run_id: UUID,
    now: datetime | None = None,
) -> PreparedScheduleRunExecution:
    ...
```

Use a dataclass return value containing:

- `schedule_id`
- `schedule_run_id`
- `conversation_id`
- `agent_run_id`
- `user_prompt`

Behavior:

1. Load `AgentScheduleRun` by id with `FOR UPDATE`, non-deleted.
2. Load its `AgentSchedule` and `Agent`, non-deleted. You may use explicit
   `select()` calls instead of relying on stale relationship state from the
   claim session.
3. Require `schedule_run.status == RUN_STATUS_CLAIMED`; if not, raise
   `ConflictError`.
4. If `schedule.default_prompt` is missing or blank, mark this as a terminal
   schedule failure with code `missing_default_prompt`, disable the schedule, and
   return a result indicating no execution should start. If a result union feels
   awkward, raise a typed internal exception that the worker catches and treats
   as "prepared nothing".
5. If `schedule_run.conversation_id` is missing, create a `Conversation` with:
   - `user_id=schedule.user_id`
   - `workspace_id=schedule.workspace_id`
   - `created_by=schedule.user_id`
   - `title` based on the schedule prompt, using the same fallback-title helper
     already used for interactive conversation creation
   - `source="scheduled"`
   - `schedule_id=schedule.id`
   - `schedule_run_id=schedule_run.id`
   - `active_agent_id=schedule.agent_id`
   - `agent_slug=schedule.agent.slug`
   - metadata containing schedule id, schedule run id, and scheduled_for as strings
6. If `schedule_run.conversation_id` exists, load and reuse that conversation.
7. If `schedule_run.agent_run_id` is missing, call `create_agent_run(...,
   trigger=RUN_TRIGGER_SCHEDULED, metadata={...})` and `link_schedule_run(...)`.
8. Set `schedule_run.status = RUN_STATUS_RUNNING`, `accepted_at = now`, and
   `claim_expires_at = None`.
9. Flush but do not call `execute_run` here. The worker should commit this
   prepared state before provider execution begins.

Promote or add a public helper in `apps/api/services/agent_schedules/runs.py` for
terminal schedule failure that disables the schedule and records the same audit
event currently handled by private `_fail_run_terminally`. Do not duplicate audit
logic in the worker.

Add tests in `apps/api/tests/services/agent_schedules/test_prepare_execution.py`:

- claimed run with prompt creates scheduled conversation, creates scheduled
  `AgentRun`, links `agent_schedule_runs.agent_run_id`, and moves the schedule
  run to `running`;
- existing `conversation_id` is reused;
- missing default prompt disables the schedule and marks the schedule run
  terminal with sanitized error text;
- non-claimed schedule run is rejected.

**Verify**:

- `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules/test_prepare_execution.py tests/services/agent_runs/test_agent_run_lifecycle.py` -> all selected tests pass.
- `cd apps/api && uv run ruff check .` -> `All checks passed!`.

### Step 4: Execute And Finalize One Scheduled Run

Create `apps/api/services/agent_schedules/finalize_schedule_run_execution.py`
with one public operation:

```python
async def finalize_schedule_run_execution(
    db: AsyncSession,
    *,
    schedule_run_id: UUID,
    agent_run_id: UUID,
    now: datetime | None = None,
) -> None:
    ...
```

Behavior:

- Lock and load the schedule run, schedule, and generic `AgentRun`.
- **Finalize must be idempotent.** If the schedule run is already in a terminal
  status (`completed`/`failed`/`cancelled`) or already `awaiting_approval`,
  early-return without touching `schedule.next_run_at` or re-recording audit
  events. Both the live worker (Step 4) and reconciliation (Step 5) can reach
  this operation for the same row; without this guard a second finalize would
  call `mark_run_completed` twice and advance `next_run_at` past a fire time
  (a double-fire). The `FOR UPDATE` lock serializes the two callers but does not
  by itself make the second call a no-op.
- If the generic run is `completed`, call `mark_run_completed(schedule, schedule_run, now=...)`.
- If the generic run is `awaiting_approval`, set schedule run status to
  `RUN_STATUS_AWAITING_APPROVAL`, clear claim expiry, and leave
  `schedule.next_run_at` unchanged. This keeps the schedule from advancing while
  human approval is pending.
- If the generic run is `failed` or `cancelled`, mark the schedule run terminal,
  disable the schedule, and record an audit event. This first runner slice should
  not retry terminal generic runs because `AgentScheduleRun.agent_run_id` is
  one-to-one with a terminal `AgentRun`.
- If the generic run is still `pending` or `running`, raise `ConflictError`; the
  worker should only finalize after `execute_run` returns or raises.

In `apps/api/workers/agent_runner.py`, implement one-run execution roughly as:

1. Open a session, configure it, call `prepare_schedule_run_execution`, commit.
2. If preparation produced no execution, commit and return.
3. Start `heartbeat_agent_run_lease` for the generic `agent_run_id`, following
   the pattern in `services/agents/runtime/worker.py`.
4. Open/use a configured session and call:

```python
await execute_run(
    session,
    conversation_id=prepared.conversation_id,
    run_id=prepared.agent_run_id,
    user_prompt=prepared.user_prompt,
    sink=NullSink(
        run_id=prepared.agent_run_id,
        conversation_id=prepared.conversation_id,
    ),
    owner_instance_id=owner_instance_id,
    expected_status=RUN_STATUS_PENDING,
)
```

5. Whether `execute_run` returns or raises after starting, stop the heartbeat.
6. Open a fresh session, call `finalize_schedule_run_execution`, and commit.
7. If the finalized generic run failed and the scheduled conversation is empty,
   call `prune_failed_empty_conversation_for_run` before committing.

Claim/setup failures before an `AgentRun` exists may use
`mark_run_retryable_failure`; when the retry cap is exhausted, terminally fail
and disable the schedule through the public terminal failure helper. Runtime
failures after an `AgentRun` exists must be terminal for this first slice.

Add tests in `apps/api/tests/services/agent_schedules/test_finalize_execution.py`:

- completed generic run advances/retires schedule through `mark_run_completed`;
- awaiting approval mirrors schedule run to `awaiting_approval` and does not
  advance `next_run_at`;
- failed generic run terminally fails and disables schedule;
- failed scheduled first conversation with no messages is pruned.

Add worker-level tests in `apps/api/tests/services/agent_schedules/test_agent_runner.py`
using `committed_db_session_factory` and `FunctionModel`/`TestModel` patterns from
runtime tests:

- `run_once` claims a due once schedule, executes it with `NullSink`, persists
  user/assistant messages, marks generic run completed, marks schedule run
  completed, and deactivates a once schedule;
- approval-required scheduled tool sets generic run and schedule run to
  `awaiting_approval`;
- provider/configuration failure marks generic run failed, terminally fails the
  schedule run, disables the schedule, and prunes the empty scheduled
  conversation.

**Verify**:

- `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules/test_finalize_execution.py tests/services/agent_schedules/test_agent_runner.py` -> all selected tests pass.
- `cd apps/api && uv run ruff check .` -> `All checks passed!`.

### Step 5: Add Reconciliation For Abandoned Schedule Executions

Create `apps/api/services/agent_schedules/reconcile_schedule_run_execution.py`
with one public operation:

```python
async def reconcile_schedule_run_execution(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
) -> int:
    ...
```

Behavior:

- First call `reap_abandoned_runs(db, now=now)` so stale generic pending/running
  runs are moved to `failed`.
- Find non-deleted schedule runs in `accepted` or `running` status.
- For rows with a linked generic `agent_run_id` whose generic run is now
  terminal or awaiting approval, call `finalize_schedule_run_execution`.
- For rows with no `agent_run_id` and an old `accepted_at` or expired
  `claim_expires_at`, mark retryable or terminal depending on attempt count.
- Return the number of schedule rows reconciled.

Call this reconciliation operation near the start of every worker `run_once`
before claiming fresh work. This prevents `AgentScheduleRun.status="running"`
from becoming permanently non-claimable if a worker process dies after linking a
generic run.

Add tests:

- running schedule row + failed generic run -> reconciled to terminal schedule
  failure and schedule disabled;
- running schedule row + completed generic run -> reconciled to completed and
  schedule advanced/retired;
- accepted schedule row with no generic run and expired timestamp -> retryable
  failure.

**Verify**:

- `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules/test_reconcile_execution.py tests/services/agent_schedules/test_agent_runner.py` -> all selected tests pass.
- `cd apps/api && uv run ruff check .` -> `All checks passed!`.

### Step 6: Finish The Worker Loop And Process Wiring

Implement the worker's public orchestration functions in
`apps/api/workers/agent_runner.py`:

- `async def run_once(...) -> int`: reconcile abandoned schedule executions,
  claim due schedule runs, commit claims, execute claimed rows sequentially, and
  return the number of claimed rows attempted.
- `async def run_forever(...) -> None`: loop `run_once`, sleep
  `settings.AGENT_SCHEDULE_WORKER_POLL_SECONDS`, and stop on the shutdown event.
- CLI `--once`: run one pass and exit 0.

Sequential execution is acceptable for this first slice. `claim_due_schedule_runs`
already accepts a batch size; parallel execution can be added later once provider
rate limits, per-workspace concurrency, and approval-heavy runs are better
understood.

Worker log entries should include `schedule_id`, `schedule_run_id`,
`agent_run_id`, and `conversation_id` where available. Do not log prompt text or
provider responses.

**Verify**:

- `cd apps/api && uv run python -m workers.agent_runner --once` -> exits 0.
- `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules` -> all pass.
- `docker compose config --services` -> includes `worker`.

### Step 7: Run Full Relevant Checks

Run the relevant backend verification suite:

```bash
cd apps/api
uv run ruff check .
uv run alembic check
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest \
  tests/services/agent_schedules \
  tests/services/conversations \
  tests/services/agent_runs \
  tests/services/agents/runtime \
  tests/routes/conversations/test_turn_streaming.py
uv run python -m workers.agent_runner --once
```

From the repo root:

```bash
docker compose config --services
```

Expected:

- Ruff exits 0.
- Alembic check exits 0 without requesting a migration.
- Pytest exits 0; DB-backed tests do not skip.
- Worker `--once` exits 0.
- Compose services include `postgres`, `api`, `worker`, and `web`.

## Test Plan

Add or update these focused tests:

- `apps/api/tests/services/conversations/test_prune_failed.py`
  - failed first run + no messages prunes;
  - failed run + messages does not prune;
  - completed run does not prune;
  - conversation with another run does not prune.
- `apps/api/tests/routes/conversations/test_turn_streaming.py`
  - first create-conversation runtime failure prunes the empty conversation from
    list/read surfaces.
- `apps/api/tests/services/agent_schedules/test_prepare_execution.py`
  - claim preparation creates/reuses scheduled conversation, creates generic
    scheduled run, links it, and validates prompt.
- `apps/api/tests/services/agent_schedules/test_finalize_execution.py`
  - generic completed/awaiting_approval/failed statuses mirror correctly to
    `agent_schedule_runs`.
- `apps/api/tests/services/agent_schedules/test_reconcile_execution.py`
  - stale schedule execution states are reconciled from generic run status.
- `apps/api/tests/services/agent_schedules/test_agent_runner.py`
  - `run_once` happy path, approval path, failure/pruning path.

Follow the committed DB fixture patterns in `apps/api/tests/conftest.py:98` for
worker tests where independent sessions must see committed state. Follow the
runtime test model patterns in
`apps/api/tests/services/agents/runtime/test_runtime_core.py:641` for long or
deterministic provider-free runs.

## Done Criteria

All must hold:

- [ ] `apps/api/workers/agent_runner.py` exists and supports `--once`.
- [ ] `docker compose config --services` lists `worker`.
- [ ] `makefiles/local.mk` has a `worker-dev` target and local `dev` starts it.
- [ ] Scheduled due rows are claimed via `claim_due_schedule_runs`, not via an
      HTTP call.
- [ ] Scheduled runs call the existing `execute_run` function with `NullSink`.
- [ ] Completed scheduled once-runs retire their schedule.
- [ ] Approval-required scheduled runs leave both generic and schedule run state
      in `awaiting_approval`.
- [ ] Runtime failures after generic `AgentRun` creation terminally fail and
      disable the schedule for this first slice.
- [ ] Empty failed first conversations are soft-deleted; conversations with any
      durable messages are preserved.
- [ ] New DB-backed tests pass with `TEST_DATABASE_URL` set and do not skip.
- [ ] `cd apps/api && uv run ruff check .` exits 0.
- [ ] `cd apps/api && uv run alembic check` exits 0.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report back if:

- The drift check shows that `execute_run`, `AgentScheduleRun.agent_run_id`, or
  `claim_due_schedule_runs` changed materially from the excerpts above.
- You find that schedule runtime failures must be retried automatically in this
  slice. That conflicts with the current one-to-one schedule-run-to-agent-run
  schema and needs a design decision.
- Preparing a scheduled run requires adding a new database column.
- You cannot make `python -m workers.agent_runner --once` exit cleanly without
  model credentials when there are no due schedules (Postgres up, empty
  due-queue). A failure to *connect* to Postgres is a local environment problem,
  not this STOP condition — start the database and retry.
- The pruning helper would need to delete conversations that contain any
  non-deleted messages. Preserve those conversations and report back.
- A verification command fails twice after reasonable local fixes.

## Maintenance Notes

- Review transaction boundaries carefully. Claiming, preparation, runtime
  execution, and finalization should commit at clear boundaries because
  `execute_run` commits internally.
- Review recovery behavior carefully. `AgentScheduleRun.status="running"` is
  non-claimable in the current helper, so reconciliation is required before this
  worker can be considered durable.
- Future support for retrying provider/runtime failures likely requires either
  multiple generic `AgentRun` attempts per `AgentScheduleRun` or a new attempt
  table. Do not work around that by reusing terminal generic runs.
- Future frontend approval work must account for scheduled runs in
  `awaiting_approval`; this plan only persists the state, it does not add UI.
