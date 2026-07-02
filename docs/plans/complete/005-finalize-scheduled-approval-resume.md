# Plan 005: Finalize Scheduled Runs After Approval Resume

> **Executor instructions**: Follow this plan step by step. This slice fixes the
> scheduled-run lifecycle after a human resumes an approval-required run. Do not
> implement schedule CRUD routes, frontend approval UI, or generic runtime retry
> semantics in this plan. When done, update the status row for this plan in
> `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat fdf7220..HEAD -- apps/api/services/agent_runs/resume_run_stream.py apps/api/services/agents/runtime/worker.py apps/api/services/agent_schedules apps/api/workers/agent_runner.py apps/api/tests/services/agent_schedules apps/api/tests/routes/conversations/test_turn_streaming.py apps/api/tests/services/agents/runtime/test_runtime_core.py docs/plans`
>
> If any in-scope file changed since this plan was written, compare the "Current
> State" excerpts below against the live code before proceeding. If schedule-run
> finalization or resume-worker ownership changed materially, treat that as a
> STOP condition until this plan is refreshed.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: Plan 001 scheduled agent runner
- **Category**: bug
- **Planned at**: commit `fdf7220`, 2026-07-01
- **Status**: TODO

## Why This Matters

Scheduled agent runs now use the same `agent_runs` runtime path as interactive
turns, including approval suspension. The first pause works: a scheduled run can
leave both `agent_runs.status` and `agent_schedule_runs.status` at
`awaiting_approval`. The missing piece is the continuation: when the user resumes
the generic run and it completes or fails, the linked schedule row is not advanced
or terminally failed. That leaves once schedules active and interval schedules
stuck behind an already-resumed approval row.

This plan makes `awaiting_approval` a resumable schedule-run state, finalizes the
linked schedule row after resume workers finish, and adds regression coverage for
the scheduled approval lifecycle.

## Current State

Relevant files:

- `apps/api/services/agent_runs/resume_run_stream.py` validates approval decisions
  and spawns `run_resume_worker`.
- `apps/api/services/agents/runtime/worker.py` owns detached interactive and
  resume workers with independent database sessions.
- `apps/api/services/agent_schedules/finalize_schedule_run_execution.py` mirrors
  generic `AgentRun` state onto `AgentScheduleRun`.
- `apps/api/services/agent_schedules/reconcile_schedule_run_execution.py` recovers
  stale scheduled execution rows.
- `apps/api/tests/services/agent_schedules/test_agent_runner.py` covers scheduled
  happy path, approval suspension, and provider failure, but not approval resume.

Current resume route behavior:

```python
# apps/api/services/agent_runs/resume_run_stream.py:66
sink = StreamSink(run_id=run.id, conversation_id=run.conversation_id)
await sink.emit(EVENT_RUN_STATUS, {"status": run.status})
run_task_registry.spawn(
    run.id,
    run_resume_worker(
        run_id=run.id,
        conversation_id=run.conversation_id,
        message_history=suspended_state.message_history,
        deferred_tool_results=deferred_tool_results,
        sink=sink,
    ),
)
```

Current resume worker behavior:

```python
# apps/api/services/agents/runtime/worker.py:79
async def run_resume_worker(...):
    ...
    try:
        ...
        await execute_run(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            user_prompt=None,
            sink=sink,
            model=model,
            owner_instance_id=owner_instance_id,
            expected_status=RUN_STATUS_AWAITING_APPROVAL,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
        )
    except Exception:
        await session.rollback()
        logger.exception(...)
    finally:
        ...
        await session.close()
        await sink.close()
```

Current finalizer treats schedule `awaiting_approval` as already finalized:

```python
# apps/api/services/agent_schedules/finalize_schedule_run_execution.py:33
_FINALIZED_SCHEDULE_RUN_STATUSES = {
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_TERMINAL_FAILED,
}
```

Current reconciler does not revisit schedule rows already marked
`awaiting_approval`:

```python
# apps/api/services/agent_schedules/reconcile_schedule_run_execution.py:42
select(AgentScheduleRun)
.where(
    AgentScheduleRun.deleted == False,
    AgentScheduleRun.status.in_({RUN_STATUS_ACCEPTED, RUN_STATUS_RUNNING}),
)
```

Pydantic AI approval semantics are already implemented correctly in the generic
runtime. `execute_run` resumes with `DeferredToolResults`, clears approval state
on success, and persists terminal generic run state.

