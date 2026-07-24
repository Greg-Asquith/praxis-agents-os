# Agent Turn Streaming + Disconnect-Safe Persistence (Plan)

Status: **implemented for the backend streamed-turn slice**. This document is the
accepted plan that guided the current implementation in
`services/conversations/create_turn_stream.py`,
`services/agents/runtime/worker.py`, and `services/agents/runtime/execute_run.py`.
The frontend heal loop and explicit cancel endpoint remain pending.

## Goals (non-negotiable)

1. **UI streaming** — the client sees assistant text, tool calls, and run status
   live over SSE while a turn runs.
2. **Saving disconnected threads** — if the client disconnects mid-turn, the turn
   keeps running server-side and its result is persisted in full.
3. **Reconnect on refresh if active** — on reload, the client restores the turn by
   reading persisted state from the database, and resumes a "working" indicator if
   a run is still in flight.

## Explicit non-goal

**Live token replay on refresh.** We do not reattach a refreshed client to the
in-flight token stream. This mirrors the prior AI SDK implementation, which set
`resume: false` and healed the transcript from persisted messages rather than
resuming the live stream. Pillar 3 is therefore satisfied by **DB-heal**, not by a
shared event bus.

Consequence to accept: refreshing while a turn is still mid-flight shows the last
persisted state plus a "working" indicator; the completed reply appears once the
worker finishes and the client re-fetches. Tokens produced between the last
persisted state and the refresh are not replayed — they arrive whole on completion.

Adding true live resume later would require an addressable per-run event buffer
(Redis Streams, `resumable-stream`, or Postgres `LISTEN/NOTIFY`) plus a GET resume
route. Out of scope here; the DB-heal design does not preclude it.

## How the three pillars map onto our stack

| Pillar | Prior AI SDK mechanism | Our mechanism |
| --- | --- | --- |
| UI streaming | `createAgentUIStreamResponse` + `useChat` | `StreamSink` + owned event contract over `StreamingResponse` |
| Save disconnected threads | `consumeStream` keeps the serverless function consuming to completion | detached `asyncio` worker task with its own session, drained to completion |
| Reconnect on refresh | `healConversationTranscript` polls persisted messages with backoff | identical client heal loop, driven by an authoritative `agent_runs` "is active" query |

We are better positioned than the reference on pillar 3: the reference had no run
table and had to guess whether a turn was active. We have `agent_runs`, so "is a
turn still running?" is a real query, not a heuristic.

## Architecture

### Data flow for one turn

1. `POST /conversations/{id}/turns` validates the request and the one-active-run
   guard, creates a `pending` `agent_run`, and **commits it** (the run row must be
   durable before streaming so a refresh can find it).
2. The route constructs a `StreamSink`, registers a **detached worker task** that
   runs `execute_run(...)` with the sink, and returns a `StreamingResponse` that
   drains the sink as SSE.
3. The worker owns its **own** `AsyncSession` for the full turn, independent of the
   request. It runs `execute_run` to completion; `execute_run` owns the run
   lifecycle commits for running, terminal success, and terminal failure state.
4. The response generator forwards sink events until `done`/`close` (happy path) or
   until the client disconnects. Disconnect cancels **only** the draining; the
   worker is untouched and runs to completion + persistence.
5. On refresh, the client reads persisted messages + active-run status and heals.

### Transaction / session ownership (the load-bearing decision)

The request-scoped session dependency (`core/database.py:get_async_db_session`)
commits in its `else`/`finally` *after the handler returns*. With a
`StreamingResponse` the handler returns immediately and the body runs afterward, so
that dependency no longer brackets the work. It also gets torn down when the
connection drops — exactly when we want the worker to keep running. Therefore:

- **The worker creates and closes its own session** via
  `get_async_db_session_factory()` + `configure_async_db_session()`. It does not use
  the request session for turn work.
- Only the worker task touches that session. The sink drain is pure queue reads, so
  there is no cross-task use of one `AsyncSession`.

