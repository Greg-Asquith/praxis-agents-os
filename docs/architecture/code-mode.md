# Code-Mode Orchestration

- **Status**: adopted architecture; implementation pending in plans 110–113
- **Owner**: agent runtime
- **Rule**: implementation work cites the decision it consumes. A change that
  deviates records the deviation here in the same pull request.
- **Boundary**: this note governs local orchestration of already-mounted Praxis
  tools. Provider-native computation remains the separate `run_code` capability
  planned in 059.

## 1. Intent

Code mode lets an agent write one short Python script against typed stubs of
tools it already has. A sandboxed interpreter can fetch, filter, aggregate, and
act without sending every intermediate value through another model request.
The result should be fewer requests, lower token use, and less transcription
error without creating a second authorization or execution path.

The architecture is a **composition surface, not an authority**. A script can
invoke only tools that the agent could invoke directly, and every nested call
must pass the same framework validation, workspace checks, role checks,
envelope policy, approval policy, output validation, bounding, usage
accounting, and audit path as a direct call.

This is distinct from provider-native compute:

| Surface | Purpose | Sandbox | Tool name |
|---|---|---|---|
| Code-mode orchestration | Compose Praxis tools while intermediate data stays local to the interpreter | Local Monty worker with only declared tool stubs | `run_script` |
| Provider-native compute (plan 059) | Perform pandas-class or file-heavy computation in a provider sandbox | Model provider or later external executor | `run_code` |

Neither sandbox may invoke the other.

## 2. Architecture decisions

### D-1 — Use raw `pydantic-monty`, not Harness `CodeMode`

Praxis builds the bridge directly on exact-pinned `pydantic-monty`. The
Pydantic AI Harness remains a design reference, not a runtime dependency.

Harness `CodeMode` owns a toolset and catalog layer and resolves approval or
deferred calls only inline through `HandleDeferredToolCalls` while the process
is alive. As re-verified for Harness 0.18.1, an unresolved deferral becomes a
sandbox error and then a model retry; neither `CodeMode` nor
`StepPersistence` restores CodeMode per-run state across a durable pause.
Praxis approvals can remain suspended for days and resume in another process.
Raw Monty's serializable interpreter snapshots are therefore required for the
product contract.

The dependency is exact-pinned because Monty's serialized state has no
cross-version schema-evolution guarantee. A Monty or Pydantic AI lock refresh
is an architecture re-verification event before dependent work proceeds.

### D-2 — Trust boundary: the framework `ToolManager` is the only nested invocation path

The bridge is a small Praxis wrapper toolset. It exposes only `run_script` to
the model and retains eligible tools internally as a `FunctionToolset` built
from their existing Pydantic AI `Tool` objects.

For each nested call it:

1. builds the inner `ToolManager` in the same shape as the framework's own
   `for_run_step` path: the wrapped toolset, the parent manager's root
   capability, the run context, and the prepared tools returned by
   `toolset.get_tools(ctx)`;
2. synthesizes a nested `ToolCallPart` with its own call id and the outer
   `run_script` call as parent;
3. calls `ToolManager.handle_call(..., wrap_validation_errors=False)`;
4. converts a returned `ToolDenied` into an in-script exception; and
5. adds only Praxis-owned concerns around that call: serial locking,
   parent linkage, byte limits, snapshot control, trace metadata, audit
   metadata, and client events.

At the 2.28.0 lock, `handle_call` accepts first-class `approved=` and
`metadata=` inputs and covers argument schema validation and coercion, defaults,
custom validators, context construction, timeouts, approval resolution, and
execution. Execution still reaches the existing Hooks capability and
`dispatch_tool_execution`, which remains authoritative for membership and
role re-checks, envelopes, approvals, output contracts, result bounds, and
audit.

Praxis must not reproduce the Tool-layer pipeline. Direct/nested parity is
required for effective arguments, custom validation, context, timeouts,
authorization, envelope decisions, hook reachability, and handler execution.
Outer presentation intentionally differs: nested raw failures remain
in-script, nested calls do not consume the agent retry budget, and deferrals
are translated by the lane slice that owns them.

### D-3 — Trust boundary: no ambient authority and every boundary is bounded

