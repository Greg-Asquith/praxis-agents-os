# Plan 053: Cooperative run cancellation (kill switch)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/api/services/agent_runs/ apps/api/routes/agent_runs/ apps/api/services/agents/runtime/ apps/web/src/features/conversations/`
> Compare the "Current state" excerpts against live code before proceeding;
> treat a structural mismatch (run status transition matrix, heartbeat/lease
> seam, `RunTaskRegistry` shape, `execute_run` exception layout) as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the run lifecycle exception path; a wrong
  `CancelledError` interaction can turn cancellation into `failed` rows or
  leak provider streams)
- **Depends on**: none hard (all seams landed with 001/005/026). Should land
  **before 041** — money-spending integration tools must be stoppable.
- **Category**: Lane H — harness hardening (post-roadmap additions
  053–060, added 2026-07-07)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07 (036 landed
  on disk, uncommitted; its diff touches conversation streaming payloads but
  not the run lifecycle files this plan changes)

## Product intent

Today "Cancel" does not exist for users, and the service that implements it
is dead code: `services/agent_runs/cancel.py` flips the DB row and is called
only from tests. There is no route, no stop button, and — critically — no
mechanism that stops the *executing task*. A run that is looping on tool
calls, waiting on a slow provider, or burning tokens continues until it
finishes, hits `UsageLimits`, or is reaped by the lease deadline
(`AGENT_RUN_MAX_DURATION_SECONDS`). The client-side `abort()` in
`use-agent-stream.ts` only closes the HTTP response; the detached worker
keeps running by design (that is the disconnected-turn durability feature).

This plan makes cancellation real and cooperative:

1. A user can stop their own run from the conversation UI.
2. The server flips the run to `cancelled` **and** interrupts the executing
   asyncio task — immediately when the task is local to the process,
   within one heartbeat interval when it is not (other API instance, or the
   scheduled-run worker process).
3. A cancelled run persists as `cancelled`, never `failed`, and its SSE
   stream terminates with the existing `run.status`/`done` events — no new
   protocol event names.

## Decisions taken

1. **Cancellation is cooperative, two-tier.** Tier 1 (fast path): the cancel
   service asks the process-local `RunTaskRegistry` to `cancel(run_id)` —
   interactive runs hosted by the same API instance stop immediately. Tier 2
   (universal path): the status flip to `cancelled` makes the next lease
   renewal return `False` (`renew_agent_run_lease` only matches
   `pending`/`running` rows, `services/agent_runs/renew_lease.py:36`); the
   heartbeat then checks the run status and cancels the executing task it
   now supervises. This covers the scheduled-run worker process and
   multi-instance API deployments with worst-case latency of one
   `AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS`. No new IPC, no Redis, no
   LISTEN/NOTIFY — the lease heartbeat already polls the row.
2. **The DB status flip is the source of truth; task cancel is best-effort
   delivery.** `cancel_agent_run` commits `cancelled` first. If the task
   cancel never lands (process crash), the existing reaper still closes the
   run out. Cancelling an already-terminal run is a 409 (`ConflictError`),
   cancelling an `awaiting_approval` run is allowed and requires no task
   kill (nothing is executing; the approval-resume path already rejects
   non-`awaiting_approval` runs via `expected_status`).
3. **`CancelledError` is handled explicitly in `execute_run`, separately
   from the failure path.** The current `except Exception` block
   (`execute_run.py:336`) does not catch `asyncio.CancelledError`
   (a `BaseException`) — that is correct and must stay true. A new
   `except asyncio.CancelledError` block: best-effort persists the run as
   `cancelled` (idempotent — the interactive parent is usually already
   `cancelled` from the route; a delegated child is not), best-effort emits
   `run.status {cancelled}` + `done {cancelled}`, then **re-raises**. All
   cleanup inside the handler is short and guarded — after the first
   `CancelledError` is caught, awaits proceed normally unless a second
   cancel arrives, so no `asyncio.shield` is needed; a fresh short-lived
   session is used for the persistence write because the main session may
   hold a rolled-back transaction.
4. **Delegated children cancel with their parent.** Sequentially-awaited
   children run inside the parent's task, so `task.cancel()` propagates
   through the `await execute_run(...)` in `delegate_to_agent.py:145` and
   the child's own `CancelledError` handler persists the child row as
   `cancelled`. No child-specific cancel API in this plan. (Plan 057 makes
   fan-out concurrent; its STOP list re-verifies propagation for
   pydantic-ai-created tool tasks.)
5. **No partial-message persistence.** In-flight assistant deltas from the
   cancelled provider stream are dropped; the conversation keeps everything
   already committed (the user message committed at turn start via
   `new_messages()` persistence happens only at terminal persistence, so a
   cancelled first turn shows the user message absent — see STOP list note).
   Persisting a partial assistant message is a recorded follow-up, not v1.