## Commands You Will Need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| API lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Focused schedule tests | `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules/test_finalize_execution.py tests/services/agent_schedules/test_reconcile_execution.py tests/services/agent_schedules/test_agent_runner.py` | all selected tests pass; DB-backed tests do not skip |
| Runtime approval tests | `cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agents/runtime/test_runtime_core.py tests/routes/conversations/test_turn_streaming.py` | all selected tests pass |

If Postgres is not running, start it through the repo's existing local target:
`make db-up`.

## Scope

**In scope**:

- `apps/api/services/agent_schedules/finalize_schedule_run_execution.py`
- `apps/api/services/agent_schedules/reconcile_schedule_run_execution.py`
- `apps/api/services/agents/runtime/worker.py`
- `apps/api/services/agent_schedules/__init__.py` only if you add a reusable
  helper that must be exported
- `apps/api/tests/services/agent_schedules/test_finalize_execution.py`
- `apps/api/tests/services/agent_schedules/test_reconcile_execution.py`
- `apps/api/tests/services/agent_schedules/test_agent_runner.py`
- Existing runtime/route tests only if a signature change requires updating them

**Out of scope**:

- Schedule CRUD/list/detail API routes.
- Frontend approval or schedule UI.
- Retrying terminal generic runtime failures.
- Changing the one-to-one `agent_schedule_runs.agent_run_id` model.
- Installing or using `pydantic-ai-harness`.

## Git Workflow

- Suggested branch: `advisor/005-scheduled-approval-resume`.
- Commit style should match recent history, for example:
  `API - Finalize Scheduled Approval Resumes`.
- Do not push or open a PR unless the operator asks.

## Steps

### Step 1: Make `awaiting_approval` Resumable In The Schedule Finalizer

Edit `apps/api/services/agent_schedules/finalize_schedule_run_execution.py`.

Change the finalizer's idempotency rule so `completed`, `terminal_failed`, and
`cancelled` are terminal no-op states, but `awaiting_approval` is not terminal.
The finalizer should:

- return early only for final schedule statuses;
- set or keep `agent_schedule_runs.status = awaiting_approval` when the generic
  run is still `awaiting_approval`;
- transition `awaiting_approval -> completed` when the generic run is completed;
- transition `awaiting_approval -> terminal_failed` when the generic run failed
  or was cancelled;
- preserve the existing conflict for generic `pending` or `running`.

Target shape:

```python
_TERMINAL_SCHEDULE_RUN_STATUSES = {
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_TERMINAL_FAILED,
}
```

Then leave the existing `agent_run.status` switch to decide the next state.

Add tests in `test_finalize_execution.py`:

- a schedule run already in `awaiting_approval` with a completed generic run is
  finalized as `completed` and advances/retires the schedule;
- a schedule run already in `awaiting_approval` with a failed generic run becomes
  `terminal_failed` and disables the schedule;
- a schedule run and generic run both still `awaiting_approval` remains
  `awaiting_approval` and does not advance `next_run_at`.

**Verify**:
`cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules/test_finalize_execution.py`
-> all selected tests pass.

### Step 2: Reconcile Awaiting-Approval Schedule Rows After Generic Completion

Edit `apps/api/services/agent_schedules/reconcile_schedule_run_execution.py`.

Select awaiting-approval schedule rows for reconciliation **only when their
linked generic run has already reached a terminal status**. This is the safety
net for a resume worker that finishes the generic run but crashes or is killed
before finalizing the schedule row.

Do **not** select still-paused rows (schedule row `awaiting_approval` + generic
run still `awaiting_approval`). Those legitimately wait on a human for an
unbounded time; selecting them on every poll pass would churn the `limit(...)`
batch and inflate the reconciled count. Filtering on the generic run's terminal
status keeps still-paused approvals out of reconciliation entirely, so no no-op
counting question arises.

Implementation notes:

- Keep the existing `ACCEPTED`/`RUNNING` branch and `OR` in the new
  awaiting-approval-with-terminal-generic branch. The `ACCEPTED`/`RUNNING` rows
  may have a null `agent_run_id` (handled by the stale-pre-execution path), so
  the join to `AgentRun` **must be an outer join** — an inner join would
  silently drop those null-linked rows and break stale-setup recovery.
