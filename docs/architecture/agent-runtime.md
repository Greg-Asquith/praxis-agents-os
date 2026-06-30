# Agent Runtime Architecture (Option C.2)

Status: **proposed / pending** — no runtime code exists yet. This document is the
target design, not a description of what is built.

## Decision

Run the agent runtime **in the Python API**. The frontend is a **Vite SPA** that
talks only to FastAPI: REST for data/auth, a custom **SSE protocol** for live agent
turns. We do **not** use the Vercel AI SDK on either side — neither its runtime nor
its UI-message wire format. We own the loop and the wire format.

Rationale (see the discussion that produced this): once the runtime moves into the
API, Next.js's server tier has nothing left to do for an authenticated operational
tool, so a server-side JS tier is pure overhead. One backend owns runtime,
providers, scheduling, auth, and audit — which also makes scheduled execution a
plain in-process function call instead of a cross-service poke.

## Process topology

Three long-lived processes, one database:

| Process            | Role                                                            |
| ------------------ | --------------------------------------------------------------- |
| `api` (FastAPI)    | REST + the SSE turn endpoint. Hosts interactive runs.           |
| `worker` (Python)  | Claims due schedule runs and executes them via the same runtime.|
| `web` (Vite SPA)   | Static assets. No server runtime. Consumes the API.             |

The **`agent_schedule_runs` table is the only interface between scheduling and
execution.** The scanner writes claimable rows; the worker pulls them. Nothing
calls an executor over HTTP. (`claim_due_schedule_runs` in
`services/agent_schedules/runs.py` already implements the claim half with
`FOR UPDATE SKIP LOCKED`.)

## The single execution path

Both entry points converge on one coroutine:

```python
# services/agents/runtime/execute_run.py
async def execute_run(db, *, conversation_id, sink: EventSink) -> RunResult:
    """Drive one agent turn to completion (or to an approval suspend).

    Persists ConversationMessages as it goes — independent of the sink.
    Emits live events to `sink` for streaming; scheduled runs pass a NullSink.
    """
```

- **Interactive turn:** the SSE route creates a `StreamSink`, launches
  `execute_run` as a task, and drains the sink to the HTTP response.
- **Scheduled turn:** the worker claims a run, opens (or reuses) the run's
  `conversation_id`, and calls `execute_run` with a `NullSink`, awaiting completion.

Persistence is inside `execute_run`, so a scheduled run with no live client still
produces the same `ConversationMessage` history a user can open later. The sink is
**only** for live streaming — a fan-out, never the source of truth.

### Approval / human-in-the-loop, durably

When a tool needs approval, `execute_run`:
1. emits `tool.approval_required`,
2. writes the suspended loop state to `conversations.agent_state` (JSONB),
3. sets run status `awaiting_approval` and **returns** (no long-lived hang).

Resume is a fresh entry: `POST /runs/{id}/resume` with the decision re-enters
`execute_run`, which rehydrates from `agent_state` and continues. This reuses the
existing `RUN_STATUS_AWAITING_APPROVAL` state and works identically for interactive
and scheduled runs (a scheduled run that suspends simply waits for a user to
approve later).

## Backend package layout

Follows existing conventions: thin routes, one operation per file, domain logic in
`services/`, reusable helpers in `services/<svc>/utils.py`.

```
apps/api/
  routes/
    agents/
      __init__.py              # composes the router only
      stream_turn.py           # POST /conversations/{id}/turns -> text/event-stream
      resume_run.py            # POST /runs/{id}/resume
  services/
    agents/
      __init__.py              # re-exports operations
      runtime/
        execute_run.py         # the core loop (above)
        sinks.py               # EventSink, StreamSink, NullSink
        events.py              # event dataclasses (server side of the wire protocol)
        loop.py                # Pydantic AI agent construction + step driver
        tools/
          contract.py          # define_tool(): zod-equivalent IO validation + approval mode
          registry.py          # tool catalog + per-turn active-tool gating
        persistence.py         # ConversationMessage read/write, stable ids, abort-safe saves
      models/
        registry.py            # model catalog (single source of truth, Python-owned)
        factory.py             # provider/model -> client instance
        resolution.py          # per-use-case + per-workspace override resolution
  workers/
    agent_runner.py            # entrypoint: scan -> claim -> execute_run -> mark complete
```

### Provider/model abstraction

- **One catalog, Python-owned.** A registry module plus per-workspace overrides in a
  new `ai_model_configs` table. This fixes the old system's wart of duplicating the
  model catalog across Python and TS — the SPA reads model metadata from the API and
  never re-encodes it.