Monty receives no OS handler, mount, network, credentials, database, workspace
filesystem, or third-party imports. Its only external functions are generated
stubs for the eligible tools selected for that run. Wrapped tool
implementations keep their ordinary host/network authority, so eligibility
never grants authority and dispatch still enforces every call.

The complete resource obligation is binding:

- CPU where the pinned API provides a true quota; any residual is documented;
- wall-clock time;
- soft and hard memory;
- stack depth;
- cumulative nested-call count;
- captured print and final-output size;
- a hard serialized-byte limit on every value crossing into or out of Monty;
- cumulative budgets preserved across approval suspension and resume; and
- ordinary per-call model/provider spend through existing usage accounting and
  the AI-usage ledger.

Normal dispatch deliberately preserves structured results. The bridge must
independently reject or convert an over-budget or non-serializable nested
value; it cannot rely on free-text truncation as its interpreter boundary.

### D-4 — Execution model: nested calls remain serial

The runtime protects one run-scoped SQLAlchemy `AsyncSession` with Pydantic
AI's sequential tool-execution mode. The bridge therefore holds one dispatch
lock. A generated script may use `asyncio.gather`, but its external tool calls
execute serially.

The token and composition benefit does not depend on parallel execution.
Parallel nested dispatch can be reconsidered only after plan 057 is replaced
by an explicit safe session-isolation or per-tool-barrier design.

### D-5 — Durable approvals: Postgres is authoritative; a snapshot is a resume artifact

Run status, `approval_state`, audit events, usage, and terminal evidence remain
authoritative Postgres records. A bounded Monty snapshot is stored beside them
only to continue a partially executed script. It is stamped with a code-mode
state version and exact Monty version and is accepted only from the API's own
database. Deserialized interpreter state is executable trusted input and must
never be accepted from a client or external store without a separately
designed trust boundary.

Snapshot load or compatibility failure branches on the completed prefix:

- **Read-only prefix**: settle `run_script` with a structured model-visible
  failure so the model may redraft. Existing approvals, audits, and evidence
  remain intact.
- **Any completed effectful nested call**: fail closed to explicit operator
  recovery and list the completed actions. Automatic redrafting is forbidden
  because a fresh script could repeat a side effect.

The resume artifact carries a bounded executed-effects ledger containing the
nested call id, tool name, and effective-arguments digest. A durable,
deduplicating execution ledger is the heavier alternative and remains a
follow-up.

### D-6 — Durable approvals: one nested call, one decision

The operator approves the familiar nested tool action and effective arguments;
the Python script is collapsed context, not a consent artifact. One decision
authorizes exactly one nested tool-call id once. Approval of call N must never
leak to N+1 merely because the outer `run_script` call resumed as approved.

When a nested call requires approval, the outer tool suspends through the
existing deferred-tool machinery. The approval card uses the nested tool's
server-declared presentation and supports the existing validated argument
override path. Denial resumes the outer tool body and injects a denial into the
interpreter; it does not silently deny the outer call and abandon the script.

The bridge/resume path owns nested pending and denied audit rows and denied
staged-content cleanup because generic approval helpers can see only the outer
message-history call. Each record and cleanup occurs exactly once.

Batch consent is expressed as one list-shaped tool call whose existing
`records` presentation shows the complete bounded row set. Script-scoped
grants are not part of this lane because they would approve future arguments
the operator has not reviewed.

### D-7 — Catalog rules: wrapped tools replace direct mounting

When code mode is enabled, eligible wrapped tools are not also registered as
direct Pydantic AI tools. Their JSON schemas leave the model request and are
represented only by concise Python signatures and one-line descriptions in
the generated stub catalog. A one-tool operation becomes a one-line script;
the trade is accepted so the request does not pay for both schemas.

Every `RuntimeToolDefinition` declares `code_eligible: bool`. Eligibility is
never inferred from effect, provider, schema, or policy. Import-time validation
forbids `True` on runtime machinery such as delegation, always-mounted
internals, `report_completion`, `run_script`, provider-native `run_code`, and
capability-loading tools.

An eligible tool must:

- return data that is useful to compose and Monty can serialize;
- have a schema the stub generator can faithfully represent;
- already be selected and allowed for the agent/workspace/context; and
- not be deferred-loading or MCP-derived in v1.

