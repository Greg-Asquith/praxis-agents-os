# Code-Mode Orchestration

Status: **implemented end to end**. Agents with code mode enabled expose one
orchestration tool, `run_workflow`, that runs a short model-authored Python
script in a sandboxed interpreter. The script composes the agent's
already-authorized tools; every nested call still crosses the same
authorization, approval, and audit path as a direct call. The web app renders
the workflow script, its nested calls, and mid-workflow approvals live and on
replay. This note describes how it works, why it is shaped this way, and how
to build on it.

## What code mode is

Without code mode, a multi-step data task costs one model request per tool
call, and every intermediate result travels through model context — paying
tokens and risking transcription errors on the way. Code mode lets the agent
write one short Python script against typed stubs of tools it already has: a
sandboxed interpreter can fetch, filter, aggregate, and act while intermediate
data stays local to the interpreter. The result is fewer model requests, lower
token use, and computed rather than transcribed values.

The architecture is a **composition surface, not an authority**. A script can
invoke only tools the agent could invoke directly, and every nested call
passes the same framework validation, workspace checks, role checks, envelope
policy, approval policy, output validation, bounding, usage accounting, and
audit path as a direct call. Code mode never aggregates or weakens per-call
decisions (see `governance.md` and `threat-model.md` §7).

Code mode is distinct from provider-native computation. `run_workflow`
composes Praxis tools in a local sandbox; a separate `run_code` capability for
pandas-class computation in a provider sandbox is planned but not built.
Neither sandbox may invoke the other. "Workflow" names Praxis-side tool
composition; "script" stays reserved for one-shot provider-sandbox
computation — the payload is Python either way, but the product capability is
the governed workflow it orchestrates.

## Enablement