This composes with the current `execute_run` contract (see its docstring):

- **Success** commits final messages, usage, and terminal run status inside
  `execute_run`.
- **Failure** calls `fail_agent_run` + `db.commit()` inside `execute_run` before
  re-raising, then emits terminal stream events (`run.status`, `error`, `done`);
  the worker rolls back any residual state and logs.

Worker skeleton:

```python
async def _run_turn_worker(*, run_id, conversation_id, user_prompt, sink):
    session = get_async_db_session_factory()()
    await configure_async_db_session(session)
    try:
        await execute_run(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            user_prompt=user_prompt,
            sink=sink,
        )
    except Exception:
        await session.rollback()  # failure transition already committed by execute_run
        logger.exception("Detached agent turn failed", extra={"run_id": str(run_id)})
    finally:
        await session.close()
```

### Background task registry

A module-level singleton in `services/agents/runtime/` (e.g. `run_manager.py`) that
owns in-flight workers. `asyncio` holds only weak references to tasks, so without
this a detached turn can be garbage-collected when its spawning request ends.

Responsibilities:

- `spawn(run_id, coro) -> asyncio.Task` — create the task, store a strong reference
  keyed by `run_id`, attach a done-callback that removes it and logs any exception.
- `drain(timeout)` — await all in-flight workers up to a timeout, for graceful
  shutdown.
- (Optional) `is_running(run_id)` for introspection; the DB remains source of truth.

Wire `drain()` into the `lifespan` shutdown in `apps/api/main.py` **before**
`close_db_connections()`, so a normal deploy lets in-flight turns commit instead of
orphaning them.

### Concurrency guard (one active run per conversation)

Before creating a run, reject the request if the conversation already has a
non-terminal `agent_run`. This:

- prevents concurrent detached workers racing on `ConversationMessage.sequence`
  (which sidesteps the deferred sequence-uniqueness migration), and
- doubles as the "is a turn active?" signal that drives refresh-resume.

Return a structured 409 (existing `ConflictError`) carrying the active `run_id` so
the client can attach its heal loop to it.

## Routes

### `POST /conversations/{conversation_id}/turns`

- Body: `user_prompt`, optional `client_message_id` (idempotency; the
  `conversation_messages` unique partial index already supports it).
- Validates scope (reuse `validate_run_context` semantics), applies the active-run
  guard, creates + commits the `pending` run.
- Spawns the detached worker, returns `StreamingResponse(media_type="text/event-stream")`
  draining a `StreamSink`.
- The **first** emitted event is `run.status` carrying `run_id` (the sink envelope
  already includes it) so a reconnecting client knows what to poll.
- Note: the POST body means the browser cannot use native `EventSource`; the client
  uses `fetch` + `ReadableStream`. The prior frontend already did this.

### Read surface for refresh-resume

Either one combined conversation-fetch payload or two endpoints:

- Persisted transcript: `GET /conversations/{id}/messages` (ordered
  `ConversationMessage` rows; the existing read path if present).
- Active-run status: the conversation payload should expose whether a non-terminal
  `agent_run` exists and its `run_id`/`status`.

On mount the client: loads messages; if an active run exists, shows the working
state and re-fetches with backoff until the run goes terminal.

### `POST /agent-runs/{run_id}/cancel` (later)

Explicit, deliberate stop — distinct from a disconnect. Signals the worker to stop;
persists meaningful partial output (mirror `hasMeaningfulAssistantResponse`) rather
than discarding. Gotcha for implementation: `asyncio.CancelledError` is a
`BaseException`, not `Exception`, so it will not be caught by `execute_run`'s
`except Exception` — cancellation must be recorded deliberately, not relied upon to
flow through the failure path. Deferred until after the core streaming path lands —
note this is a *feature* deferral only; an abandoned run with no cancel endpoint is
still recovered by the reaper, so there is no durability gap in the meantime.

## Disconnect semantics

- Client disconnect → the `StreamingResponse` generator is cancelled → stop draining
  the sink. **Do not** cancel the worker task.