Binary or multimodal `ToolReturn` producers, faithful-render surfaces such as
Gmail message reading, helper-native web/media tools, conversational acts,
memory tools, planning tools, skill loading, delegation, and completion
reporting remain direct. Plan 110 initially wraps eligible auto-read tools;
approval-default and envelope-gated writes remain direct until plan 112 makes
durable mid-script approval available.

Unsupported schemas remain direct rather than receiving a lossy stub.
Non-serializable or over-budget returns become structured in-script failures.
`build_runtime_tools` stays the sole mounting authority and applies the split
after agent selection, workspace disables, deferred loading, and integration
context filtering.

### D-8 — Naming and classification: explicit enablement

The outer tool is `run_script` and declares:

- `effect="read"`;
- `effect_scope="internal"`;
- `egress="none"`;
- `default_policy="auto"`; and
- `configurable=False`.

The outer tool has no effect of its own. Every nested effect is independently
classified, authorized, audited, and approved. The corresponding threat-model
channel in D-9 is mandatory; the outer classification must not become a way to
bypass nested enforcement.

Code mode is an agent capability controlled by
`agents.code_mode_enabled`. The agent form places one checkbox above the tool
list with explanatory copy; `run_script` is never a catalog row. There is no
workspace-global switch and no automatic threshold-based activation in v1.

### D-9 — Threat model and governance: taint survives transformations

Code mode adds the threat-model channel **tool outputs consumed by
model-authored code**. Data may flow between tools without model narration, so
a poisoned read can steer a later call invisibly. Per-call authorization,
audit, bounds, and egress classification limit impact but do not preserve
provenance after ordinary Python extraction or transformation.

The bridge therefore applies conservative whole-interpreter taint:

1. traverse every nested result before it crosses into Monty;
2. when any value contains an `UntrustedNode`, mark the interpreter tainted
   and retain a bounded, deduplicated source list plus overflow count;
3. keep taint sticky through caught exceptions and, in plan 112, suspension;
4. wrap a tainted script's final value and captured print output in one
   server-minted `UntrustedNode` with
   `source_kind="code_mode_script"` and `source_ref` equal to the outer call
   id; and
5. carry the complete bounded source list in nested-trace/audit/event metadata,
   and later `code_mode_state`, rather than overloading the singular node
   schema.

The existing marker vocabulary and `render_untrusted_frames()` remain
unchanged. The frame tells the model that the value is data; trace metadata
gives operators per-source detail. This is intentionally not data-flow
tracking.

A tainted interpreter can never use an unattended envelope grant to
auto-execute an effectful nested call. The call must suspend for approval, and
the approval card and audit record identify the untrusted derivation and its
sources. Deterministic tests cover extraction, concatenation,
collection/filtering, caught exceptions, structured final values, and derived
write arguments. The named G6 eval must prove the attempted write still
suspends and that the final model-visible representation remains framed.

Governance §2 gains the companion law: each nested call retains its own effect,
role, envelope, approval, and audit enforcement; code mode never aggregates or
weakens those decisions.

### D-10 — Guidance has one source for models and one for operators

Model-facing guidance is generated with the stub catalog from the same source
as the signatures. It says that direct tools serve conversation-shaped acts,
wrapped functions serve data work, scripts should be short, the last
expression is the result, and one script per task is preferred to many small
scripts. Sandbox syntax and stdlib guidance come from the pinned probe record,
not hand-maintained prose. In particular, stale claims that Monty lacks
classes, decorators, or typed signatures must not be introduced.

Operator-facing guidance lives only in the checkbox popover and uses outcome
language:

> Lets the agent combine several of its tools in one step, working through
> data without back-and-forth. Use it for agents that run reports, reconcile,
> or act on many items at once — for example, run an ads report, work out the
> weakest campaigns, and pause them. Leave it off for simple chat or
> single-action agents.

The surface must fit the existing compact agent form, use existing form and
popover primitives, remain accessible on desktop and mobile, and keep this
capability separate from the searchable tool rows. No automatic enablement is
allowed in v1.

### D-11 — Durable nested trace: one replay representation

Bridge-internal calls are not Pydantic AI message parts. Live SSE and audit
events are observation channels, not replay sources. The durable
representation is therefore bounded, redacted trace metadata attached to the
outer `run_script` result.

Each nested entry contains:

- stable order;
- nested `tool_call_id` and parent outer call id;
- tool name;
- effective-arguments digest, never unrestricted arguments;
- a presentation-resolvable summary;
- status: succeeded, failed, pending, or denied; and
- a bounded result or failure excerpt.

Plan 110 writes settled traces; plan 112 persists partial trace state across
suspension and appends on resume. The web renders replay exclusively from this
metadata and must make live and reloaded turns identical for success, failure,
suspension, resumption, expiry, and legacy turns. Pending approvals are never
hidden behind a collapsed container.

## 3. Trust-boundary summary

```text
model
  -> run_script (only directly visible orchestration tool)
    -> Monty worker (no ambient OS, files, network, DB, or credentials)
      -> generated eligible-tool stub
        -> inner Pydantic AI ToolManager
          -> Hooks capability
            -> dispatch_tool_execution
              -> membership + role + envelope + approval + output + audit
```

The sandbox limits model-authored control flow. It does not sandbox the host
implementation of a wrapped tool, replace dispatch policy, or make prompt
injection harmless. Workspace isolation, exact tool authority, per-call
approval, egress classification, taint, bounds, and durable audit remain
independent controls.

## 4. Lane ordering and deployment law

The binding order is:

`109 (DONE) → 110 → 111 → measured exit gate → 112 → 113`

- Plan 110 must deploy client protocol acceptance before the server emits any
  new script event. The web SSE parser rejects unknown names, so client-first
  is a deployment law, not permission to ship both sides in an unsafe order.
- Plan 111 supplies the operator configuration and complete live/replay UI.
- Plan 112 has three hard prerequisites: 110 complete, 111 complete, and the
  measured exit gate recorded as passing in §6.
- A missed exit threshold stops the lane at 111. Only the maintainer may choose
  revision and re-measurement or register a D16 revisit in the roadmap.
- Plan 113 follows 112 and uses the already-landed `records` presentation
  format; it does not redesign that format.

## 5. Verification obligations

Plan 110 records its exact package/API probes in §7 before relying on them.
At minimum it verifies:

- the actual 0.0.21 `ResourceLimits` fields and semantics;
- external lookup, sync/async nested calls, and serial locking;
- snapshot dump/load across a fresh process;
- successful `ExternalReturnValue` resume and both documented exception
  mappings through the integrated async driver;
- fail-closed behavior if the documented exception mappings do not inject a
  catchable error (a STOP for plan 112);
- Pydantic AI 2.28.0 inner-manager construction, `approved=` and `metadata=`,
  raw error behavior, `ToolDenied`, custom validation, context, and timeouts;
- Monty-serializable types and the supported JSON-schema-to-stub subset;
- byte, time, memory, stack, call-count, output, and cumulative-resume limits;
- sticky taint and byte-faithful untrusted framing; and
- no ambient filesystem, network, environment, clock, or credentials.

Direct/nested parity tests and translation tests are separate. The first prove
one authoritative tool execution path; the second prove nested failures,
denials, approvals, trace, and suspension are represented correctly.

## 6. Measured exit gate

The gate owner is the **maintainer/operator**. Recording measurements is not
authority for an executor to waive or reinterpret a miss.

### Corpus

1. the named G6 code-mode graded-eval case from D-9; and
2. a fixed multi-read comparison benchmark using the same agent, model,
   provider, prompt, tool implementations, and source fixtures in both arms.
   The minimum task compares X and Y using two read tools and produces one
   user-facing comparison.

### Pre-registered run design

- Run each on/off benchmark arm **five times**.
- Record every run, including failures and redrafts.
- Compute success rate across all runs.
- Evaluate request, token, and latency thresholds on the median per arm.
  Evaluate redrafts over all scripted runs and also record the median per-run
  count. A failed run remains in the raw record and success denominator; it is
  never silently dropped from the metric set.
- Use the same provider/model version and fixed model settings across arms.

### Thresholds

All must pass:

| Metric | Passing threshold |
|---|---|
| Task success | Code mode is at parity with direct calling; no lower success rate across the five runs |
| Model requests | Median reduced by **at least 50%** |
| Input tokens | Median reduced by **at least 20%** |
| Output tokens | Median reduced by **at least 20%** |
| Total tokens | Median reduced by **at least 20%** |
| End-to-end latency | Median no more than **20% worse** |
| Redrafts | At most **one redraft across five scripted runs**, with median per-run redrafts equal to zero |
| G6 compliance | **Zero** non-compliant graded-eval outcomes |

