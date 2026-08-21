# Agent Runtime Architecture

Status: **implemented end to end**. The backend has the model registry,
`agent_runs`, the Pydantic AI runtime core, event sinks, durable streamed
interactive turns, scheduled-run worker execution, approval suspend/resume, and
runtime delegation tools for allowlisted specialist agents. The Vite app has
typed conversation transport, a real chat surface, agent management, approval
controls, and delegated tool-call rendering. This note describes the runtime as
it runs today and the design rules that keep it that shape.

## Decision

Run the agent runtime **in the Python API**. The frontend is a **Vite SPA** that
talks only to FastAPI: REST for data/auth, a custom **SSE protocol** for live agent
turns. We do **not** use the Vercel AI SDK on either side — neither its runtime nor
its UI-message wire format. We own the loop and the wire format.

Rationale: with the runtime in the API, a server-side JS tier would have nothing
left to do for an authenticated operational tool — it would be pure overhead.
One backend owns runtime, providers, scheduling, auth, and audit, which also
makes scheduled execution a plain in-process function call instead of a
cross-service poke.

## Process topology

Three long-lived processes, one database:

| Process            | Role                                                            |
| ------------------ | --------------------------------------------------------------- |
| `api` (FastAPI)    | REST + the SSE turn/resume endpoints. Hosts interactive runs.   |
| `worker` (Python)  | Claims due schedule runs and executes them via the same runtime.|
| `web` (Vite SPA)   | Static assets. No server runtime. Consumes the API.             |

The **`agent_schedule_runs` table is the only interface between scheduling and
execution handoff.** The scanner writes claimable rows; the worker pulls them.
Nothing calls an executor over HTTP. (`claim_due_schedule_runs` in
`services/agent_schedules/runs.py` implements the claim half with
`FOR UPDATE SKIP LOCKED`.)

The worker process is wired into local Compose and `make dev` through
`workers.main`, which supervises the scheduled-agent runner and the generic
jobs runner. It shares the API image, database, provider settings, and storage
mount so scheduled runs use the same execution path as interactive turns.

## The single execution path

Interactive, scheduled, resumed, and delegated execution converge on one
coroutine:

```python
# services/agents/runtime/execute_run.py
async def execute_run(
    db,
    *,
    conversation_id,
    run_id,
    user_prompt,
    sink: EventSink | None = None,
    message_history=None,
    deferred_tool_results=None,
    usage=None,
) -> ExecuteRunResult:
    """Drive one agent turn to completion or approval suspension.

    Persists ConversationMessages and run lifecycle state independent of the sink.
    Emits live events to `sink` for streaming; scheduled runs pass a NullSink.
    """
```

- **Interactive turn:** the conversation route creates a pending `agent_run`,
  spawns a detached turn worker with its own database session and lease heartbeat,
  and drains a `StreamSink` to the HTTP response.
- **Scheduled turn:** the worker claims a run, opens (or reuses) the run's
  `conversation_id`, and calls `execute_run` with a `NullSink`, awaiting completion.
- **Approval resume:** `POST /agent-runs/{id}/resume` rehydrates the suspended
  message history and deferred tool requests, then re-enters `execute_run`.
- **Delegated child run:** `delegate_to_agent` creates an `agent_call`
  conversation and delegated child `agent_run`, then calls `execute_run` with an
  isolated session and shared usage accounting.

Persistence is inside `execute_run`, so a scheduled run with no live client will
produce the same `ConversationMessage` history a user can open later. Successful
runs commit final messages, usage, and terminal status at completion; failures
commit terminal run state before re-raising. The sink is **only** for live
streaming — a fan-out, never the source of truth.

### Conversation ownership and delegation

A live conversation has one primary agent. The UI should not expose a per-message
agent selector in the composer; that adds ambiguity about who owns the thread,
which tools are available, and how prior assistant messages should be interpreted.

Use `conversations.active_agent_id` as the canonical primary agent for the thread.
Users choose an agent when creating a conversation, or change the conversation's
primary agent through an explicit conversation setting outside the live turn flow.
`POST /conversations/{id}/turns` uses that primary agent; it does not accept an
arbitrary `agent_id` for each message.

Specialist agents are reached through Pydantic AI multi-agent delegation, not by
turning the chat into a multi-speaker selector. The primary agent receives
delegation tools for its `allowed_agent_ids`. A delegate agent can run internally
and return a result to the primary agent, which remains responsible for the
user-visible response.

Persist delegation as run/subrun metadata and stream it as tool activity where
useful. By default, `ConversationMessage` should contain the user-visible primary
agent response, while delegate transcripts/results remain available for audit,
debugging, and future replay without cluttering the main conversation.
Delegated child conversations use `source="agent_call"` and are excluded from the
default conversation list; callers can still fetch them directly by id from run
metadata or a delegation tool-result link.

