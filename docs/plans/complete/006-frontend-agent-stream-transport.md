# Plan 006: Add Frontend Agent API Contracts And Stream Transport

> **Executor instructions**: Follow this plan step by step. This slice adds the
> frontend data contracts and streaming transport that replace the old AI SDK
> client behavior. Do not build the chat route UI, approval controls, agent
> management forms, or schedule screens in this plan. When done, update the
> status row for this plan in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat fdf7220..HEAD -- apps/web/src/lib/api apps/web/src/features apps/web/src/app/router.tsx apps/web/src/config/navigation.ts apps/web/src/routes/home.tsx apps/api/services/agents/runtime/events.py apps/api/services/conversations/schemas.py apps/api/services/agents/schemas.py apps/api/services/agents/models/schemas.py apps/api/services/agent_runs/schemas.py docs/plans`
>
> If any in-scope file changed since this plan was written, compare the "Current
> State" excerpts below against the live code before proceeding. If the backend
> stream event names or response payloads changed, treat that as a STOP condition
> until this plan is refreshed.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: feature
- **Planned at**: commit `fdf7220`, 2026-07-01
- **Status**: TODO

## Why This Matters

The backend now exposes durable streamed turns over a custom SSE protocol, but
the Vite app has no typed client for agents, conversations, active runs, message
history, or approval resume. This plan creates the frontend runtime foundation:
REST API clients, typed stream event contracts, an SSE parser for `fetch` POST
responses, and a reducer/hook that turns backend events into stable UI state.

Keeping this transport slice separate from route UI makes the later chat and
approval plans smaller and easier to verify. It also gives the frontend a single
wire-format contract that mirrors `apps/api/services/agents/runtime/events.py`
instead of hand-rolling stream parsing inside components.

## Current State

Relevant backend contract:

```python
# apps/api/services/agents/runtime/events.py:19
EVENT_RUN_STATUS = "run.status"
EVENT_MESSAGE_START = "message.start"
EVENT_MESSAGE_DELTA = "message.delta"
EVENT_MESSAGE_END = "message.end"
EVENT_TOOL_CALL = "tool.call"
EVENT_TOOL_RESULT = "tool.result"
EVENT_TOOL_APPROVAL_REQUIRED = "tool.approval_required"
EVENT_CONVERSATION_CREATED = "conversation.created"
EVENT_CONVERSATION_UPDATED = "conversation.updated"
EVENT_ERROR = "error"
EVENT_DONE = "done"

STREAM_PROTOCOL_VERSION = "1"
STREAM_VERSION_HEADER = "X-Praxis-Stream-Version"
```

Relevant backend routes and payloads:

- `POST /api/v1/conversations/` creates a conversation and streams the first
  turn.
- `POST /api/v1/conversations/{conversation_id}/turns` streams another turn.
- `GET /api/v1/conversations/{conversation_id}/messages` returns persisted
  `ConversationMessageRead` rows.
- `GET /api/v1/conversations/{conversation_id}/active-run` returns
  `{ active_run: AgentRunRead | null }`.
- `POST /api/v1/agent-runs/{run_id}/resume` streams the resumed approval run.
- `GET /api/v1/agents/` and `GET /api/v1/models/catalog` already exist.

Current frontend API helper:

```ts
// apps/web/src/lib/api/client.ts:28
function buildRequest(
  path: string,
  { body, headers, method = "GET", query, ...init }: ApiRequestOptions = {}
): { url: URL; init: RequestInit } {
  ...
  const requestInit: RequestInit = {
    ...init,
    credentials: "include",
    headers: requestHeaders,
    method: normalizedMethod,
  }
  ...
}
```

`buildRequest` already centralizes credentials, workspace header, JSON content
type, and CSRF, but it is private. Streaming POSTs need the same behavior while
returning a raw `Response` instead of parsing JSON.

Current frontend route state:

- `apps/web/src/features` only contains `auth` and `workspaces`.
- `apps/web/src/config/navigation.ts` has an Agents item disabled.
- `apps/web/src/routes/home.tsx` shows placeholder cards for agents,
  schedules, and approvals.

## Commands You Will Need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Typecheck | `cd apps/web && pnpm typecheck` | exit 0, no TS errors |
| Lint | `cd apps/web && pnpm lint` | exit 0, no warnings |
| Build | `cd apps/web && pnpm build` | exit 0 |
| API contract smoke | `cd apps/api && uv run ruff check .` | exit 0; no backend edits should be needed |

There is currently no frontend unit-test script in `apps/web/package.json`.
Use typecheck/lint/build as the verification gate for this slice.

## Scope

**In scope**:

- `apps/web/src/lib/api/client.ts`
- New files under `apps/web/src/features/agents/`
- New files under `apps/web/src/features/models/`
- New files under `apps/web/src/features/conversations/`
- Optional small shared helpers under `apps/web/src/lib/`

**Out of scope**:

- Route registration in `apps/web/src/app/router.tsx`.
- Navigation changes in `apps/web/src/config/navigation.ts`.
- Chat message-list/composer UI components.
- Approval decision UI.
- Agent create/update forms.
- Backend route or schema changes.
- Any Vercel AI SDK dependency or message format.
- Installing `pydantic-ai-harness`.

## Git Workflow

- Suggested branch: `advisor/006-agent-stream-transport`.
- Commit style should match recent history, for example:
  `Web - Add Agent Stream Transport`.
- Do not push or open a PR unless the operator asks.

## Steps

### Step 1: Expose A Raw API Fetch Helper

Edit `apps/web/src/lib/api/client.ts`.

Add an exported helper for callers that need the raw `Response`, for example:

```ts
export async function apiFetch(path: string, options: ApiRequestOptions = {}) {
  const { url, init } = buildRequest(path, options)
  return fetch(url, init)
}
```

Keep `apiRequest<T>` implemented on top of `apiFetch` or the same private
`buildRequest` helper. Do not duplicate CSRF/workspace/credentials behavior in
stream code.

Make sure streaming callers can set `Accept: "text/event-stream"` without losing
the workspace or CSRF headers.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 2: Add Typed REST API Clients

Create frontend feature modules that mirror the current backend route shape.
Follow existing TanStack Query patterns such as
`apps/web/src/features/workspaces/api/list-workspaces.ts`.

Add at least:

```text
apps/web/src/features/agents/types.ts
apps/web/src/features/agents/api/list-agents.ts
apps/web/src/features/agents/api/create-agent.ts
apps/web/src/features/agents/api/update-agent.ts
apps/web/src/features/agents/api/delete-agent.ts