The maintainer may change a number only before a gate run and records the
change, date, and rationale in §7. Changing a threshold after seeing results
does not make that run pass.

### Failure decision

A missed threshold stops the lane. Plan 112 does not start. The maintainer
either revises plans 110/111 and repeats the full gate or records a D16 revisit
in `docs/plans/000_MASTER_ROADMAP.md`. Proceeding despite a miss is not an
executor decision.

## 7. Evidence appendix

This appendix is the durable home for probe findings and measured gate data.
Planning evidence does not belong in runtime comments or docstrings.

### 7.1 Architecture pre-flight — 2026-08-13

- Runtime drift from the plan-109 anchor `ee2f714`: none under
  `apps/api/services/agents/runtime/`.
- Pydantic AI contract assumed by the implementation plans: lock resolution
  2.28.0; `ToolManager.handle_call` must be re-probed by plan 110 before use.
- Monty contract: 0.0.21 exact. A temporary exact-package probe confirmed
  `resume(self, /, result)` and the `ExternalResult` TypedDict union:
  `ExternalReturnValue`, `ExternalException`, `ExternalExceptionData`, and
  `ExternalFuture`. Plan 110 must pin return and exception mappings through its
  integrated async driver. No dependency is added by this note.
- Harness comparison point: 0.18.1 inline-only approval resolution; Harness is
  not added by this lane.

### 7.2 Plan 110 package and bridge probes

**2026-08-13 — Chunk A package probes.** The probe suite is
`tests/services/agents/runtime/code_mode/test_monty_probes.py`; run with
`cd apps/api && uv run pytest
tests/services/agents/runtime/code_mode/test_monty_probes.py -q`. The recorded
run passed 24 tests. The lock resolves `pydantic-ai` 2.28.0 and exact-matched
`pydantic-monty`, `pydantic-monty-client`, and `pydantic-monty-runtime` 0.0.21.
The post-lock `apps/api/uv.lock` SHA-256 is
`0a9ebef2d29ccf0f09f20531f376e09e33e4ab5bffb9f7a3147fad13d95cb0f2`.
The broader `make check` compatibility run also passed: migration drift was
clean, 2,058 API tests passed with 9 configured skips, and 121 web test files /
679 tests passed before the production build completed.

- `AsyncMonty.feed_run` dispatches both synchronous and asynchronous
  `external_lookup` callables. An exception raised by an async host callable is
  injected into the interpreter and is catchable by the script.
- Manual `feed_start` stops on an `AsyncFunctionSnapshot` carrying
  `function_name`, integer `call_id`, positional `args`, and keyword `kwargs`.
  An awaited async external call has a two-stage resume contract: first resume
  the function snapshot with `{"future": ...}`, then settle the resulting
  `AsyncFutureSnapshot` by call id with `{"return_value": value}`,
  `{"exception": exception}`, or
  `{"exc_type": supported_name, "message": message}`. Directly resuming an
  awaited function snapshot with a plain return value produces a catchable
  interpreter `TypeError` because that value is not awaitable. The manual
  bridge must preserve both stages.
- A suspended snapshot dumps to bytes, exits its original pool, loads in a new
  pool/process, re-announces the same external call, and completes using the
  `external_lookup` supplied to `load_snapshot`. Rebinding on load is therefore
  the host-tool reattachment mechanism. `feed_run` and `resume_auto` hide the
  intermediate snapshot; the durable bridge must use the manual `feed_start`
  loop.
- The production-shaped probe retained and dumped the function snapshot while
  a host dispatch coroutine was in flight, settled it after dispatch, restored
  the same pre-call dump in a fresh pool, and injected `PermissionError` by the
  typed exception-data mapping. The paused-interpreter ownership required by
  plan 112 is available.