### Run identity

The generic `agent_runs` table (`models/agent_run.py`) is the universal run
identity for both interactive and scheduled turns. `agent_schedule_runs`
requires `schedule_id` and `scheduled_for`, so it cannot be that identity; it is
the scheduler claim table and links to `agent_runs` once a worker starts
execution.

`agent_runs` keeps approval, resume, errors, usage, audit correlation, and stream
replay under one durable execution identifier, with `trigger` distinguishing
interactive from scheduled runs and hot usage columns alongside the full
`usage_json`.

### Streaming session ownership

Do not run `execute_run` on the request-scoped SQLAlchemy session after returning
the `StreamingResponse`. The current middleware commits or rolls back the
request session once the response object is produced, while the stream body may
still be executing.

The SSE endpoint should either:

- run the agent inside the streaming generator and own the session until the
  generator exits, or
- create a background task that opens its own database session and communicates
  with the stream through `StreamSink`.

In both cases, persistence must be abort-safe: user message, assistant deltas,
tool calls, terminal errors, and approval suspension state should commit at clear
boundaries rather than waiting for a long stream to finish.

Interactive turns return the runtime database transaction before each model
request and provider-backed helper call. Successful tools commit at the dispatch
boundary. Retrying tools and tools with invalid output roll back staged database
work and reload the runtime state before model continuation.

### Approval / human-in-the-loop, durably

Use Pydantic AI's deferred-tool flow rather than inventing a parallel approval
protocol. Tools that always need approval can use `requires_approval=True`; tools
that need conditional approval should raise `ApprovalRequired(...)`.

When a tool needs approval, Pydantic AI returns `DeferredToolRequests`. At that
point `execute_run`:

1. emits `tool.approval_required`,
2. writes the Pydantic AI message history plus the pending deferred tool requests
   to `agent_runs.metadata["approval_state"]` as a versioned JSON snapshot,
3. sets run status `awaiting_approval` and **returns** (no long-lived hang).

Resume is a fresh entry: `POST /agent-runs/{id}/resume` with the decision re-enters
`execute_run`, which rehydrates from the run's approval-state snapshot and continues
by passing `message_history` and `DeferredToolResults` back to Pydantic AI. Approved
decisions may include `override_args`; these are mapped to
`ToolApproved(override_args=...)` so a user can correct a proposed tool call before
execution. Denials should use `ToolDenied` so the model receives a typed denial
result. This reuses the existing `RUN_STATUS_AWAITING_APPROVAL` state for scheduled
runs and the generic run status for interactive runs.

Only persist JSON-serializable message/state data that we know how to rehydrate.
Do not store opaque Pydantic AI runtime objects in run metadata.

## Backend package layout

Follows existing conventions: thin routes, one operation per file, domain logic in
`services/`, reusable helpers in `services/<svc>/utils.py`.

```
apps/api/
  routes/
    agents/
      list_agents.py           # GET /agents
      create_agent.py          # POST /agents
      get_agent.py             # GET /agents/{id}
      update_agent.py          # PATCH /agents/{id}
      delete_agent.py          # DELETE /agents/{id}
    conversations/
      list_conversations.py    # GET /conversations
      get_conversation.py      # GET /conversations/{id}
      create_conversation.py   # POST /conversations -> text/event-stream
      create_turn.py           # POST /conversations/{id}/turns -> text/event-stream
      list_messages.py         # GET /conversations/{id}/messages
      get_active_run.py        # GET /conversations/{id}/active-run
    agent_runs/
      get_approval_state.py    # GET /agent-runs/{id}/approval-state
      resume_run.py            # POST /agent-runs/{id}/resume
  services/
    agents/
      __init__.py              # re-exports operations
      list_agents.py           # workspace-scoped agent listing
      create_agent.py          # create workspace agent config
      get_agent.py             # read workspace agent config
      update_agent.py          # update workspace agent config
      delete_agent.py          # soft-delete workspace agent config
      schemas.py               # public agent config contracts
      utils.py                 # agent config validation helpers
      runtime/
        execute_run.py         # the core execution path (above)
        sinks.py               # EventSink, StreamSink, NullSink
        streaming.py           # POST-compatible SSE frame parsing/draining helpers
        events.py              # server side of the stream protocol
        approval_events.py     # approval-required + deferred-tool resume event replay
        approval_state.py      # durable approval-state metadata serialization
        capabilities.py        # Pydantic AI AgentCapability assembly
        context.py             # RuntimeDeps exposed to tools and capabilities
        delegation.py          # allowlisted agent-as-tool delegation
        heartbeat.py           # lease renewal for detached/inline long runs
        load_context.py        # DB row loading for run, conversation, agent, actor
        loop.py                # Pydantic AI agent construction + event driver
        run_manager.py         # strong references for detached turn/resume tasks
        run_persistence.py     # run lifecycle/message/usage persistence
        worker.py              # detached interactive turn and resume workers
        tools/
          contract.py          # define_tool(): zod-equivalent IO validation + approval mode
          registry.py          # tool catalog + per-turn active-tool gating
        persistence.py         # ConversationMessage read/write, stable ids, abort-safe saves
      models/
        registry.py            # model catalog (single source of truth, Python-owned)
        factory.py             # provider/model -> Pydantic AI Model instance
        resolution.py          # per-agent resolution + the naming use case
        utils.py               # provider credential seam
  workers/
    main.py                    # worker entrypoint: supervises both runner loops
    agent_runner.py            # scan -> claim -> execute_run -> mark complete
    job_runner.py              # generic jobs queue loop
```