- **Library:** build the loop on **Pydantic AI** (typed tools, structured output,
  streaming, multi-provider — fits the existing Pydantic stack). If provider breadth
  ever outgrows it, drop **LiteLLM** in as the provider layer underneath the factory
  without touching `execute_run`. Keep `execute_run` library-agnostic so this stays
  swappable.
- Infra-provider settings already live in `core/settings/providers.py`; LLM model
  config is a separate, new concern (model catalog + credentials), not folded into
  that mixin.

## The SSE wire protocol (custom, owned by us)

One streaming POST per turn (mirrors how AI SDK's transport works under the hood,
without the AI SDK): the request carries the user message; the response is
`text/event-stream`. The client reads `response.body` — not `EventSource`, so POST
works.

Each event: SSE `event:` = type, `data:` = JSON carrying `run_id`,
`conversation_id`, and a monotonic `seq`.

| `event:`                 | `data` payload                                  |
| ------------------------ | ----------------------------------------------- |
| `run.status`             | `{ status }` running / awaiting_approval / done |
| `message.start`          | `{ message_id, role }`                          |
| `message.delta`          | `{ message_id, text }` (token chunk)            |
| `message.end`            | `{ message_id }`                                |
| `tool.call`              | `{ tool_call_id, name, args }`                  |
| `tool.result`            | `{ tool_call_id, result }`                      |
| `tool.approval_required` | `{ tool_call_id, name, args }`                  |
| `step`                   | `{ index }` agent-loop step boundary            |
| `error`                  | `{ code, message }`                             |
| `done`                   | `{}` terminal — client closes                   |

Version the protocol from day one (`X-Praxis-Stream-Version`) so client/runtime can
evolve independently. Keep the event set small; this table is the contract.

## Frontend (Vite SPA)

Replaces the Next scaffold in `apps/web`. React + TypeScript + Tailwind, App-Router
conventions dropped in favor of a client router.

```
apps/web/
  index.html
  vite.config.ts
  src/
    main.tsx
    lib/
      api/client.ts            # fetch wrapper, credentials: 'include', typed
      agent/
        protocol.ts            # event types — mirrors backend events.py
        useAgentStream.ts      # POST + ReadableStream reader -> reducer
        reducer.ts             # events -> { messages, toolCalls, status }
    components/chat/           # message list, composer, tool-call cards, approval frame
    routes/                    # dashboard, agents, conversations, schedules
```

- **`useAgentStream`** does the work the AI SDK's `useChat` did: POST the turn, read
  the SSE body, fold events into render state, expose `sendMessage`,
  `approve(toolCallId)`, `messages`, `status`.
- **Server state:** TanStack Query for REST. **Routing:** TanStack Router or
  react-router.
- **`protocol.ts` mirrors `events.py`.** Generate it from the backend (e.g. an
  OpenAPI/JSON-schema export of the event union) rather than hand-syncing, so the two
  ends can't drift.

### Auth / CORS / cookies (do not loosen — add explicit local config)

The SPA is a separate origin from the API in dev. Per repo policy we never relax
CORS/cookie/CSRF for convenience:

- **Production:** serve SPA and API **same-site** behind one domain (reverse proxy:
  `/` → static SPA, `/api` → FastAPI) so session cookies stay first-party. No CORS
  needed.
- **Local dev:** explicit allowed origin for the Vite dev server + `SameSite=Lax`/
  credentialed fetch, configured in settings — not a wildcard.

## Build sequence

1. Model registry + `ai_model_configs` + factory/resolution (Python).
2. Runtime core: `execute_run`, `EventSink`/`StreamSink`/`NullSink`, tool contract,
   Pydantic AI loop. Persist to existing `ConversationMessage`.
3. SSE turn endpoint (`stream_turn.py`) — interactive path end to end.
4. `workers/agent_runner.py` — scan/claim via existing `runs.py`, call `execute_run`
   with `NullSink`.
5. Approval suspend/resume (`resume_run.py` + `agent_state` rehydrate).
6. Replace `apps/web` with the Vite SPA; build `useAgentStream` + chat UI.

## What this explicitly drops vs the old system

- The Vercel AI SDK (runtime and UI). We rebuild the loop (Pydantic AI) and the
  chat-stream client (`useAgentStream`) ourselves — the accepted cost of C.2.
- The Next.js server tier and its internal `schedule-runs/.../execute` route.
- Any duplication of the model catalog across languages.
```