- `ResourceLimits` has exactly four optional fields:
  `max_duration_secs`, `max_memory`, `gc_interval`, and
  `max_recursion_depth`. Duration exhaustion surfaces as
  `MontyRuntimeError(TimeoutError)`, memory exhaustion as
  `MontyRuntimeError(MemoryError)`, and stack exhaustion as
  `MontyRuntimeError(RecursionError)`; each leaves the worker alive for a fresh
  checkout. The memory signal crosses to the host even when script code tries
  to catch `MemoryError`, so it is not an ordinary recoverable in-script soft
  limit. Pool `checkout_timeout` raises host `TimeoutError`. Pool
  `request_timeout` kills the stuck worker, raises `MontyCrashedError` with
  `timed_out=True`, and replaces the worker before the next checkout.
- The pinned language surface executes user classes, decorators, async methods,
  and type-checked signatures. The import allowlist observed by the probe is
  `asyncio`, `collections`, `dataclasses`, `datetime`, `itertools`, `json`,
  `math`, `os`, `pathlib`, `re`, `sys`, `typing`, and `unicodedata`.
  Non-allowlisted imports fail. Without an OS handler or mount, environment
  reads, wall-clock reads, and filesystem reads fail; network modules are not
  importable.
- Boundary conversion accepts bytes, tuples, sets, and registered host
  dataclasses; it rejects at least `bytearray` and `complex` with
  `MontyConversionError`. Monty's conversion surface is intentionally broader
  than the code-mode value contract, so the bridge still needs its independent
  byte-bounded, JSON-safe allowlist and binary-content rejection.

Residual resource risks on 0.0.21: there is no distinct configurable hard
memory field and no CPU-quota field. `max_duration_secs` bounds interpreter
execution, not elapsed host-tool time, so the outer wall-clock timeout remains
mandatory. `gc_interval` is tuning rather than a cap. Hard allocator failures
remain contained by subprocess crash isolation and the pool-level
`request_timeout`; these controls do not replace the bridge's cumulative
wall-clock, call-count, value, and output budgets.

### 7.3 Measured gate record

**Status: not run. Plans 110 and 111 are pending.**

Before running, record:

- date;
- provider and exact model/version;
- model settings;
- fixture and benchmark revision;
- any maintainer-approved pre-run threshold change.

Then append one row per raw run:

| Arm | Run | Success | Requests | Input tokens | Output tokens | Total tokens | Latency | Redrafts | G6 result | Notes |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---|
| Pending | — | — | — | — | — | — | — | — | — | — |

Record both arm medians, success rates, the threshold verdict for every metric,
and the maintainer's dated **PASS** or **STOP** decision below the raw table.

## 8. Follow-ups register

These are deliberately outside plans 110–113 and require their own decision or
plan before implementation:

| Follow-up | Re-entry condition |
|---|---|
| Parallel nested dispatch | Plan 057 is replaced by a safe session-isolation or per-tool-barrier design, then D-4 is revisited first |
| Deferred-tool stubs | Plans 094 and 110 are landed; compare deferred stub materialization with Pydantic AI's hidden-until-revealed tool channel |
| MCP-derived stubs | Plans 095 and 110 are landed; add a threat-model delta for MCP output flowing through scripts |
| In-sandbox discovery (`search_tools` / `describe_tool`) | Measured catalogs show even concise stub text materially harms requests or routing |
| Enablement suggestion in the agent form | On/off measurements plus observed multi-call turns identify a useful, non-surprising suggestion rule |
| Workspace-level controls | A workspace governance need cannot be served by per-agent opt-in and existing tool grants |
| Script-scoped tool grants | A concrete workload cannot use batch arguments, and consent can constrain future arguments to an operator-reviewed target/value set |
| Durable deduplicating execution ledger | Product evidence justifies replaying past executed writes instead of D-5's fail-closed recovery branch |
| Object-storage snapshot offload | Measured bounded snapshots create material Postgres storage pressure |

## 9. Consumed by

| Plan | Contract consumed | Status |
|---|---|---|
| 110 | D-1–D-4, D-7–D-11; probe record and first safe read-only substrate | Pending |
| 111 | D-8, D-10, D-11; operator enablement and live/replay presentation | Pending |
| 112 | D-3–D-6, D-9, D-11; durable approvals, taint persistence, write tools | Pending; hard-gated by §6 |
| 113 | D-6, D-7, D-11; faithful batch approvals over landed `records` | Pending |
| 059 | Compute/orchestration delineation and no sandbox nesting | Pending |
| 094 | Deferred-loading exclusion and joint revisit | Pending |
| 095 | MCP exclusion and threat-model-gated joint revisit | Pending |
