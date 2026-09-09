# Code Mode implementation contracts

Read this before changing sandbox state, nested approvals, or workflow
replay. The [Code Mode architecture](../architecture/code-mode.md) explains
the design and trust boundaries. Backend paths are relative to `apps/api/`.

## Execution and durable state

Code-mode execution lives under `services/agents/runtime/code_mode/` and
uses the dedicated `core/settings/code_mode.py` mixin. Its lazily created
Monty subprocess pool must close in API, worker, and test lifecycles. The
sandbox has no OS handler or mount; nested calls are serial and must use the
parent's prepared `ToolManager` so validation, approval, hooks, dispatch,
and audit remain the framework-owned path. Durable nested approvals persist
a version-stamped Monty snapshot in workspace-confidential run metadata.
Bound the pre-base64 snapshot with `AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES` and
the complete serialised artifact with `AGENT_CODE_MODE_STATE_MAX_BYTES`;
suspension-only presentation evidence is trimmed oldest-first before an
oversized artifact fails closed. A decision authorises only the matching
nested call and validated effective arguments. Captured print
output is persisted cumulatively across suspensions, and every resume uses
only the remaining output budget. Keep script arguments, nested results,
final values, and print output independently bounded. Generated
stubs render faithful input signatures and declared `output_model` return
shapes; tools without a declared output model remain explicitly `Any`.
Completed-run nested traces retain each complete normalised nested result as
application-only presentation evidence, with no additional UI sampling or
truncation. Trace entries record a wall-clock start and, once settled, the
measured execution duration; a resumed approval times only its settlement
execution. Suspended artifacts may omit the oldest presentation values only
to meet the aggregate state ceiling, while retaining their trace summaries
and explicit truncation markers. When a nested tool supplies a governed
`public_result`, that richer value is the presentation evidence while only
`return_value` enters the sandbox. That evidence must never enter model context. The governed
nested-value and provider product bounds remain authoritative. Keep the
workflow's model-facing final-result bound materially tighter than the
nested value bound so a faulty reduction cannot flood every later request.

## Signature rendering

`services/agents/runtime/code_mode/stubs.py` owns signature rendering and its
strict schema adapter. Pydantic AI 2.42.0's public renderer is not adopted:
recursive value types, input/output collisions, and required/default semantics
lose information. See the architecture's
[renderer decision](../architecture/code-mode.md#signature-renderer-ownership).
Unsupported schemas remain directly mounted. Shared types retain one name,
conflicting output types receive output-specific names, and Python keyword
fields use functional `TypedDict` syntax without changing their wire names.
The complete eligible catalogue must compile and pass the pinned Monty type
checker when schemas or providers change.

## Transcript presentation

Code-mode workflows render as one collapsed outer row whose children recurse
through the standard `ToolCallRow`; keep live state normalised by parent id,
rebuild replay only from the persisted nested trace, and auto-expand any
nested approval so operator consent is never hidden. Label the children as
tool calls, not workflow steps: interpreter-side filtering, aggregation, and
branching are meaningful work but are not separate trace children. Prefer a trace's
structured presentation result over its excerpt so provider presenters work
after reload. The presentation result is complete relative to the governed
nested tool return: pagination may control the visible page, but must not
discard rows, and copy/export actions use the complete retained result. A
truncated legacy excerpt gets explanatory fallback copy, not malformed JSON.
Settled workflow rows also expose the complete outer tool result under an
explicitly labelled model-output disclosure so operators can distinguish
what the model received from the richer nested results retained for them.
When nested results contain exact mutation counts, summarise the settled
container in outcome language and keep applied, skipped, failed, and declined
outcomes distinct. Derive this only from retained structured results; do not
infer effects from proposed arguments or a model-authored reason.

## Pending workflow projection

Approval reloads expose a `workflows` list for root and delegated workflows.
Each workflow retains its owning run and delegation reference. Its pending
leaf carries the nested action's identity, editable arguments, and untrusted
data warning. The singular `workflow` field remains available for one root
workflow. Root stream approval events use these same leaves after suspension
commits, so child workflow arguments and warnings match reload.

Approval reads reject malformed or unavailable workflow state instead of
presenting an unverifiable action. A root resume against that state stops with
bounded recovery evidence, preserving completed effects for inspection.

Delegated workflow decisions compile against the child's saved interpreter
state. The parent carries the child's deferred results, including the nested
call identity and effective-argument digest. A later suspension creates a fresh
batch and requires another decision. Completed nested effects remain in the
saved trace, so continuing a second approval round does not rerun them.

If a delegated workflow cannot resume safely, family recovery preserves its
completed and uncertain effect references before executable state is cleared.
The main conversation shows that evidence and links to the specialist
transcripts. Recovery does not authorise automatic redrafting or effect replay.