- The worker completes `execute_run`, persists messages + usage + terminal status,
  and commits. The sink keeps accepting `emit` calls (non-blocking) that no one
  reads; they are discarded when the task ends.
- `StreamSink.emit` must remain **non-blocking** for the producer (unbounded queue,
  or bounded with a drop policy + marker — never a blocking `put`). A blocked
  producer would let a dead client stall a turn that must complete. (This reverses
  the earlier "bounded queue for backpressure" idea, which conflicts with pillar 2.)

## Crash / restart durability (required — in this cut, not deferred)

A detached worker lives in one process's memory. Any hard stop — crash, OOM,
`SIGKILL`, a deploy that skips graceful drain, host failure — leaves its run stuck
non-terminal (`running`, or `pending` if it died before start) with no terminal
transition. The streaming response and the worker are both gone, so nothing in that
process will ever move the run. On refresh the client's heal loop sees an "active"
run that never completes and spins forever. This must be impossible by
construction, so the recovery mechanism ships **with** the streaming path.

We do not invent a new mechanism: we mirror the scheduled path, which already
survives dead workers via a **lease**. `agent_schedule_runs` carries
`claim_expires_at` and is reclaimed once the lease expires — and, importantly, the
scheduler reaps lazily **at claim time** (`claim_due_schedule_runs` skips a claimed
run only while `claim_expires_at > now`), not via a separate background loop.
Interactive `agent_runs` gets the analogous lease and reaps the same way.

### What lands now vs. with the worker

A dedicated scheduler/worker process for `agent_schedules` is coming. The
**periodic background sweep loop** belongs there, so we do not build a throwaway
reaper loop in the API lifespan. But crash durability cannot wait for it, so the
recovery *data and logic* land now and the gap is bridged by lazy on-read reaping:

- **Lands now (required):** the lease column + heartbeat, the `reap_abandoned_runs`
  service operation, **lazy reaping on every read path that consults "is a run
  active?"**, and a one-shot startup sweep.
- **Defers to the worker:** only the periodic sweep loop that catches runs *nobody
  is watching*.

This is safe because, for interactive turns, the cases where an orphan would cause
harm are all read paths that we reap synchronously (see below). The periodic loop is
pure hygiene for unobserved rows — and interactive turns, by definition, have an
observer.

### Defense in depth (ordered by detection latency)

1. **Graceful drain** — planned restarts: `drain()` in `lifespan` awaits in-flight
   workers so they commit. No orphan created in the first place.
2. **Lease + heartbeat** — the worker stamps `agent_runs.lease_expires_at = now +
   LEASE_TTL` when it starts and renews it on a heartbeat ticker. A dead worker stops
   renewing; its lease goes stale within one TTL regardless of crash cause.
3. **Lazy on-read reaping (the in-this-cut resolver)** — the two paths that ask
   "is a run active?" reap a lease-expired run *before* answering:
   - the **active-run guard** (new turn on a conversation): a stale `running`/`pending`
     run is failed first, so an orphan can never block future turns;
   - the **active-run status endpoint** (refresh heal loop): a stale run is failed
     before being reported, so the client heal loop can never spin forever.
   Both call `reap_abandoned_runs` scoped to the one run/conversation. This is the
   same lazy-at-claim-time pattern the scheduler already uses.
4. **Startup sweep** — a one-shot sweep on boot fails anything left non-terminal with
   an expired lease by a prior process (covers crash-then-restart).
5. **Hard deadline backstop** — `reap_abandoned_runs` also fails runs past
   `started_at + AGENT_RUN_MAX_DURATION_SECONDS` (default 1200, matching the prior
   `maxDuration`). Catches an alive-but-wedged worker (hung provider call, runaway
   tool loop) that is still leasing.
6. **Periodic sweep (with the worker, later)** — the same `reap_abandoned_runs` on an
   interval, for runs with no observer. Not required for interactive durability.