apps/web/src/features/models/types.ts
apps/web/src/features/models/api/list-model-catalog.ts

apps/web/src/features/conversations/types.ts
apps/web/src/features/conversations/api/list-conversations.ts
apps/web/src/features/conversations/api/create-conversation-stream.ts
apps/web/src/features/conversations/api/list-messages.ts
apps/web/src/features/conversations/api/get-active-run.ts
apps/web/src/features/conversations/api/create-turn-stream.ts
apps/web/src/features/conversations/api/resume-run-stream.ts
```

The stream API modules should return raw `Response` objects or delegate to the
stream hook from Step 4. REST modules should use `apiRequest<T>`.

Type names should line up with backend schemas:

- `Agent`, `AgentsListResponse`, `AgentCreateRequest`, `AgentUpdateRequest`
- `ModelCatalogResponse`, `ModelCatalogEntry`
- `Conversation`, `ConversationMessage`, `ConversationsListResponse`
- `AgentRun`, `ConversationActiveRunResponse`
- `AgentRunResumeRequest`, `AgentRunResumeDecision`

Keep `metadata_json` aliases in mind: backend serializes those fields as
`metadata` through Pydantic aliases. Type the frontend field as `metadata` unless
live responses show otherwise.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 3: Add Stream Protocol Types And SSE Parser

Create a protocol module, for example:

```text
apps/web/src/features/conversations/stream/protocol.ts
apps/web/src/features/conversations/stream/sse.ts
```

`protocol.ts` must define a discriminated union for backend event names:

```ts
type StreamEvent =
  | { event: "conversation.created"; data: StreamEnvelope & { conversation: Conversation } }
  | { event: "conversation.updated"; data: StreamEnvelope & { conversation: Conversation } }
  | { event: "run.status"; data: StreamEnvelope & { status: AgentRunStatus } }
  | { event: "message.start"; data: StreamEnvelope & { message_id: string; role: "assistant" } }
  | { event: "message.delta"; data: StreamEnvelope & { message_id: string; text: string } }
  | { event: "message.end"; data: StreamEnvelope & { message_id: string } }
  | { event: "tool.call"; data: StreamEnvelope & { tool_call_id: string; name: string; args: unknown } }
  | { event: "tool.result"; data: StreamEnvelope & { tool_call_id: string; name?: string | null; result: unknown } }
  | { event: "tool.approval_required"; data: StreamEnvelope & { tool_call_id: string; name: string; args: unknown } }
  | { event: "error"; data: StreamEnvelope & { code: string; message: string } }
  | { event: "done"; data: StreamEnvelope & { status: AgentRunStatus } }