- Scope the row lock to the schedule table with
  `.with_for_update(skip_locked=True, of=AgentScheduleRun)` so the join does not
  try to lock `AgentRun` rows.
- Import the schedule-domain `RUN_STATUS_AWAITING_APPROVAL` from
  `services.agent_schedules.runs` (distinct from the already-imported generic
  `AGENT_RUN_STATUS_AWAITING_APPROVAL`). `TERMINAL_RUN_STATUSES` is already
  imported and excludes `awaiting_approval`, which is exactly the filter we want.

Target shape:

```python
select(AgentScheduleRun)
.outerjoin(AgentRun, AgentScheduleRun.agent_run_id == AgentRun.id)
.where(
    AgentScheduleRun.deleted == False,  # noqa: E712
    or_(
        AgentScheduleRun.status.in_({RUN_STATUS_ACCEPTED, RUN_STATUS_RUNNING}),
        and_(
            AgentScheduleRun.status == RUN_STATUS_AWAITING_APPROVAL,
            AgentRun.status.in_(TERMINAL_RUN_STATUSES),
        ),
    ),
)
.order_by(AgentScheduleRun.created_at)
.limit(batch_size or DEFAULT_RECONCILE_BATCH_SIZE)
.with_for_update(skip_locked=True, of=AgentScheduleRun)
```

Add tests in `test_reconcile_execution.py`:

- schedule row `awaiting_approval` + generic run `completed` is selected and
  reconciles to `completed`;
- schedule row `awaiting_approval` + generic run `failed` reconciles to
  `terminal_failed`;
- schedule row `awaiting_approval` + generic run still `awaiting_approval` is
  **not** selected — it stays `awaiting_approval` and does not advance
  `next_run_at` or increment the reconciled count;
- an `ACCEPTED`/`RUNNING` row with a null `agent_run_id` is still selected
  (regression guard proving the outer join did not drop null-linked rows).

**Verify**:
`cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules/test_reconcile_execution.py`
-> all selected tests pass.

### Step 3: Finalize A Linked Schedule After `run_resume_worker`

Edit `apps/api/services/agents/runtime/worker.py`.

After `run_resume_worker` calls `execute_run`, finalize any linked
`AgentScheduleRun`. Use a fresh short-lived session for finalization, following
the same transaction-boundary style as `_finalize` in
`apps/api/workers/agent_runner.py`. Do not reuse the long runtime session for a
separate schedule-finalization commit.

Recommended implementation:

- create a private helper in `runtime/worker.py`, for example
  `_finalize_linked_schedule_run(run_id: UUID) -> None`;
- in that helper, open a new session with `get_async_db_session_factory()` and
  `configure_async_db_session()`;
- **defensive status re-check**: re-read the generic run
  (`run = await db.get(AgentRun, run_id)`). If it is `None`, or its status is
  `pending`/`running`, return without finalizing — never finalize an active run.
  This guards the mid-stream-cancellation case (worker killed before
  `execute_run` commits a terminal status) and documents the dependency on the
  commit-before-raise invariant (see Maintenance Notes);
- look up a non-deleted `AgentScheduleRun` where `agent_run_id == run_id`;
- if none exists, return silently so interactive resumes are unaffected;
- call `finalize_schedule_run_execution(db, schedule_run_id=..., agent_run_id=run_id)`
  and commit on success;
- **mirror `_finalize` in `workers/agent_runner.py`** for errors: on
  `ConflictError`, rollback and log a warning (generic run still active /
  mid-transition); on any other `Exception`, rollback and log `.exception`.

Invoke the helper **exactly once** from `run_resume_worker`'s existing `finally`
block (after the heartbeat stop and `session.close()`, before `sink.close()`).
Because the helper uses its own session, it is independent of the runtime
session's `rollback()` in the `except` branch. A single `finally` call covers
every outcome the finalizer already handles:

- completion → schedule row advances to `completed` (and retires/advances the
  schedule);
- failure → `execute_run` already committed the failed generic run before
  re-raising, so the fresh session reads it and marks the schedule row
  `terminal_failed`;
- re-suspension (agent calls another approval tool on resume) → generic run is
  `awaiting_approval` again, and the finalizer keeps the schedule row
  `awaiting_approval` without advancing `next_run_at`;
- mid-stream cancellation → generic run still `running`, so the defensive
  re-check skips finalization.

