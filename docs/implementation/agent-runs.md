# Agent runs and conversation state

Read this before changing run completion, approval expiry, active context,
or conversation recovery. For the execution design, see
[agent runtime architecture](../architecture/agent-runtime.md) and
[streaming ownership](../architecture/agent-turn-streaming.md).
Backend paths are relative to `apps/api/`; frontend paths to `apps/web/`.

## Run lifecycle and context

The following contracts apply in this area:

- The agent runtime lives in `services/agents/runtime/`: SSE streaming with a
  versioned event protocol, run persistence, approval state
  (`DeferredToolRequests`/`DeferredToolResults`), capabilities, cooperative
  cancellation, and agent-to-agent delegation under `runtime/delegation/`.
  Terminal lifecycle transitions stamp a separate six-value `outcome` and
  bounded `completion_json` at the shared agent-run transition choke point;
  the transition refreshes under a row lock so the first terminal verdict is
  authoritative. Do not widen the six run statuses to represent completion
  verdicts. Required schedule completion contracts are copied into server-owned
  run metadata, inject their bounded criteria as a dedicated runtime system-
  instruction block (never into the visible user prompt), and
  mount the non-configurable internal `report_completion` tool only for that
  run; its pass/fail/missing-report verdict is resolved during successful
  finalisation. Once mounted, the tool is always available and auto-executed
  regardless of workspace tool settings, role write policy, or the run
  side-effect envelope. The first accepted report is authoritative; later
  report attempts fail without replacing its evidence.
  Optional schedule `max_requests` and `max_total_tokens` completion-contract
  budgets may only tighten the resolved model/platform `UsageLimits`; they
  never widen defaults. Approval continuations must restore the run's persisted
  cumulative Pydantic AI usage so those limits apply across the whole generic
  run, not once per resume segment. A tripped limit fails the run with outcome
  `budget_exhausted` and records only its allowlisted kind and limit in bounded
  completion evidence. Budget declarations remain within the largest integer
  that round-trips losslessly through JSON and the TypeScript schedule editor.
  Parked approvals expire through the generic jobs harness after
  `AGENT_RUN_APPROVAL_EXPIRY_DAYS` (default 7; 0 disables), which fails the run,
  clears durable approval state, and transactionally enqueues retryable staged
  write-content cleanup. Lease reaping also queues that cleanup before clearing
  a resumed run's approval state. Resume reserves the locked run as `running`
  before its SSE response begins. The conversation active-run read exposes the
  parked run's expiry deadline and always treats an existing active run as the
  latest run, so an older terminal outcome cannot replace a new stream.
- Direct conversation creation may include an `active_context` selection. It
  must be validated and persisted after the conversation is flushed but before
  its first run is created, so the initial turn resolves the selected context.
  Every active workspace member, including `read_only`, may select context;
  tool dispatch separately enforces whether that member may perform read or
  write effects.
- Context Group membership derives from `Workspace.is_personal`: shared
  workspace groups accept only connections owned by that workspace; personal
  workspace groups also accept the current actor's user-owned connections.
  Standalone resource selection deliberately retains actor-or-workspace
  visibility and must not reuse the narrower group-membership rule.

## Dispatch and streaming transactions

Every agent tool flows through the tool registry and the single dispatch
choke point (`runtime/dispatch.py`), which owns per-invocation audit,
policy/approval enforcement, run envelopes, and bounded tool results. Do
not execute tool logic around it. Interactive turns release their database
transaction before every model request and provider-backed helper call.
Completed tool calls commit before the next request; retrying or invalid tool
calls roll back their staged database work and reload runtime state before
model continuation. `RunTaskRegistry` bounds admitted turns per API
process and emits a transient `queued` stream status while a turn waits;
this value is not a persisted run lifecycle status. Stream sinks use a
bounded queue and detach slow consumers when that queue fills. Define stream
event names and payloads in `runtime/stream_protocol.py`, construct those
models at production emit sites, and run `make stream-protocol-export` after
any contract change. `make stream-protocol-check` verifies the checked-in
web test contract without writing files.

## Frontend stream and recovery

The following contracts apply in this area:

- SSE handling lives in `src/features/conversations/stream/`: a hand-written
  parser, a typed versioned event protocol, and a reducer. The parser throws
  on unknown event names, so a new server-side event breaks stale clients.
  Ship the client change first. Checked backend schema and sample artifacts
  live under `tests/features/conversations/stream/fixtures/`; regenerate them
  from the repository root with `make stream-protocol-export`. The transient
  `queued` run status means an
  interactive turn is waiting for API capacity; keep it in stream state and
  map it to persisted `pending` state wherever an `AgentRun` is required.
