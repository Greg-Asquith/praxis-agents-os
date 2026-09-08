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