```

Use `run_id`, `conversation_id`, and `seq` in a shared envelope. Include
`STREAM_PROTOCOL_VERSION = "1"` and `STREAM_VERSION_HEADER =
"X-Praxis-Stream-Version"` constants matching the backend.

`sse.ts` should parse `ReadableStream<Uint8Array>` frames from `fetch`, not
`EventSource`, because the turn endpoints are POST routes. Requirements:

- handle frames split across chunks;
- ignore comment frames such as `: keepalive`;
- support `event:` and one or more `data:` lines;
- JSON-parse `data`;
- throw a clear error for invalid JSON or missing event names;
- preserve event order.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 4: Add Stream Reducer And Hook

Create:

```text
apps/web/src/features/conversations/stream/reducer.ts
apps/web/src/features/conversations/stream/use-agent-stream.ts
```

The reducer should turn `StreamEvent` values into UI-ready state without React
side effects. Suggested state:

```ts
type AgentStreamState = {
  conversation: Conversation | null
  conversationId: string | null
  runId: string | null
  status: "idle" | "pending" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled"
  messages: ChatMessageDraft[]
  toolCalls: Record<string, ToolCallState>
  approvals: Record<string, ApprovalState>
  error: { code: string; message: string } | null
  done: boolean
  lastSeq: number
}
```

Reducer behavior:

- `conversation.created` and `conversation.updated` update `conversation`.
- `run.status` updates `runId`, `conversationId`, and `status`.
- `message.start` creates a draft assistant message with a stable message id.
- `message.delta` appends text to the matching draft.
- `message.end` marks the draft complete.
- `tool.call` records name/args and an in-flight status.
- `tool.result` records result and completed status.
- `tool.approval_required` records a pending approval and status
  `awaiting_approval`.
- `error` records the error and sets status `failed`.
- `done` sets `done = true` and terminal or suspended status.
- If `seq` does not increase, record a stream error rather than silently
  corrupting state.

The hook should:

- expose `sendFirstMessage`, `sendTurn`, and `resumeRun` or a small equivalent API;
- call the stream API endpoints with `apiFetch`;
- check the `X-Praxis-Stream-Version` response header and reject unsupported
  versions;
- consume the SSE parser and dispatch reducer events;
- support `AbortController` cleanup on component unmount;
- invalidate or refetch TanStack Query keys for conversations/messages/active run
  when a stream finishes.

Do not implement the refresh heal loop in this plan; expose the primitives needed
by Plan 007.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 5: Run The Frontend Gate

Run:

```bash
cd apps/web
pnpm typecheck
pnpm lint
pnpm build
```

Expected result: all commands exit 0.

## Test Plan

There is no configured frontend test runner. Use TypeScript as the primary
contract check for this slice.

Manual checks for the executor:

- Confirm `apiRequest<T>` still uses credentials, CSRF, and `X-Workspace`.
- Confirm stream POST helpers use the same header behavior through `apiFetch`.
- Confirm all stream event names exactly match `events.py`.
- Confirm no route UI imports the new hook yet; route wiring belongs to Plan 007.

## Done Criteria

- [ ] `apiFetch` or equivalent raw response helper exists and reuses shared API
      request construction.
- [ ] Typed REST API modules exist for agents, model catalog, conversations,
      messages, active run, turn streaming, and run resume.
- [ ] Stream protocol types mirror backend event names and version header.
- [ ] A POST-compatible SSE parser exists and ignores keepalive comments.
- [ ] A reducer and hook expose stream state/actions without route UI.
- [ ] `cd apps/web && pnpm typecheck` exits 0.
- [ ] `cd apps/web && pnpm lint` exits 0.
- [ ] `cd apps/web && pnpm build` exits 0.
- [ ] No backend source files are modified.
- [ ] `docs/plans/000_README.md` status row updated.

## STOP Conditions

Stop and report back if:

- Backend stream event names differ from the current `events.py` contract.
- The frontend needs a generated event-union pipeline before hand-written types
  can be accepted.
- The API client cannot support raw streaming responses without weakening CSRF,
  credentials, or workspace header behavior.
- A route UI change becomes necessary to verify this transport slice.
- Typecheck or build fails twice after reasonable fixes.

## Maintenance Notes

Plan 007 should consume these modules instead of parsing SSE directly in React
components. When the backend later generates the stream event union, replace the
hand-written protocol types here rather than creating a second contract.

Do not add `@ai-sdk/*` packages for this work. The architecture deliberately owns
the stream wire format and reducer.
