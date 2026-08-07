# Agent Turn Streaming & Disconnect-Safe Persistence

How interactive agent turns stream to the client while remaining durable when
the client goes away. The implementation lives in
`services/conversations/create_turn_stream.py`,
`services/agents/runtime/worker.py`, and
`services/agents/runtime/execute_run.py`.

## Guarantees (non-negotiable)

1. **UI streaming** — the client sees assistant text, tool calls, and run status
   live over SSE while a turn runs.
2. **Saving disconnected threads** — if the client disconnects mid-turn, the turn
   keeps running server-side and its result is persisted in full.
3. **Reconnect on refresh if active** — on reload, the client restores the turn by
   reading persisted state from the database, and resumes a "working" indicator if
   a run is still in flight.

## Explicit non-goal

**Live token replay on refresh.** A refreshed client is not reattached to the
in-flight token stream. Guarantee 3 is satisfied by **DB-heal**, not by a shared
event bus: refreshing while a turn is mid-flight shows the last persisted state
plus a "working" indicator; the completed reply appears once the worker finishes
and the client re-fetches. Tokens produced between the last persisted state and
the refresh are not replayed — they arrive whole on completion.

True live resume would require an addressable per-run event buffer (Redis
Streams or Postgres `LISTEN/NOTIFY`) plus a GET resume route. The DB-heal
design does not preclude adding it, but nothing today needs it.

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
connection drops — exactly when the worker must keep running. Therefore:

- **The worker creates and closes its own session** via
  `get_async_db_session_factory()` + `configure_async_db_session()`. It does not use
  the request session for turn work.
- Only the worker task touches that session. The sink drain is pure queue reads, so
  there is no cross-task use of one `AsyncSession`.

This composes with the `execute_run` contract:

- **Success** commits final messages, usage, and terminal run status inside
  `execute_run`.
- **Failure** calls `fail_agent_run` + `db.commit()` inside `execute_run` before
  re-raising, then emits terminal stream events (`run.status`, `error`, `done`);
  the worker rolls back any residual state and logs.

### Background task registry

A module-level singleton (`services/agents/runtime/run_manager.py`) owns
in-flight workers. `asyncio` holds only weak references to tasks, so without
this a detached turn could be garbage-collected when its spawning request ends.
It creates each task with a strong reference keyed by `run_id`, removes it on
completion via a done-callback that logs any exception, and exposes a
`drain(timeout)` used at `lifespan` shutdown — before `close_db_connections()` —
so a normal deploy lets in-flight turns commit instead of orphaning them.

### Concurrency guard (one active run per conversation)

Before creating a run, the route rejects the request if the conversation already
has a non-terminal `agent_run`. This prevents concurrent detached workers racing
on `ConversationMessage.sequence`, and doubles as the "is a turn active?" signal
that drives refresh-resume. The rejection is a structured 409 carrying the
active `run_id` so the client can attach its heal loop to it.

## Routes

### `POST /conversations/{conversation_id}/turns`

- Body: `user_prompt`, optional `client_message_id` (idempotency; backed by the
  `conversation_messages` unique partial index).
- Validates scope, applies the active-run guard, creates + commits the `pending`
  run.
- Spawns the detached worker and returns
  `StreamingResponse(media_type="text/event-stream")` draining a `StreamSink`.
- The **first** emitted event is `run.status` carrying `run_id` so a
  reconnecting client knows what to poll.
- The POST body means the browser cannot use native `EventSource`; the client
  uses `fetch` + `ReadableStream`.

### Read surface for refresh-resume

- Persisted transcript: `GET /conversations/{id}/messages`.
- Active-run status: the conversation payload exposes whether a non-terminal
  `agent_run` exists and its `run_id`/`status`.

On mount the client loads messages; if an active run exists, it shows the
working state and re-fetches with backoff until the run goes terminal.

### `POST /agent-runs/{run_id}/cancel`

Explicit, deliberate stop — distinct from a disconnect. Cancellation is
cooperative: the worker is signalled to stop and meaningful partial output is
persisted rather than discarded. Implementation gotcha that shaped it:
`asyncio.CancelledError` is a `BaseException`, not an `Exception`, so it does
not flow through `execute_run`'s failure path — cancellation is recorded
deliberately.

## Disconnect semantics

- Client disconnect → the `StreamingResponse` generator is cancelled → draining
  stops. The worker task is **not** cancelled.
- The worker completes `execute_run`, persists messages + usage + terminal status,
  and commits. The sink keeps accepting `emit` calls that no one reads; they are
  discarded when the task ends.
- `StreamSink.emit` is **non-blocking** for the producer. A blocked producer
  would let a dead client stall a turn that must complete, so backpressure is
  deliberately not applied here.

## Crash / restart durability

A detached worker lives in one process's memory. Any hard stop — crash, OOM,
`SIGKILL`, a deploy that skips graceful drain, host failure — would leave its run
stuck non-terminal with nothing in that process to move it, and a heal loop that
spins forever. The recovery mechanism makes that impossible by construction and
mirrors the scheduled path, which survives dead workers via a lease
(`agent_schedule_runs.claim_expires_at`, reaped lazily at claim time).
Interactive `agent_runs` carries the analogous lease and reaps the same way.

### Defense in depth (ordered by detection latency)

1. **Graceful drain** — planned restarts: `drain()` in `lifespan` awaits in-flight
   workers so they commit. No orphan created in the first place.
2. **Lease + heartbeat** — the worker stamps `agent_runs.lease_expires_at = now +
   LEASE_TTL` when it starts and renews it on a heartbeat ticker. A dead worker
   stops renewing; its lease goes stale within one TTL regardless of crash cause.