### Provider/model abstraction

- **One catalog, Python-owned.** A hard-coded registry module (`models/registry.py`)
  is the single source of truth — no database table and no per-workspace overrides.
  Model selection lives on the agent row (`model_provider`/`model`/`model_settings`),
  so delegating to an agent automatically inherits its model. Non-agent utility
  cases still resolve through the same catalog/factory seam: conversation naming
  uses settings constants, while native helper tools can take provider/model as
  runtime tool arguments. The SPA reads model metadata from the API and never
  re-encodes it, so the catalog cannot drift between languages.
- **Library:** build the loop on **Pydantic AI** (typed tools, structured output,
  streaming, multi-provider — fits the existing Pydantic stack). If provider breadth
  ever outgrows it, drop **LiteLLM** in as the provider layer underneath the factory
  without touching `execute_run`. Keep `execute_run` library-agnostic so this stays
  swappable.
- Infra-provider settings already live in `core/settings/providers.py`; LLM model
  config is a separate, new concern (model catalog + credentials), not folded into
  that mixin.

### Pydantic AI usage

Use Pydantic AI as the runtime foundation, not merely as a provider wrapper:

- Build agents with explicit `name=` values so traces and audit logs are
  distinguishable once multiple agents exist.
- Use `deps_type=RuntimeDeps` and `RunContext[RuntimeDeps]` to pass workspace,
  user, conversation, run, tool policy, sink, and service handles into tools and
  dynamic instructions.
- Model specialist-agent calls as Pydantic AI delegation tools. The primary agent
  keeps control of the user-facing turn; delegates return results to it.
- Prefer Pydantic AI's native run APIs: `run_stream_events()` or
  `event_stream_handler=` for live event mapping, `message_history=` for
  conversation continuation, and `iter()` only when the runtime genuinely needs
  step-by-step loop control beyond the event stream.
- Use Pydantic models for structured tool arguments, tool returns, and any
  machine-consumed agent output.
- Treat `Hooks`, `ProcessHistory`, `ToolSearch`, `Thinking`, `WebSearch`,
  `WebFetch`, `MCP`, and `HandleDeferredToolCalls` as Pydantic AI
  `AgentCapability` instances passed through `Agent(..., capabilities=[...])`.
  The assembly seam lives in `runtime/capabilities.py`; only the baseline
  capability set is wired today.
- Use `Hooks` for audit emission, stream fan-out, model-request policy,
  provider-call observability, and pre-tool validation. This keeps cross-cutting
  concerns out of route handlers and individual tools.
- Use `ProcessHistory` or a `before_model_request` hook for context trimming,
  redaction, and old-message summarization. The runtime registers a per-turn
  `ProcessHistory` closure that trims prior stored history at stable, chunked
  user-turn watermarks. When a trim first reaches a persisted message-id
  watermark, the completed turn enqueues an idempotent
  `conversations.summarize_history` job. The job frames the dropped span as
  untrusted data, folds the prior watermark summary when advancing, and stores
  one bounded automatic summary for the next turn. The closure injects at most
  that exact stored summary, so the prefix stays byte-stable between watermark
  advances. Catalog `context_window` and calibrated `chars_per_token` values can
  advance trimming one additional chunk under token pressure; Azure deployments
  use explicit context-window and estimator settings because their deployment
  names are customer-defined. Turn-count trimming remains the floor.
  `load_message_history` retains its byte-identical persisted-history contract,
  and summary watermark ids travel beside the provider-visible messages rather
  than inside them. Before either the runtime model or history-summary model
  receives reconstructed history, a model-boundary sanitizer removes legacy
  `integration_resource_id` and `connection_id` keys from integration tool
  calls/results, including Code Mode nested metadata. It does not rewrite
  stored conversation rows, replay payloads, audit data, or arbitrary user and
  non-integration content.
- Use built-in capabilities such as `Thinking`, `WebSearch`, `WebFetch`, and
  `MCP` when they fit. For every optional or specialist capability, explicitly
  consider `defer_loading=True` so long-tail instructions and schemas do not bloat
  normal turns.