6. **Permissions: run owner or workspace manager.** The actor may cancel
   runs where `user_id == actor.id`; owners/admins may cancel any workspace
   run (mirrors the 021 schedules rule "mutate others' = owner-or-admin").
   Cancellation writes an audit event (`resource_type="agent_run"`,
   action `cancel`) — a manager killing someone else's run must be
   attributable.
7. **No new SSE event names.** `run.status` with `{"status": "cancelled"}`
   and `done` with the same status ride the existing versioned protocol;
   the web reducer and `run-status-badge.tsx` already render `cancelled`.
   The frontend stop button calls the new route and lets the stream
   terminate server-side; the local `abort()` remains the
   connection-teardown fallback only.
8. **Scheduled runs are cancellable through the same route.** The linked
   `agent_schedule_runs` row finalizes through the existing
   `finalize_schedule_run_execution`, which already handles
   `RUN_STATUS_CANCELLED` (`services/agent_schedules/finalize_schedule_run_execution.py:173-179`).
   The worker-process heartbeat (delegation `utils.heartbeat` and the
   schedule runner's lease loop) gains the same cancel-detection seam.

## Why this matters

Every capability phase after this one raises the cost of an unstoppable
run: integration writes (041) spend real money, KB ingestion tools chew
embedding budget, and memory writes mutate durable state. "Permissioned,
observable, and reversible" (AGENTS.md) requires *stoppable* first. This is
also a trust-surface feature: the stop button is the most basic control an
SME operator expects, and its absence is glaring next to the approval
machinery the product already has.

## Current state

All anchors verified on the working tree at `c2f08cc` (2026-07-07).

- **Dead cancel service**: `services/agent_runs/cancel.py:12-14` —
  `cancel_agent_run` = `transition_run_status(db, run, RUN_STATUS_CANCELLED)`;
  callers are only `tests/services/agent_runs/test_agent_run_lifecycle.py`.
  Transition matrix (`services/agent_runs/domain.py:31-49`):
  `pending`/`running`/`awaiting_approval` may all reach `cancelled`;
  `TERMINAL_RUN_STATUSES = {completed, failed, cancelled}`.
- **No cancel route**: `routes/agent_runs/__init__.py` composes only
  `get_approval_state` and `resume_run`.
- **Task registry**: `services/agents/runtime/run_manager.py` —
  `RunTaskRegistry` holds `dict[UUID, asyncio.Task]`, has `spawn`,
  `is_running`, `drain`, and a done-callback that tolerates cancelled tasks
  (`_log_task_exception` returns early for `task.cancelled()`,
  lines 55-61). **No `cancel` method exists.** Spawners:
  `create_conversation_stream.py:131`, `create_turn_stream.py:140`,
  `resume_run_stream.py:88`.
- **Workers**: `services/agents/runtime/worker.py` — `run_turn_worker` /
  `run_resume_worker` open their own session, spawn
  `heartbeat_agent_run_lease` (lines 51-58), call `execute_run`, and catch
  `except Exception` only (line 73) — `CancelledError` currently escapes to
  the registry done-callback, which is silent, but nothing persists the
  `cancelled` row or emits terminal SSE events, and the interactive session
  is closed in `finally` (correct).
- **Heartbeat**: `services/agents/runtime/heartbeat.py:39-70` — loop calls
  `renew_agent_run_lease_once`; when `renewed` is `False` it logs
  "no longer live" and `break`s. It has **no reference to the task it
  guards** — the cancel-detection seam must be threaded in by the caller.
- **Lease renewal**: `services/agent_runs/renew_lease.py:31-41` — `UPDATE`
  guarded by `status IN (pending, running)`; a `cancelled` row therefore
  stops renewing on the next beat.
- **`execute_run` exception layout**: `execute_run.py:336-368` —
  `except Exception` rolls back, persists `failed` (only if `started`),
  emits `error` + `done`, re-raises; `finally` closes the sink. The
  `started` flag commits at line 152 before streaming begins.
- **Delegated child heartbeat**: `delegation/utils.py` `heartbeat` mirrors
  the worker heartbeat for child runs (spawned at
  `delegate_to_agent.py:138-141`).
- **Reaper**: `services/agent_runs/reap_abandoned.py` closes out runs whose
  lease/grace/hard deadline expired — the backstop when no cooperative
  cancel lands.
- **Frontend**: `use-agent-stream.ts:49-76,161` — `AbortController` only;
  `run-status-badge.tsx` already has a `cancelled` presentation; the
  composer has no stop control. Conversation heal loop
  (`use-conversation-heal-loop.ts`) re-fetches persisted state after stream
  teardown — it will reconcile a cancelled run without changes.
- **Audit**: `services/audit_events/` has generic recorders; agent-run rows
  audit via `resource_type="agent_run"` in existing flows.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint (API) | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Focused tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agent_runs tests/routes/agent_runs tests/services/agents/runtime -q` | all pass |
| Full API tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest -q` | all pass |
| Frontend gate | `cd apps/web && pnpm check` | all gates pass |
| Manual smoke | `make dev`, start a slow turn, hit stop | run flips to cancelled; stream ends with `done {cancelled}` |

## Scope

**In scope (API):**

- `services/agent_runs/cancel.py` (extend: scoping/guards/audit/task-kill
  orchestration — or keep it thin and add
  `services/agent_runs/request_cancel.py` following one-op-per-file; the
  route consumes the new operation)
- `routes/agent_runs/cancel_run.py` (create) + `routes/agent_runs/__init__.py`
- `services/agents/runtime/run_manager.py` (add `cancel(run_id) -> bool`)
- `services/agents/runtime/heartbeat.py` (cancel-detection: optional
  `cancel_target: asyncio.Task | None` param; on `not renewed`, load the
  run status in a short session and `cancel_target.cancel()` iff status is
  `cancelled`)
- `services/agents/runtime/worker.py` (pass `asyncio.current_task()` into
  the heartbeat for both workers)
- `services/agents/runtime/delegation/utils.py` (same for the child
  heartbeat)
- `services/agents/runtime/execute_run.py` (the `except
  asyncio.CancelledError` handler per decision 3)
- `services/agents/runtime/run_persistence.py` (add
  `persist_cancelled_run` — fresh-session, idempotent, transition-guarded)
- `tests/services/agent_runs/`, `tests/routes/agent_runs/`,
  `tests/services/agents/runtime/` additions

**In scope (Web):**

- `features/conversations/api/cancel-run.ts` (create — `useMutation`,
  invalidates the conversation/active-run queries)
- Stop control in the composer / streaming header (wherever the current
  streaming state renders; follow the existing component seams)
- `features/conversations/types.ts` (request/response types)

**Out of scope (do NOT touch):**

- Partial assistant-message persistence (decision 5 — follow-up).
- The SSE protocol (`stream/protocol.ts`, `events.py` event names).
- The reaper thresholds and lease TTLs.
- Schedule pause/enable semantics (021 owns those); this plan only makes
  the linked generic run cancellable.
- Any queue/broker infrastructure.

## Git workflow

- Branch: `advisor/053-cooperative-run-cancellation`
- Commits: `API - Cooperative Run Cancellation` / `Web - Run Stop Control`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `persist_cancelled_run` + registry `cancel`

1. `run_persistence.py`: `persist_cancelled_run(run_id) -> AgentRun | None`
   — opens its own short session (mirror `persist_failed_run`'s
   fresh-session pattern if it has one; otherwise follow
   `heartbeat.renew_agent_run_lease_once`), loads the run, returns it
   unchanged if already terminal, else `transition_run_status` →
   `cancelled`, commit. Never raises into the caller's cancellation
   unwind — log and return `None` on failure.
2. `run_manager.py`: `cancel(self, run_id) -> bool` — look up a live task,
   `task.cancel()`, return whether a cancel was delivered. Keep the
   done-callback behavior unchanged (it already tolerates cancelled tasks).

**Verify**: `uv run ruff check .`; unit test for `cancel()` on a stubbed
task.

### Step 2: cancel service + route + audit

1. Cancel operation: load run by id (workspace-scoped), enforce decision 6
   permissions, 409 on terminal status, `cancel_agent_run` (status flip) +
   commit, audit event, then best-effort `run_task_registry.cancel(run_id)`.
   Return the updated run projection.
2. `routes/agent_runs/cancel_run.py`: `POST /agent-runs/{run_id}/cancel`,
   standard deps, member access + decision 6 check in the service.
   Register in `routes/agent_runs/__init__.py`.

**Verify**: route registry lists the path; curl against a running run
returns `cancelled`; second call returns 409.

### Step 3: heartbeat cancel-detection

Extend `heartbeat_agent_run_lease(..., cancel_target: asyncio.Task | None = None)`:
when `renewed` is `False`, open a short session, read the run status; if
`cancelled` and `cancel_target` is live, `cancel_target.cancel()` and log;
then `break` as today. Thread `asyncio.current_task()` through
`run_turn_worker`, `run_resume_worker`, and the delegation heartbeat
spawner. The schedule runner's execution path uses the same workers/seams —
confirm `workers/agent_runner.py` reaches `execute_run` through a heartbeat
that now carries the target (if it heartbeats through a different helper,
extend that one identically and record it).

**Verify**: runtime test — start a `FunctionModel` turn whose scripted tool
sleeps; flip the run to `cancelled` out-of-band; assert the task receives
`CancelledError` within one (test-shortened) heartbeat interval.

### Step 4: `execute_run` CancelledError handler

Per decision 3, before the existing `except Exception`:

```python
except asyncio.CancelledError:
    with suppress(Exception):
        await db.rollback()
    cancelled_run = await persist_cancelled_run(run_id)
    status = cancelled_run.status if cancelled_run else RUN_STATUS_CANCELLED
    with suppress(Exception):
        await event_sink.emit(EVENT_RUN_STATUS, {"status": status})
        await event_sink.emit(EVENT_DONE, {"status": status})
    raise
```

The `finally` still closes the sink. Confirm the provider stream context
manager (`run_stream_events`) exits cleanly under cancellation (its
`__aexit__` runs during unwind — if it swallows or re-wraps
`CancelledError`, STOP and record).

**Verify**: the Step 3 test now also asserts: run row `cancelled` (not
`failed`), sink received `run.status {cancelled}` + `done {cancelled}`, no
`error` event, and `persist_failed_run` was not invoked.

### Step 5: delegated-child propagation test

Scenario: parent turn delegates (scripted via `FunctionModel` on both
agents); cancel the parent mid-child-execution; assert both parent and
child rows end `cancelled` and the child's schedule/heartbeat tasks are
torn down (no leaked task warnings).

### Step 6: scheduled-run cancellation test

Suspend-free scheduled run mid-execution in the worker harness (reuse the
schedule-runner test fixtures), cancel via the service, assert the linked
`agent_schedule_runs` row finalizes through the existing
`RUN_STATUS_CANCELLED` branch.

### Step 7: frontend stop control

`cancel-run.ts` mutation + a stop button rendered only while the stream is
active (`use-agent-stream` exposes the live run id). On click: call the
mutation; do **not** locally abort — let the server terminate the stream
(`done {cancelled}`); keep the existing unmount abort behavior. Invalidate
the active-run and conversation queries on success.

**Verify**: `pnpm check`; manual — stop mid-stream shows the cancelled
badge and the composer unlocks.

## Test plan

Backend (~10-14 tests): service scoping/permission/terminal-409/audit; the
registry `cancel`; heartbeat detection; `execute_run` cancelled-terminal
behavior (status, events, no-failed); delegated propagation; scheduled
finalization. Frontend: static gate + manual script (no component
framework).

## Done criteria

- [ ] `POST /api/v1/agent-runs/{id}/cancel` exists, is workspace/permission
      scoped, audits, and 409s on terminal runs
- [ ] A locally-hosted interactive run stops within ~1s of the call; a
      worker-hosted scheduled run stops within one heartbeat interval
- [ ] Cancelled runs persist `status="cancelled"` with no `failed`
      overwrite; delegated children cancel with the parent
- [ ] SSE terminates with existing `run.status`/`done` events only — no new
      event names, `stream/protocol.ts` untouched
- [ ] Stop control visible only during an active stream; `pnpm check` and
      the API suites pass
- [ ] `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `run_stream_events`' context manager swallows/re-wraps `CancelledError`
  on exit — the terminal-status guarantee breaks; probe the installed
  pydantic-ai and record the actual unwind behavior before continuing.
- `transition_run_status` rejects `awaiting_approval → cancelled` (the
  domain matrix excerpt says it is allowed; if the code disagrees, the
  matrix is the contract to fix, not bypass).
- The user message of a cancelled *first* turn is lost because persistence
  only happens at terminal `new_messages()` handling — if manual testing
  shows the user's prompt vanishing from the conversation, record it and
  ask whether to persist the prompt eagerly; do not bolt on a second
  persistence path silently.
- Cancelling requires touching the SSE protocol or adding an event name.
- The schedule runner heartbeats through a seam this plan did not extend.

## Maintenance notes

- **Plan 057 (parallel fan-out)** must re-verify decision 4: concurrent
  children run in pydantic-ai-created tool tasks, and parent-task
  cancellation reaching them is that plan's responsibility to prove.
- **Partial-message persistence** on cancel is the recorded follow-up; if
  users complain that stopped runs "lose the answer so far", that is the
  feature to build — not a longer grace period.
- The heartbeat cancel-detection reads one extra row per beat only after a
  failed renewal — do not add a per-beat status query to the happy path.
- Reviewers should scrutinize: the `except asyncio.CancelledError` block
  re-raising unconditionally, `persist_cancelled_run` never raising, and
  the route's permission branch (owner-or-manager) having tests for the
  deny case.