Together, items 1–5 guarantee a bounded time to terminal state for every run that
anyone observes, with no permanent user-visible orphan even before the worker
exists. Item 6 closes the residual hygiene gap for fire-and-forget rows.

### Schema (Alembic, core)

- `agent_runs.lease_expires_at TIMESTAMPTZ NULL` — the live lease.
- Optional `agent_runs.owner_instance_id TEXT NULL` — process id for diagnostics
  only; correctness comes from the lease, not ownership.
- Partial index `ix_agent_runs_lease_expiry` on `lease_expires_at`
  `WHERE deleted = false AND status IN ('pending','running')`, mirroring
  `ix_agent_schedule_runs_claim_expiry`, so the reaper scan is cheap.

### Heartbeat ticker

The worker spawns a sibling ticker task that, every `HEARTBEAT_INTERVAL_SECONDS`,
runs a **targeted update on its own short-lived session**
(`UPDATE agent_runs SET lease_expires_at = now() + :ttl WHERE id = :id`) and commits
immediately. It must not share the turn's session: the turn flushes-but-does-not-
commit until the end, so a heartbeat commit on that session would prematurely commit
partial state. The ticker is cancelled when the turn finishes.

False-positive safety: `LEASE_TTL` must be comfortably larger than the heartbeat
interval (default TTL 90s, interval 30s) to tolerate transient event-loop blocking.
A genuinely CPU-blocking tool would stall the loop and pause heartbeats, so such
tools must run in a threadpool; the generous TTL covers brief stalls.

### Reaper

A single `reap_abandoned_runs` service operation, multi-process safe the same way the
scheduler is — select expired candidates `with_for_update(skip_locked=True)` (or a
guarded conditional `UPDATE ... WHERE id = :id AND status IN ('pending','running')`,
which is atomic so concurrent callers each fail a row at most once). It transitions
matched runs to `failed` with `error_code = "run_abandoned"` and a message naming
the stale lease, so the client heal loop terminates on a real terminal state and can
offer retry. It must accept a scope — a single `run_id` (lazy on-read path) or a
batch over all expired runs (startup/periodic sweeps) — so the same logic backs every
caller.

Note: `pending -> failed` is not currently in `ALLOWED_TRANSITIONS`
(`services/agent_runs/domain.py` allows `pending -> {running, cancelled}`). Add it —
a run that never started can legitimately fail — so the ORM path and the reaper's
SQL agree on valid source states.

Where it runs (this cut): synchronously from the active-run guard and the active-run
status endpoint (single-run scope), plus a one-shot batch sweep at startup. **No
background loop in the API lifespan** — the periodic sweep lands with the
scheduler/worker process, calling the same `reap_abandoned_runs` batch on its tick.
Guarding the batch sweep with `pg_try_advisory_lock` is an optional efficiency
measure; the guarded UPDATE is what provides correctness across replicas.

### Settles a known race

If a worker completes at the same moment the reaper fails it (only possible under a
false-positive, i.e. too-tight TTL), the guarded transitions stay consistent: the
reaper's `WHERE status IN ('pending','running')` matches zero rows if the worker
already wrote `completed`; if the reaper wins, the worker's `complete_agent_run`
hits `can_transition(failed -> completed) == False` and the worker wrapper logs the
`ConflictError` without crashing. `complete_agent_run` should treat an
already-terminal run as a no-op to keep this quiet.

### Settings (core/settings)

`AGENT_RUN_LEASE_TTL_SECONDS=90`, `AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS=30`,
`AGENT_RUN_MAX_DURATION_SECONDS=1200`, `AGENT_RUN_REAPER_INTERVAL_SECONDS=30`,
`AGENT_RUN_PENDING_GRACE_SECONDS=60`. Validate `HEARTBEAT_INTERVAL < LEASE_TTL` in
settings so a misconfiguration cannot make every live run look abandoned.

## Frontend (heal loop)

Port the reference's `healConversationTranscript` shape:

- After error/stop/disconnect, poll persisted messages with backoff
  (`[250, 750, 1500]ms`) and swap the saved server transcript into local state once
  it lands.
- On mount with an active run, show "working" and poll until terminal, then load the
  final transcript.
- Consume our event contract (`run.status`, `message.start|delta|end`,
  `tool.call|result`, `error`, `done`) rather than the AI SDK UI-message protocol —
  we own both ends.

## Testing plan

- **Successful streamed turn** (route-level, `TestModel`): asserts ordered SSE
  events (`run.status` first, deltas present, `run.status`+`done` last), persisted
  messages, terminal `completed` run.
- **Disconnect mid-turn**: break the response iteration early; assert the worker
  still completes, the run ends `completed`, and messages persist. Needs a
  controllable/blocking model to create a disconnect window.
- **Model/build failure**: assert `run.status failed`, `error`, and terminal `done`
  SSE events plus a durable `failed` run (already committed by `execute_run`).
- **Active-run guard**: a second turn on a conversation with an in-flight run is
  rejected with the active `run_id`.
- **Task registry**: spawned tasks are strongly referenced, removed on completion,
  and `drain()` awaits them.
- **`reap_abandoned_runs` logic**: a run whose lease is past `now` is failed with
  `error_code = "run_abandoned"`; a `pending` run older than the grace with no lease
  is failed; a run past the hard deadline is failed; a fresh run with a live lease is
  left running. Covers both single-run and batch scope.
- **Lazy on-read reaping (the in-this-cut resolver)**: with a `running` run whose
  `lease_expires_at` is in the past, (a) the active-run status endpoint reports it
  terminal rather than active — the heal loop cannot spin; (b) a new turn on that
  conversation is admitted, not blocked by the stale run — the guard reaped it first.
- **Startup sweep**: a non-terminal run with an expired lease left by a prior process
  is failed on the first sweep after boot.
- **Heartbeat isolation**: the ticker renews the lease without committing the turn's
  in-progress (flushed, uncommitted) state.
- **Reaper/worker race**: failing an already-`completed` run is a no-op; completing
  an already-reaped run does not crash the worker.

## Build sequence

Backend items 1-5 are implemented for plain interactive turns. Item 6
(`useAgentStream` + frontend heal loop) and item 7 (explicit cancel) remain pending.

1. Schema: `agent_runs.lease_expires_at` (+ optional `owner_instance_id`) migration,
   partial lease index, and `pending -> failed` added to `ALLOWED_TRANSITIONS`.
2. Crash-durability core: lease stamping in `execute_run`/worker, heartbeat ticker
   (own session), the `reap_abandoned_runs` service op (single-run + batch scope),
   lazy on-read reaping wired into the active-run guard and status endpoint, a
   one-shot startup sweep, and the settings above. Landed alongside (or just ahead
   of) the route so no streaming path ever ships without recovery. No periodic
   lifespan loop — that lands with the scheduler/worker.
3. Background task registry + `drain()` (awaits workers and stops the reaper) wired
   into `lifespan`.
4. `POST /conversations/{id}/turns`: active-run guard, create+commit run, spawn
   worker (own session), `StreamingResponse` draining `StreamSink`.
5. Read surface: persisted messages + active-run status for refresh.
6. Frontend transport + heal loop against our event contract.
7. (Later) explicit cancel endpoint.

## Deferred (tracked, not in this cut)

- History windowing / token-budget on `load_message_history` (unbounded today).
- `ConversationMessage.sequence` uniqueness migration (mitigated by the active-run
  guard for now).
- True live stream resume (requires a shared event bus; non-goal above).
- Idempotent re-save of a turn via stable message IDs (relevant once approval
  resume re-saves the same turn).
- **Periodic reaper sweep loop** — lands with the `agent_schedules` scheduler/worker
  process, calling the `reap_abandoned_runs` batch on its tick. Deferred safely:
  lazy on-read reaping + the startup sweep already resolve every observed orphan, so
  this only adds hygiene for unobserved fire-and-forget rows.