3. **Lazy on-read reaping** — the paths that ask "is a run active?" reap a
   lease-expired run *before* answering:
   - the **active-run guard** (new turn on a conversation): a stale
     `running`/`pending` run is failed first, so an orphan can never block
     future turns;
   - the **active-run status read** (refresh heal loop): a stale run is failed
     before being reported, so the heal loop can never spin forever.
   Both call `reap_abandoned_runs` scoped to the one run/conversation — the
   same lazy-at-claim-time pattern the scheduler uses.
4. **Startup sweep** — a one-shot sweep on boot fails anything left non-terminal
   with an expired lease by a prior process (covers crash-then-restart).
5. **Hard deadline backstop** — `reap_abandoned_runs` also fails runs past
   `started_at + AGENT_RUN_MAX_DURATION_SECONDS`. Catches an alive-but-wedged
   worker (hung provider call, runaway tool loop) that is still leasing.

Together these guarantee a bounded time to terminal state for every run that
anyone observes. A periodic background sweep would add only hygiene for
unobserved rows — interactive turns, by definition, have an observer — so none
runs in the API lifespan.

### Schema

- `agent_runs.lease_expires_at TIMESTAMPTZ NULL` — the live lease.
- `agent_runs.owner_instance_id TEXT NULL` — process id for diagnostics only;
  correctness comes from the lease, not ownership.
- Partial index `ix_agent_runs_lease_expiry` on `lease_expires_at`
  `WHERE deleted = false AND status IN ('pending','running')`, mirroring
  `ix_agent_schedule_runs_claim_expiry`, so the reaper scan is cheap.

### Heartbeat ticker

The worker spawns a sibling ticker task that, every
`AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS`, runs a targeted update on its own
short-lived session (`UPDATE agent_runs SET lease_expires_at = now() + :ttl
WHERE id = :id`) and commits immediately. It must not share the turn's session:
the turn flushes-but-does-not-commit until the end, so a heartbeat commit on
that session would prematurely commit partial state. The ticker is cancelled
when the turn finishes.

False-positive safety: the lease TTL is comfortably larger than the heartbeat
interval (default TTL 90s, interval 30s) to tolerate transient event-loop
blocking, and settings validation rejects `HEARTBEAT_INTERVAL >= LEASE_TTL` so
a misconfiguration cannot make every live run look abandoned. A genuinely
CPU-blocking tool would stall the loop and pause heartbeats, so such tools must
run in a threadpool.

### Reaper

One `reap_abandoned_runs` service operation (`services/agent_runs/`),
multi-process safe the same way the scheduler is: guarded conditional
transitions (`... WHERE id = :id AND status IN ('pending','running')`) so
concurrent callers each fail a row at most once. It transitions matched runs to
`failed` with `error_code = "run_abandoned"` and a message naming the stale
lease, so the client heal loop terminates on a real terminal state and can offer
retry. It accepts a scope — a single `run_id` (lazy on-read path) or a batch
over all expired runs (startup sweep) — so the same logic backs every caller.

### The completion/reaper race

If a worker completes at the same moment the reaper fails it (only possible
under a false-positive, i.e. too-tight TTL), the guarded transitions stay
consistent: the reaper's `WHERE status IN ('pending','running')` matches zero
rows if the worker already wrote `completed`; if the reaper wins, the worker's
`complete_agent_run` treats the already-terminal run as a no-op.

### Settings

`AGENT_RUN_LEASE_TTL_SECONDS`, `AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS`,
`AGENT_RUN_MAX_DURATION_SECONDS`, `AGENT_RUN_REAPER_INTERVAL_SECONDS`, and
`AGENT_RUN_PENDING_GRACE_SECONDS` in `core/settings/agents.py`. Settings
validation keeps the heartbeat interval below the lease TTL.

## Frontend (heal loop)

`src/features/conversations/conversation-heal-polling.ts`:

- After error/stop/disconnect, poll persisted messages with backoff and swap the
  saved server transcript into local state once it lands.
- On mount with an active run, show "working" and poll until terminal, then load
  the final transcript.
- Consume the owned event contract (`run.status`, `message.start|delta|end`,
  `tool.call|result`, `error`, `done`) documented in
  `docs/architecture/agent-runtime.md`.

## Test coverage

- **Successful streamed turn** (route-level, `TestModel`): ordered SSE events
  (`run.status` first, deltas present, `run.status`+`done` last), persisted
  messages, terminal `completed` run.
- **Disconnect mid-turn**: break the response iteration early; the worker still
  completes, the run ends `completed`, and messages persist.
- **Model/build failure**: `run.status failed`, `error`, and terminal `done`
  SSE events plus a durable `failed` run.
- **Active-run guard**: a second turn on a conversation with an in-flight run is
  rejected with the active `run_id`.
- **Task registry**: spawned tasks are strongly referenced, removed on
  completion, and `drain()` awaits them.
- **Reaper logic**: stale-lease, graceless-pending, and past-deadline runs are
  failed with `error_code = "run_abandoned"`; fresh runs with live leases are
  untouched. Covers single-run and batch scope.
- **Lazy on-read reaping**: with a `running` run whose lease has expired, the
  active-run status read reports it terminal (the heal loop cannot spin) and a
  new turn is admitted (the guard reaped it first).
- **Startup sweep**: a non-terminal run with an expired lease left by a prior
  process is failed on the first sweep after boot.
- **Heartbeat isolation**: the ticker renews the lease without committing the
  turn's in-progress (flushed, uncommitted) state.
- **Reaper/worker race**: failing an already-`completed` run is a no-op;
  completing an already-reaped run does not crash the worker.