- Use tool-level `defer_loading=True` or tool search for large flat catalogs.
  Keep common, high-signal tools eagerly available.
- Use Pydantic AI `TestModel` for deterministic runtime tests and `FunctionModel`
  for exact approval, retry, and failure cases. Use `capture_run_messages()` for
  targeted debugging. If Logfire is enabled, instrument Pydantic AI, but treat
  traces as diagnostic data and avoid full HTTP payload capture except for
  targeted debugging.

Code-mode orchestration is described in [`code-mode.md`](code-mode.md): it
builds on raw `pydantic-monty`, not Pydantic AI Harness, which remains a
design reference only.

## The SSE wire protocol (custom, owned by us)

One streaming POST per turn: the request carries the user message; the response
is `text/event-stream`. The client reads `response.body` — not `EventSource`, so
POST works.

Each event: SSE `event:` = type, `data:` = JSON carrying `run_id`,
`conversation_id`, and a monotonic `seq`.

`services/agents/runtime/stream_protocol.py` is the authoritative contract for
event names, payload fields, enum values, and representative frames. Its export
script writes the checked-in browser contract to
`apps/web/tests/features/conversations/stream/fixtures/`. The backend check
compares those artifacts with the models. The frontend check verifies that the
handwritten parser accepts representative, minimal, nullable, and nested
contract forms and rejects missing required fields. Run
`make stream-protocol-export` after changing the contract.

The payload models cover conversation creation and updates, run status,
assistant text and thinking messages, tool calls and results, approval details,
Code Mode workflow state, errors, and terminal completion. Approval payloads
include replay arguments, nested workflow parents, delegated-run context, and
untrusted-content provenance when those values apply. `tool.call.args` and
`tool.result.result` remain JSON values because individual tool contracts own
their shapes.

The protocol is versioned so client and runtime can evolve independently. The
backend sends `X-Praxis-Stream-Version: 1` on turn streams and exposes that
header through cross-origin resource sharing (CORS) for the Vite client.

## Frontend (Vite SPA)

`apps/web` is a Vite React SPA with TanStack Router and TanStack Query. The
runtime-facing frontend lives mostly under `src/features/conversations` and
`src/features/agents`.

The live conversation surface shows the primary conversation agent, but not an
inline agent picker. Agent selection belongs in conversation creation and
conversation settings. Delegation to specialist agents appears as tool activity
and child transcript links, not as a second assistant competing in the composer.

```
apps/web/src/features/
  conversations/
    api/                       # typed REST/SSE calls for conversations and runs
    stream/
      protocol.ts              # typed event facade checked against backend schema
      sse.ts                   # POST-compatible SSE parser
      reducer.ts               # stream events -> render state
      use-agent-stream.ts      # create, turn, and resume stream orchestration
    components/                # messages, composer, tool/delegation rows, approvals
    routes/                    # conversation list/detail/new conversation
  agents/
    api/                       # typed agent CRUD calls
    components/                # forms, runtime tools, delegation allowlist
    routes/                    # agents list/detail/new agent
```

- **`useAgentStream`** owns the stream lifecycle: POST a conversation
  create/turn/resume request, read the SSE body, fold events into render state,
  and expose stream state/actions to the route shell.
- **Server state:** TanStack Query for REST. **Routing:** the existing TanStack
  Router setup.
- **The backend owns the stream contract.** Regenerate the checked-in schema
  and samples after changing a payload model. `make check` rejects stale
  artifacts. `pnpm check` verifies the handwritten parser against the
  checked-in contract but does not load Python models.

### Auth / CORS / cookies (do not loosen — add explicit local config)

The SPA is a separate origin from the API in dev. Per repo policy we never relax
CORS/cookie/CSRF for convenience:

- **Production:** serve SPA and API **same-site** behind one domain (reverse proxy:
  `/` → static SPA, `/api` → FastAPI) so session cookies stay first-party. No CORS
  needed.
- **Local dev:** explicit allowed origin for the Vite dev server + `SameSite=Lax`/
  credentialed fetch, configured in settings — not a wildcard.

## Current implementation

The production runtime includes scheduled and interactive runs, approval
pause/resume, cooperative cancellation, bounded tool results, single-level
delegation, provider retry and usage limits, history trimming and summaries,
skills, files, knowledge retrieval, memory, audited tool dispatch, and opt-in
OpenTelemetry/Logfire instrumentation. The web app exposes the corresponding
conversation, approval, agent, schedule, tool-catalog, and audit surfaces.

Code-mode orchestration is described in [`code-mode.md`](code-mode.md): it
builds on raw `pydantic-monty`, not Pydantic AI Harness, which remains a
design reference only.