Code mode is a per-agent capability: `agents.code_mode_enabled`, one checkbox
in the agent form above the tool list. `run_workflow` is never a catalog row
and cannot be mounted directly. There is no workspace-global switch and no
automatic activation. The operator-facing copy lives only in the checkbox
popover and uses outcome language ("Lets the agent combine several tools in
one workflow… Leave it off for simple chat or single-action agents"), keeping
sandbox mechanics out of a non-technical operator's face.

## How a workflow executes

### 1. The catalog replaces direct mounting

`build_runtime_tools` (`services/agents/runtime/tools/registry.py`) stays the
sole mounting authority. After agent selection, workspace disables, deferred
loading, and integration-context filtering, tools that are `code_eligible` are
diverted into a per-run `CodeModeCatalog` instead of being mounted directly.
Their JSON tool schemas leave the model request entirely; the catalog renders
them as concise Python function stubs — typed async signatures, declared
`output_model` return shapes, and one-line descriptions — embedded in the
`run_workflow` tool description (`code_mode/stubs.py`). A one-tool operation
becomes a one-line script; that trade is accepted so a request never pays for
both representations.

Integration stubs expose provider-native scoped references only. Their fixed
results are operation-specific typed dictionaries, so a workflow can pass a
created reference directly into a later tool without a discovery/report call
or a Praxis UUID. The server resolves each provider scope against current
active context at the nested dispatch boundary; missing scopes fail closed.

A tool whose schema falls outside the supported stub subset stays directly
mounted (with a logged warning) rather than receiving a lossy stub.

### 2. The script runs in a Monty sandbox

The bridge (`code_mode/bridge.py`) executes the script through a process-local
pool of `pydantic-monty` subprocess workers (`code_mode/executor.py`). The
interpreter receives **no ambient authority**: no OS handler, mount, network,
credentials, database, workspace filesystem, or third-party imports. Its only
external functions are the generated stubs for that run's eligible tools.
Environment, wall-clock, and filesystem access fail; network modules are not
importable. The import allowlist is a small stdlib subset (`asyncio`,
`collections`, `dataclasses`, `datetime`, `itertools`, `json`, `math`, `os`,
`pathlib`, `re`, `sys`, `typing`, `unicodedata`). The sandbox does support
classes, decorators, async code, and type-checked signatures.

Wrapped tool implementations keep their ordinary host/network authority — the
sandbox limits model-authored control flow, not the host implementation of a
tool. Eligibility never grants authority; dispatch still enforces every call.

### 3. Nested calls go through the framework, not around it

For each awaited stub call, the bridge builds an inner Pydantic AI
`ToolManager` in the same shape as the framework's own per-step path,
synthesizes a nested `ToolCallPart` (with its own call id and the outer
`run_workflow` call as parent), and invokes `ToolManager.handle_call`. That
covers argument validation and coercion, defaults, custom validators, context
construction, timeouts, and approval resolution, and execution still reaches
the runtime `Hooks` capability and `dispatch_tool_execution` — which remains
authoritative for membership and role re-checks, envelopes, approvals, output
contracts, result bounds, and audit.

The bridge must never reproduce the tool-layer pipeline. Direct and nested
execution are required to be identical for effective arguments, validation,
context, timeouts, authorization, envelope decisions, hook reachability, and
handler execution. Only the outer presentation differs deliberately: nested
failures surface as catchable in-workflow exceptions (a `ToolDenied` becomes a
denial the script can handle), nested calls do not consume the agent's retry
budget, and approvals suspend the outer tool (below).

The complete trust chain:

```text
model
  -> run_workflow (only directly visible orchestration tool)
    -> Monty worker (no ambient OS, files, network, DB, or credentials)
      -> generated eligible-tool stub
        -> inner Pydantic AI ToolManager
          -> Hooks capability
            -> dispatch_tool_execution
              -> membership + role + envelope + approval + output + audit
```

The sandbox does not replace dispatch policy or make prompt injection
harmless. Workspace isolation, exact tool authority, per-call approval, egress
classification, taint, bounds, and durable audit remain independent controls.

### 4. Nested calls are serial

The runtime protects one run-scoped SQLAlchemy `AsyncSession` with Pydantic
AI's sequential tool-execution mode, so the bridge holds one dispatch lock. A
script may use `asyncio.gather`, but its external tool calls execute serially.
The token and composition benefit does not depend on parallelism; parallel
nested dispatch requires a session-isolation or per-tool-barrier design first.

### 5. Everything is bounded

Every resource the sandbox and its boundary can consume has an explicit limit,
configured in `core/settings/code_mode.py` (`AGENT_CODE_MODE_*`):

| Bound | Setting (default) |
| --- | --- |
| Interpreter + cumulative wall-clock time | `AGENT_CODE_MODE_TIMEOUT_SECONDS` (60s), backstopped by `AGENT_CODE_MODE_REQUEST_TIMEOUT_SECONDS`, which replaces an unresponsive worker |
| Interpreter memory / recursion depth | `AGENT_CODE_MODE_MEMORY_MAX_BYTES` (64 MiB) / `AGENT_CODE_MODE_MAX_RECURSION_DEPTH` (100) |
| Nested calls per script | `AGENT_CODE_MODE_MAX_NESTED_CALLS` (25) |
| Captured print output | `AGENT_CODE_MODE_OUTPUT_MAX_CHARS` (8,000) |
| Each value crossing the boundary | `AGENT_CODE_MODE_VALUE_MAX_BYTES` (1 MiB) |
| Model-facing final result | `AGENT_CODE_MODE_RESULT_MAX_BYTES` (32 KiB) — intentionally much tighter than the boundary-value limit, so a workflow returns compact, decision-ready data rather than raw payloads |
| Suspended interpreter snapshot / durable resume artifact | `AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES` / `AGENT_CODE_MODE_STATE_MAX_BYTES`, cross-validated so a valid configuration can always fit |

Cumulative budgets survive approval suspension and resume. The bridge itself
rejects or converts over-budget and non-serializable boundary values — normal
dispatch deliberately preserves structured results, so free-text truncation is
not the interpreter boundary. Model/provider spend flows through the existing
usage accounting and AI-usage ledger unchanged.
One nested `classify` call accepts up to 500 items and issues sequential
helper-model requests in batches of at most 100. Each helper invocation records
its own usage event. Scripts stay inside the shared wall-clock and nested-call
budgets by using one bounded classifier call, not by looping over individual
items.

## Durable approvals

### Suspension and resume

When a nested call requires approval, the outer `run_workflow` tool suspends
through the existing deferred-tool machinery (`agent-runtime.md`). The bridge
captures the **pre-call** interpreter snapshot and persists a bounded resume
artifact in run metadata (`code_mode_state`, built and validated by
`code_mode/state.py`): the snapshot, the script, executed-call counts and
consumed budget, the nested trace so far, taint state, bounded print output,
and an executed-effects ledger (nested call id, tool name, effective-arguments
digest). The artifact is stamped with a state version and the exact Monty
version.

Postgres stays authoritative: run status, `approval_state`, audit events,
usage, and terminal evidence are the records of what happened. The snapshot is
only a resume artifact, accepted exclusively from the API's own database —
deserialized interpreter state is executable trusted input and must never be
accepted from a client or external store.

On resume, the executor restores the snapshot in a fresh worker (possibly a
different process, hours or days later), settles the pending call with the
decision, and continues driving the script. Approval can therefore outlive any
process — the reason the bridge is built on raw `pydantic-monty` and its
serializable interpreter snapshots rather than an in-process code-mode layer
that can only resolve approvals while the original process is alive. The
dependency is exact-pinned because serialized interpreter state carries no
cross-version compatibility guarantee; a Monty version bump is a
re-verification event, and a version-mismatched snapshot is refused rather
than loaded.

If the artifact cannot be restored (missing, corrupt, version-mismatched, or
over budget), recovery branches on what already ran:

- **Read-only prefix**: settle `run_workflow` with a structured model-visible
  failure so the model can redraft. Approvals, audits, and evidence stay
  intact.
- **Any completed effectful nested call**: fail closed to explicit operator
  recovery, listing the completed actions. Automatic redrafting is forbidden
  because a fresh script could repeat a side effect.

A run holds at most one suspended workflow; a second workflow that would
suspend fails closed with a structured failure instead of overwriting the
first snapshot. If a suspension artifact exceeds its aggregate bound,
application-only presentation values are dropped oldest-first (marked
`presentation_truncated`) before the suspension is abandoned entirely.

### One nested call, one decision

The operator approves the familiar nested tool action and its effective
arguments; the Python script is collapsed context, not a consent artifact. One
decision authorizes exactly one nested tool-call id, once — approval of call N
never leaks to call N+1 just because the outer call resumed as approved. The
approval card uses the nested tool's server-declared presentation and supports
the existing validated argument-override path. Denial resumes the script and
injects a typed denial the script can handle; it does not silently abandon the
workflow.

Because generic approval helpers can only see the outer message-history call,
the bridge/resume path owns nested pending and denied audit rows and denied
staged-content cleanup, each exactly once.

### Batch consent is one list-shaped call

Loops over write tools would otherwise turn one logical action into dozens of
approvals. The rule for every `code_eligible=True` write tool: when the
provider operation accepts a batch, the tool must accept that batch as one
list-shaped argument and declare an editable `records` presentation exposing
every bounded row before approval. The operator-edited row set becomes the
effective arguments sent through dispatch and bound into the terminal audit
digest. Singular calls are not bundled artificially when the provider has no
batch operation, and workflow-scoped grants (approving future, unreviewed
arguments) are deliberately excluded.

## Untrusted data: whole-interpreter taint

Code mode adds one threat channel: **tool outputs consumed by model-authored
code**. Data can flow between tools without model narration, so a poisoned
read could steer a later call invisibly — and ordinary Python transformation
erases `UntrustedNode` shape before the final value returns to the model.

The bridge applies conservative whole-interpreter taint rather than data-flow
tracking: if any nested result contains an `UntrustedNode`, the interpreter is
marked tainted (with a bounded, deduplicated source list), and taint stays
sticky through caught exceptions and suspension. A tainted workflow's final
value and captured print output are wrapped in one server-minted
`UntrustedNode` with `source_kind="code_mode_workflow"`; the per-source detail
travels in trace/audit metadata. A tainted interpreter can never use an
unattended envelope grant to auto-execute an effectful nested call — the call
suspends for approval, and the approval card and audit record identify the
untrusted derivation. `threat-model.md` §7 records the full contract and its
tests.

## Eligibility rules

Every `RuntimeToolDefinition` declares `code_eligible: bool` explicitly —
eligibility is never inferred from effect, provider, schema, or policy.
Import-time validation forbids `True` on runtime machinery (delegation,
always-mounted internals, `report_completion`, `run_workflow`, provider-native
`run_code`, capability-loading tools).

An eligible tool must return data that is useful to compose and that Monty can
serialize, have a schema the stub generator can represent faithfully, and
already be selected and allowed for the agent, workspace, and context.
Deferred-loading and MCP-derived tools are excluded for now. Binary or
multimodal producers, faithful-render surfaces (e.g. Gmail message reading),
conversational acts, memory, planning, skill loading, delegation, and
completion reporting stay direct — they are conversation-shaped, not
data-shaped.

Helper-native tools also stay direct unless they return text-only JSON-safe
data and send content only to a configured model provider. Native `classify`
and active workspace-defined `classifier_{name}` tools meet that exception:
their server-enforced closed label sets keep the composable return data-shaped.
Workspace definitions are loaded at the start of each run, so saved changes
apply to the next run. Each result's `value` is copied exactly from the
corresponding validated tool input after the helper returns; the helper can
author only the index and closed-set label, never arbitrary result text.

## Trace and replay

Bridge-internal calls are not Pydantic AI message parts, and live SSE events
are observation channels, not replay sources. The durable representation is
trace metadata attached to the outer `run_workflow` result
(`code_mode_trace`). Each entry carries stable order, the nested and parent
call ids, tool name, an effective-arguments digest (never unrestricted
arguments), a presentation-resolvable summary, status (succeeded, failed,
pending, denied), and a bounded result or failure excerpt.

The completed-run trace also retains the complete normalized nested result as
**application-only presentation evidence**: replay shows exactly the governed
value the sandbox received — every fan-out resource and row — without it ever
entering model context. Tools with a richer governed `public_result` contract
use that complete user-only value for replay and live SSE while only
`return_value` enters the sandbox. The settled workflow card separately
renders the outer result as "Output sent to model": the bounded final
expression, not a copy of the richer presentation values.

The web renders workflow rows exclusively from this metadata
(`apps/web/src/features/conversations/components/`), and live and reloaded
turns must be identical for success, failure, suspension, resumption, expiry,
and legacy turns. Pending approvals are never hidden behind a collapsed
container. Live progress streams over the existing SSE protocol
(`workflow.state` plus the ordinary `tool.*` events); the client accepts new
event names before the server may emit them, so protocol changes deploy
client-first.

## Guidance has one source per audience

Model-facing guidance is generated with the stub catalog from the same source
as the signatures and output contracts (`code_mode/stubs.py`): direct tools
for conversation-shaped acts, wrapped functions for data work, short scripts,
the last expression is the result, intermediate results are variables to
reduce — not payloads to return. Sandbox syntax and stdlib claims come from
verified probes of the pinned interpreter
(`tests/services/agents/runtime/code_mode/test_monty_probes.py`), not
hand-maintained prose, so guidance cannot drift from what the sandbox actually
supports. Operator-facing guidance lives only in the enablement popover.

## Module layout

```
apps/api/
  core/settings/code_mode.py           # AGENT_CODE_MODE_* bounds + cross-validation
  services/agents/runtime/
    tools/code_mode.py                 # run_workflow definition + per-run tool factory
    code_mode/
      stubs.py                         # CodeModeCatalog + Python stub rendering
      executor.py                      # Monty worker pool, execute/resume drivers
      bridge.py                        # nested dispatch, taint, trace, bounds, suspension
      state.py                         # durable resume artifact build/load/clear
      approval.py                      # trusted nested-approval metadata contract
apps/web/src/features/
  agents/components/                   # code-mode enablement checkbox + popover
  conversations/components/            # workflow card, nested-call rows, approvals, replay
```

Tests live in `tests/services/agents/runtime/code_mode/` (stub rendering,
bridge parity, taint matrix, executor, durable state, settings) and
`tests/scenarios/test_code_mode.py` (end-to-end suspension/resume across
process boundaries, batch approvals, hostile-output framing, role denial).

## Building on it

- **Making a tool code-eligible**: set `code_eligible=True` on its
  `RuntimeToolDefinition`, keep its input schema inside the supported stub
  subset (`stubs.py` raises `UnsupportedCodeModeSchemaError` otherwise, and
  the registry falls back to direct mounting), and declare an `output_model`
  so the stub advertises a typed return. If it writes and the provider has a
  batch operation, follow the batch-consent rule above: one list-shaped
  argument, an editable `records` presentation showing every row, and a
  declared maximum batch size.
- **Changing bounds**: adjust the `AGENT_CODE_MODE_*` settings; the settings
  validator keeps timeouts and snapshot/state budgets internally consistent.
- **Upgrading Monty or Pydantic AI**: both contracts are load-bearing. Monty
  is exact-pinned because serialized snapshots have no cross-version
  guarantee; the probe test suite is the checklist of behaviors to re-verify
  (resume mappings, resource-limit semantics, boundary conversion, the import
  allowlist) before a bump lands. The bridge's inner-`ToolManager`
  construction mirrors the framework's own path, so a Pydantic AI upgrade
  must re-check that seam.

Some extensions are deliberately excluded until their prerequisite design
exists, rather than being half-supported: parallel nested dispatch (needs safe
session isolation), stubs for deferred-loading and MCP-derived tools (the
latter needs a threat-model delta for MCP output flowing through scripts),
in-sandbox tool discovery, workspace-level controls, workflow-scoped tool
grants (consent would cover unreviewed future arguments), a deduplicating
execution ledger that could replay past writes instead of the fail-closed
recovery branch, and object-storage snapshot offload. Treat these as design
decisions to revisit explicitly, not gaps to patch in passing.