Add a worker-level test in `test_agent_runner.py`:

1. Create a due schedule whose agent has `add_numbers` with policy `approval`.
2. Run `run_once(..., model=TestModel())` and assert both generic and schedule
   rows are `awaiting_approval`.
3. Load the suspended approval state from the generic run.
4. Call `run_resume_worker(...)` with `ToolApproved(...)`, `NullSink`, and
   `TestModel()`.
5. Assert the generic run is `completed` and the linked schedule row is
   `completed`; for a once schedule, assert `schedule.is_active is False`.

If `run_resume_worker` is awkward to call from this test because it opens global
sessions, follow the existing `test_agent_runner.py` patterns that use the
committed database session factory.

**Verify**:
`cd apps/api && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest tests/services/agent_schedules/test_agent_runner.py`
-> all selected tests pass.

### Step 4: Run The Focused Regression Gate

Run all focused tests touched by this lifecycle:

```bash
cd apps/api
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uv run pytest \
  tests/services/agent_schedules/test_finalize_execution.py \
  tests/services/agent_schedules/test_reconcile_execution.py \
  tests/services/agent_schedules/test_agent_runner.py \
  tests/services/agents/runtime/test_runtime_core.py \
  tests/routes/conversations/test_turn_streaming.py
uv run ruff check .
```

Expected result: all tests pass and Ruff exits 0.

## Test Plan

New or updated tests:

- `test_finalize_execution.py`
  - awaiting schedule + completed generic run completes schedule;
  - awaiting schedule + failed generic run terminally fails schedule;
  - awaiting schedule + awaiting generic run stays paused.
- `test_reconcile_execution.py`
  - awaiting schedule rows are reconciled only when the generic run has reached a
    terminal status; still-paused rows (generic run still `awaiting_approval`)
    are excluded and left untouched;
  - `ACCEPTED`/`RUNNING` rows with a null `agent_run_id` are still selected
    (outer-join regression guard).
- `test_agent_runner.py`
  - scheduled approval suspension followed by resume finalizes the schedule row.

Use existing `TestModel` and `ToolApproved` patterns from
`apps/api/tests/services/agents/runtime/test_runtime_core.py`.

## Done Criteria

- [ ] Scheduled approval resume updates the linked `agent_schedule_runs` row.
- [ ] `agent_schedule_runs.status = awaiting_approval` is not treated as terminal
      once the linked generic run has completed or failed.
- [ ] Reconciliation includes awaiting-approval schedule rows whose generic run
      has reached a terminal status, and excludes still-paused ones.
- [ ] Focused DB-backed tests pass with `TEST_DATABASE_URL` set.
- [ ] `cd apps/api && uv run ruff check .` exits 0.
- [ ] No frontend files are modified.
- [ ] `docs/plans/000_README.md` status row updated.

## STOP Conditions

Stop and report back if:

- `AgentScheduleRun.agent_run_id` is no longer one-to-one with `AgentRun`.
- The generic resume worker no longer persists terminal generic run state through
  `execute_run`.
- Correct finalization requires changing schedule retry semantics for terminal
  generic runtime failures.
- The fix appears to require a new database column.
- The focused lifecycle tests fail twice after reasonable fixes.

## Maintenance Notes

Reviewers should pay close attention to transaction boundaries. The runtime
session, heartbeat session, and schedule-finalization session must stay separate
so a finalization commit cannot accidentally commit partial runtime work.

This slice rests on an `execute_run` invariant: it commits terminal/suspended
generic run state **before** returning or re-raising. On failure it calls
`persist_failed_run`, which commits the failed status
(`services/agents/runtime/run_persistence.py`) before `execute_run` re-raises, so
the resume worker's later `session.rollback()` is a no-op against that committed
state and the fresh finalize session reliably reads the terminal status. The
Step 3 defensive re-check (skip finalize when the generic run is still
`pending`/`running`) exists so that if this invariant ever regresses, the
finalizer fails closed — an active run is never finalized — rather than
corrupting the schedule row. If you change `execute_run`'s failure-commit
behavior, revisit this plan (it is also a STOP condition).

Future schedule CRUD/UI work should assume `awaiting_approval` is a pause state,
not a final state. Future retry support for terminal generic failures will still
need a separate design because this plan keeps the current one-to-one
schedule-fire-to-generic-run model.
