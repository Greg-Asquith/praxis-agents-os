# Agent runs and conversation state

Read this before changing run completion, approval expiry, active context,
or conversation recovery. For the execution design, see
[agent runtime architecture](../architecture/agent-runtime.md) and
[streaming ownership](../architecture/agent-turn-streaming.md).
Backend paths are relative to `apps/api/`; frontend paths to `apps/web/`.

## Skill history

Assigned skills use deferred instruction capabilities with `skill-UUID` IDs.
Migration `core_0052` converts historical `skill:UUID` IDs in typed capability-load
calls in conversation messages and saved approval histories, including delegated
runs. It preserves call IDs, message metadata, decisions, and interpreter state.
Ordinary tool results and prompt content are unchanged and cannot restore a
loaded skill. Reading a skill document requires its assigned capability to be
loaded. Runtime history loading performs no compatibility conversion.

Stop old API and worker processes before applying this migration, then start
the upgraded processes after it succeeds. A restored pre-upgrade database must
run migrations before use. Downgrading the migration restores the historical
prefix and requires the same stopped-process boundary.

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
  never widen defaults. Delegated starts and continuations copy the actual
  parent limits and intersect them with the child's limits. Each non-null
  ceiling is an absolute cumulative limit, including child `max_steps`; it
  does not allocate a fresh allowance to each specialist. Approval continuations
  must restore the run's persisted
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

Recovery reads the active run first, then its current approval projection and
messages through workspace-scoped query caches. It publishes the recovered
status after those reads succeed and their approval revisions match. A revision
change between reads retries the sequence. Concurrent refreshes share the
in-flight query. Disconnected stream state yields to durable approvals and terminal
outcomes; a connected stream retains precedence.

Network failures, HTTP 429, and server errors retain two bounded query retries.
After those retries exhaust, recovery waits four, eight, 16, then at most 30
seconds between read sequences. A successful sequence resets the delay. The
active-run query owns retries, so dependent reads do not multiply them. Session,
access, and missing-resource errors stop automatic recovery. Intentional
cancellation stops the request. Queries respect tab visibility and online state.
Healthy parked approvals wait for their expiry deadline, with conversation-local
focus and reconnect refresh even when expiry is disabled. Global query defaults
remain unchanged.

The route mounts before status and transcript reads, so an initial failure can
recover on the page. The transcript retains its last known content during an
outage and exposes a **Retry** action. Recovery never resends a turn or an approval submission.
After an uncertain approval response or conflict, the submission stays blocked
until the coordinated reads settle. Unavailable projections remain read-only.
An unchanged, freshly recovered proposal permits another explicit decision;
a different revision clears decisions and remounts its editors. Conflicts also
clear retained decisions. An unrelated transcript refetch does not disable a
valid approval projection. A continuously focused parked tab can remain stale
until refresh or submission; the server rejects a stale revision.

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

## Cumulative usage ceilings

Runtime preparation stores a validated, versioned `effective_usage_limits`
snapshot in server-owned run metadata before model execution. Each continuation
intersects saved ceilings with newly resolved settings and inherited limits.
Settings edits can tighten an accepted run but cannot widen its saved ceilings.
Run creation rejects caller-supplied effective-budget metadata.

The root worker restores cumulative usage once. Every specialist receives the
same accumulator; saved child usage is never added to it. Completion reporting
and schedule criteria remain root-owned. The shared composition helper guards
the SDK field inventory, takes numeric minima, and preserves enabled token
counting. The runtime sets only request and total-token ceilings.

Request limits apply at the framework model-request boundary. An approved action
produced by the last permitted request can settle before the next model request
is refused. Denials retain their separate consent handling. A terminal exhausted
root cannot resume or start another specialist.

Framework checks produce typed budget evidence. An inherited limit failure
propagates through delegation and ends the root with `budget_exhausted`, including
after approval continuation. A stricter child-only limit can return a bounded
specialist failure while the parent retains its own budget. Recovery evidence
remains available when approved work stops.

Token ceilings use observed provider usage. An already-streaming response can
overshoot its ceiling before stopping; these limits are not a preflight token
or monetary guarantee. Observed exhaustion stops further model/tool continuation.
Invocation metering still records partial responses under each agent's model.

Legacy runs without a saved snapshot acquire one from the limits resolved on
their next execution, including any retained schedule contract. Historical
settings cannot be reconstructed. This rollout limitation applies until those
runs finish or receive their first effective snapshot.

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

## Shared approval reads

A root suspension persists its approval revision before emitting approval
leaves. REST reloads, stream events, and the pending approvals list derive
those leaves from the same actor-scoped graph. Child runs retain their own
suspension batches, and their approvals appear through the root conversation.
Missing or terminal child references cannot become ordinary delegation
approval cards.

## Durable approval continuation

The root resume operation validates the current graph revision, exact leaf
coverage, and effective arguments under root-first family locks. It persists a
bounded, versioned `approval_continuation` reservation, marks the run running,
and reserves its execution owner in one transaction before starting work.
The reservation references existing child batches instead of copying their
message histories or interpreter snapshots. Its serialised size is limited to
four MiB, using the shared proposal bound.

Only that owner can start the continuation. Children are claimed when the
parent reaches their delegation calls. Identical repeated submissions return
`approval_already_reserved`; different decisions return
`approval_decisions_conflict`. Both responses refresh the client reads without
retrying the approval POST. Fresh suspension replaces the reservation and
installs a fresh batch.

Resume and the expiry sweep apply the same earliest pending family deadline.
An unexpired reservation protects its referenced queued children from separate
approval expiry. Execution lease loss, cancellation, or an uncertain effect
still stops the family. `agent_run_resume_requires_recovery` maps to the
existing blocked outcome and retains safe recovery evidence before cleanup.
This includes at most 25 completed or uncertain actions, a truncation marker,
and specialist conversation references. It contains no executable snapshots,
raw arguments, or provider payloads. Accepted continuations are not replayed
automatically after a process failure.

Cancellation retains this action evidence while keeping the cancelled outcome.
Accepted denials do not appear as uncertain actions. If a specialist settles
first, its safe evidence remains available when the root subsequently stops.
Standalone workflow recovery retains the existing Code Mode failure contract.
If delegation permission or depth is revoked while approval is pending, the
accepted continuation stops before another model request or specialist action.


## Legacy approval recovery during upgrades

A legacy approval can resume after a client refresh when its saved proposal and
owning context remain verifiable. Saved Monty 0.0.21 interpreter state preserves
completed effects across repeated approval rounds. Staged file content remains
owned by the suspended run. Unsupported versions, ambiguous native histories,
and stale revisions cannot authorise execution.

The old acceptance path persisted running state but held approved decisions only
in memory. If that execution is interrupted, a retained approval without a
reservation requires blocked recovery. Family settlement preserves completed
and uncertain action references before clearing executable state. Cancellation
keeps its cancelled outcome and retains the same evidence. Existing standalone
Code Mode recovery keeps its specific failure contract.

A coordinated backend and worker replacement is required for ownership and
approval metadata changes. The tolerant client can load old server payloads;
that wire compatibility does not make old lease-renewal code safe to run beside
new owners. Stop all old executions before any replacement process starts.