- `message-parts/timeline.ts` is the pure projection owner for persisted
  messages, live stream activity, approvals, and optimistic user messages.
  Keep `MessageList` focused on rendering and interaction wiring.
- The conversation active-run read also returns the latest run outcome so a
  terminal approval expiry can mark its unresolved tool row failed and show
  plain-language outcome copy without keeping the conversation blocked. It
  includes the active approval's expiry deadline; schedule one healing read at
  that deadline instead of polling throughout a days-long wait. An active run
  always takes precedence over an older expiry outcome. Pending and running
  heal reads use a four-second interval only while the tab has no connected
  stream for that conversation.

## Schedule completion controls

Schedule completion contracts remain opt-in behind the review step's Advanced
disclosure. Criteria are one plain-language check per line; do not expose the
underlying completion JSON or outcome codes in the form. Completion reports
use the shared compact `ToolResultCard` pattern; keep evidence collapsed by
default like other rich tool results. Optional request and total-token
budgets share the same Advanced disclosure and use the platform defaults when
blank. When the report requirement or a budget is removed, preserve unknown
completion-contract extension data through schedule edits. Run history names
the precise tripped budget when bounded evidence contains it. Keep persisted
budget values within JavaScript's safe-integer range so API-created schedules
round-trip without numeric loss.

## Context selection controls

The following contracts apply in this area:

- The conversation composer exposes active integration context for both new
  and existing conversations, including for read-only members.
  New-conversation selection stays local until it is submitted atomically with
  the first message.
- In shared workspaces, the Context Group picker hides resources from personal
  connections. Standalone context selection may still show those resources in
  conversations and schedules; do not reuse the group filter for that picker.

## Finalisation and interruption

Admission claims an opaque invocation UUID before queueing. The same identity
owns the lease and usage settlement. Renewal matches the run, workspace, user,
and current owner, and rejects an expired lease. Renewal cannot claim work.

Each continuation has a monotonic execution deadline derived from its durable
start. The default 1,200 seconds includes queue time. Approval waiting is
excluded, and reservation starts the resumed continuation clock once.
Specialists share the root's remaining deadline. Finalisation cleanup has its
own bounded wait outside the execution deadline.

`AGENT_MAX_DELEGATION_DEPTH` accepts zero to disable delegation or one for
direct specialists. The heartbeat interval must stay below the lease TTL.

Fresh permission reads precede model and tool requests. Failed reads cannot
authorise another request. Heartbeats retry database failures only within the
last confirmed lease window. An external request already accepted by a provider
can complete after local stopping; the runtime does not replay it automatically.

Family mutations lock the root before children in ID order. Cancellation,
permanent failure, and abandoned-run recovery settle non-terminal descendants
through `parent_run_id`, preserving completed children. Cleanup jobs are queued
before suspended metadata is cleared. A root with unfinished children records
blocked recovery instead of successful completion.

The committed run row controls final status, error events, and delegated
results. Completion, suspension, failure, and cancellation preserve an earlier
terminal verdict and its completion evidence. A suspension that loses this
race retains execution messages and usage but returns no actionable approval
requests. Delegation propagates approvals only when both the committed status
and deferred output describe an approval wait. If a resumed delegate becomes
unavailable, the locked child row still controls failure results. A completed
child remains completed, but unavailable-target output is not returned.

Finalisation has a three-second wait bound. Failure settlement has the same
bound. Cancellation during execution or failure settlement follows the same
interruption path and preserves the original cancellation signal.
During interruption, the execution task rolls back its own session
within a three-second bound, then starts isolated settlement. The isolated
task has three seconds to finish and three seconds to cancel and join.
Repeated cancellation does not restart these deadlines. Cleanup that resists
cancellation remains explicitly supervised and owns its session until it exits;
it cannot use the execution task's session. Python cancellation still
propagates. Process shutdown settles usage without recording a human stop.

Persistence precedes final stream events. A closed or detached stream does
not prevent settlement. Exhausted accounting persistence produces bounded
operational evidence containing the run, invocation, provider, model, and
usage counters. Total
database failure can leave accounting incomplete and does not trigger effect
replay.
