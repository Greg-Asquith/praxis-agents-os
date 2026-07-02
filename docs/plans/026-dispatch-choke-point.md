# Plan 026: Dispatch choke point — tool audit, mutation tracking, capability envelopes

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat f83d210..HEAD -- apps/api/services/agents/runtime/ apps/api/models/audit_event.py apps/api/services/audit_events/ apps/api/workers/agent_runner.py`
> Plan 025 must be DONE before this plan starts; diff against 025's merge
> commit for the `runtime/tools/` files instead of `f83d210` once it lands.
> On any mismatch with "Current state", STOP.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH (sits inside every agent turn; a bug here breaks all runs.
  Mitigated by the fire-and-forget audit pattern and the no-behavior-change
  tests)
- **Depends on**: 025 (hard — consumes `provider`/`effect`/`output_model`
  from the contract)
- **Category**: harness spine (roadmap `000_MASTER_ROADMAP.md` Phase 1;
  donor design A2 extended to delegation)
- **Planned at**: commit `f83d210`, 2026-07-02

## Decisions taken

1. **Audit rows are written from a dedicated short-lived session, per
   invocation** — the `safe_record_security_event_committed` pattern
   (`services/security/events.py:67-80`), not the run's session. Two reasons:
   `execute_run` deliberately holds **no open transaction while streaming**
   (pinned by `test_runtime_core.py`), and a tool-call audit row must survive
   a run that crashes mid-turn. Audit failures never fail the tool call
   (fire-and-forget with a logged warning).
2. **Audit rows carry an input digest, not raw args.** `details` gets
   `{"args_sha256": …, "args_bytes": …}` — the conversation transcript
   already stores full tool args; duplicating them into audit rows doubles
   the sensitive-data surface for zero debugging value. (Resolves the gaps-doc
   question "input digest or redacted summary?" in favor of digest-only v1.)
3. **Envelope semantics for scheduled runs: keep the pause.** Approval flows
   already mirror correctly end-to-end (finalize/reconcile → `awaiting_approval`
   → resume in conversation). The envelope's job on scheduled runs is not to
   deny writes, it is to make the grant explicit: server-constructed from
   `run.trigger`, never from anything client-supplied. `side_effect_policy`
   exists in the envelope so 029/041 can tighten specific principals later
   without redesign.
4. **Delegated runs get a real envelope**: the child cannot re-delegate
   (already true via trigger, now explicit as `max_delegation_depth`), and
   `delegation_depth` is finally **bounded** — the cap closes the
   tracked-but-never-checked gap. Default cap 1 (current de-facto behavior).
5. **Enforcement point: lifecycle hooks if 2.1.0 exposes a tool-execution
   hook, otherwise a wrapper toolset.** The repo digest
   (`docs/pydantic-ai/04`, lines 403–412) prescribes an always-loaded `Hooks`
   capability with `before_tool_execute` as the permission gate; Step 1
   probes the installed package the way plan 018 did and records the real
   API in code. Hooks are preferred because they also cover the
   runtime-injected delegation tools without wrapping them individually.
6. **New enum members**: `AuditResourceType.AGENT_RUN = "agent_run"` (the
   resource a tool call belongs to), `AuditAction.EXECUTE` reused (exists).
   Actor is `AuditActorType.AGENT` with `requested_by_user_id` = the run's
   user — "the agent did it, on this user's behalf" is the shape the viewer
   (023) renders.

## Why this matters

This is the plank the whole harness stands on: after this plan, **every**
tool invocation — demo tool, delegation tool, and every future file /
integration / KB / memory / artifact tool — produces an audit row with
workspace, agent, run, tool name + provider, digest, outcome, latency, and
approval linkage, and executes inside an explicit server-minted grant.
Gate G1 and the 041 "Google Ads write ops must be approval-gated even on
schedules" requirement are unenforceable without it. It also closes two real
holes found in review: unbounded `delegation_depth`, and audit silence on
tool execution.

## Current state

- Turn driver: `services/agents/runtime/execute_run.py` `execute_run(...)`
  (lines 67–307) — builds the agent (143), builds `RuntimeDeps` (159–168),
  streams via `run_stream_events` (177–185), persists
  `DeferredToolRequests` suspensions (216–235). **No per-tool audit
  anywhere**; the only per-tool observability is a logging-only `Hooks` in
  `runtime/capabilities.py`.
- `RuntimeDeps` (`runtime/context.py`): frozen dataclass `db, user,
  workspace, conversation, agent, run, sink, delegation_depth=0`.
- Delegation (`runtime/delegation/`): child runs re-enter `execute_run` with
  `trigger="delegated"`, `delegation_depth=parent+1` (`delegate_to_agent.py`
  109–124); **only restriction** is `enable_delegation = run.trigger !=
  RUN_TRIGGER_DELEGATED` (`execute_run.py:135`); depth is never bounded.
  Child approvals bubble via `ApprovalRequired(metadata=...)`
  (`delegation/approvals.py:23-41`).
- Scheduled runs: same `execute_run`, `trigger="scheduled"`; an
  approval-required tool suspends the run and the schedule run mirrors
  `awaiting_approval` (`finalize_schedule_run_execution.py:72-76`);
  reconcile propagates late outcomes. Delegation is currently **enabled**
  for scheduled runs.
- Audit: `audit_events` has **no `tool_name`/`tool_provider` columns**
  (`models/audit_event.py` — full column list in plan 023). Writer:
  `safe_record_operation_audit_event` (savepoint, swallows errors); the
  committed-own-session variant exists only on the security side
  (`services/security/events.py:67-80`).
- Contract after 025: `RuntimeToolDefinition` carries `provider`, `effect`
  (`read|write`), `output_model` (declared, unenforced), and
  `RUNTIME_TOOL_CATALOG` + `is_tool_allowed` exist.
- pydantic-ai 2.1.0: hooks are composed via `capabilities=[Hooks(...)]`
  (`build_runtime_capabilities`); the digest documents `before_tool_execute`
  as the gate (`docs/pydantic-ai/04:403-412`) — **exact hook names/signatures
  must be probed, not assumed** (that file also documents `ctx.tool_call_
  approved`/`ctx.tool_call_metadata` used by delegation resume).
- Migrations: two Alembic branches; audit table lives in `core`
  (`0001_create_core_schema.py:320`).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| New migration | `uv run alembic revision --autogenerate --head core@head --version-path alembic/versions/core -m "add tool columns to audit events"` | one revision, two add_column + one index |
| Apply | `uv run alembic upgrade heads` | exit 0 |
| Migration sanity | `uv run alembic check` | no further operations |
| Probe | `uv run python -c "import pydantic_ai, inspect; ..."` (Step 1) | recorded hook signatures |
| Tests | `uv run pytest tests/services/agents/runtime tests/services/agent_schedules -q` | all pass |

## Scope

**In scope:**

- `apps/api/models/audit_event.py` + one `core` migration (`tool_name`
  String(100) nullable indexed, `tool_provider` String(50) nullable;
  composite index `(workspace_id, tool_name, occurred_at)`)
- `apps/api/services/audit_events/enums.py` (`AGENT_RUN` resource type)
- `apps/api/services/audit_events/tool_events.py` (create — the committed
  own-session writer `record_tool_invocation_audit_event`)
- `apps/api/services/agents/runtime/envelope.py` (create — `RunEnvelope` +
  `build_run_envelope(run)`)
- `apps/api/services/agents/runtime/context.py` (add `envelope` field)
- `apps/api/services/agents/runtime/dispatch.py` (create — the choke point:
  digesting, timing, envelope checks, output-contract validation, mutation
  tracking, audit emission)
- `apps/api/services/agents/runtime/capabilities.py` (wire the hooks) or the
  wrapper-toolset fallback in `runtime/tools/registry.py` (Step 1 decides)
- `apps/api/services/agents/runtime/execute_run.py` (construct envelope into
  deps; no other changes)
- `apps/api/services/agents/runtime/delegation/delegate_to_agent.py`
  (depth-cap check against the envelope)
- Tests: `tests/services/agents/runtime/test_dispatch.py` (create),
  extensions to `test_delegation.py`, `tests/services/agent_schedules/`
  regression run

**Out of scope (do NOT touch):**

- The contract/catalog/read API — 025 owns them; if a field is missing here,
  STOP and report rather than extending the contract ad hoc.
- Frontend — the audit viewer picks up `tool_name`/`tool_provider` as
  additive filter/columns in plan 027's frontend batch.
- Changing scheduled-run approval semantics (decision 3 keeps the pause).
- Retry/timeout behavior of tools (pydantic-ai owns it; 010 covered
  transport).
- OTel spans — plan 014 (it should wrap the same dispatch seam; leave a
  named hook point comment for it).

## Git workflow

- Branch: `advisor/026-dispatch-choke-point`
- Commit style: `API - Add Tool Dispatch Audit & Run Envelopes`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Probe the hook surface (no production code yet)

Write a throwaway script (scratch, not committed) that inspects the
installed `pydantic_ai` 2.1.0 `Hooks` capability: list the `hooks.on.*`
decorator names and the exact signature of the tool-execution hooks
(names like `before_tool_execute` / `after_tool_execute` per the digest —
verify, do not assume). Confirm: (a) the hook receives the tool name, args,
and `RunContext` (so `ctx.deps` reaches `RuntimeDeps`); (b) raising/returning
from the before-hook can block execution with a model-visible message;
(c) hooks fire for tools passed via `tools=[...]` (not only toolsets).

Record the findings as a comment block at the top of `dispatch.py`. If no
tool-execution hook exists in 2.1.0, fall back to a wrapper toolset
(`WrapperToolset.call_tool` per `docs/pydantic-ai/03:217`) wrapping the list
`build_runtime_tools` returns — same dispatch functions, different mounting.

**Verify**: findings recorded; decision (hooks vs wrapper) written down
before Step 4.

### Step 2: Migration + enums + writer

- Model: add `tool_name = Column(String(100), nullable=True, index=True)`
  and `tool_provider = Column(String(50), nullable=True)` to `AuditEvent`,
  plus `Index("ix_audit_events_workspace_tool_occurred", "workspace_id",
  "tool_name", "occurred_at")`. Autogenerate the `core` migration; inspect
  it by hand (two columns, indexes, nothing else).
- `AuditResourceType.AGENT_RUN = "agent_run"` (string enum, no migration).
- `services/audit_events/tool_events.py`:

  ```python
  async def record_tool_invocation_audit_event(*, workspace_id, agent, run,
      tool_name, tool_provider, status, args_sha256, args_bytes, latency_ms,
      outcome, approval_ref=None, error_code=None) -> None
  ```

  Opens its own session via `get_async_db_session_factory()`, commits
  independently, swallows + logs all exceptions (decision 1; model the body
  on `safe_record_security_event_committed`). Fields map: action `EXECUTE`,
  resource_type `AGENT_RUN`, resource_id `run.id`, actor_type `AGENT`,
  actor_id/`actor_display` from the agent, `requested_by_user_id` from the
  run's user, `workspace_id`, `tool_name`, `tool_provider`,
  `status` (`success|failure|denied`), details
  `{args_sha256, args_bytes, latency_ms, outcome, approval_ref, error_code}`.

**Verify**: `uv run alembic upgrade heads` then `uv run alembic check` →
clean; `uv run ruff check .` → exit 0.

### Step 3: `RunEnvelope`

`runtime/envelope.py`:

```python
@dataclass(frozen=True)
class RunEnvelope:
    principal: Literal["interactive", "scheduled", "delegated"]
    side_effect_policy: Literal["allow", "require_approval", "deny"] = "allow"
    max_delegation_depth: int = 1
```

`build_run_envelope(run) -> RunEnvelope` derives **only from server state**
(`run.trigger`, `run.delegation_depth`): interactive → `allow`; scheduled →
`allow` (decision 3 — approval-required tools already pause; the field is
the future tightening seam); delegated → `allow` with the parent's depth
context. Add `envelope: RunEnvelope` to `RuntimeDeps` (constructed in
`execute_run` next to the existing deps build at lines 159–168).

In `delegate_to_agent.py`, before creating the child run: if
`ctx.deps.envelope.max_delegation_depth <= ctx.deps.delegation_depth`,
return a typed tool error ("delegation depth limit reached") instead of
delegating — this replaces the implicit trigger-only guard as the bound
(keep the trigger guard; the envelope is the explicit law, the trigger check
is defense in depth).

**Verify**: `uv run pytest tests/services/agents/runtime/test_delegation.py -q`
→ existing tests pass (cap 1 == current behavior).

### Step 4: The dispatch choke point

`runtime/dispatch.py` — pure functions the hook (or wrapper) calls:

- `digest_args(args) -> tuple[str, int]` — sha256 over canonical
  (sorted-keys, compact) JSON; non-serializable values via `default=str`.
- `check_envelope(definition, deps) -> str | None` — returns a denial
  message when `definition.effect == "write"` and
  `deps.envelope.side_effect_policy == "deny"` (no principal hits this
  today; the seam is the point). Unknown tools (not in the catalog — e.g.
  delegation tools) are treated as `effect="execute"`-class: audited, never
  envelope-denied here (their own guards apply).
- `validate_output(definition, result)` — when `output_model` is set,
  `model_validate` the result. On failure: for `effect="read"` raise
  `ModelRetry` naming the schema mismatch; for `effect="write"` raise
  `ModelRetry` whose message **leads with the mutation warning**: "the
  external action may have completed — verify before retrying" (donor
  mutation-tracker rule), and the audit outcome becomes
  `"unverified_mutation"`.
- `record_invocation(...)` — assembles and fires the Step 2 writer with
  outcome ∈ `completed | failed | denied_envelope | denied_approval |
  unverified_mutation` and status mapped success/failure/denied.

Mount per Step 1's decision: an always-loaded hooks capability in
`build_runtime_capabilities` — before-hook stamps start time on the hook
context and enforces `check_envelope`; after/error hooks compute latency,
run `validate_output`, and call `record_invocation`. Approval-denied tool
results (user denials on resume) must also produce an audit row with
`denied_approval` — locate where denials re-enter execution
(`deferred_tool_results` replay in `execute_run`) and confirm the hook fires
for them; if pydantic-ai skips hooks for denied calls, write that row from
the resume path in `execute_run` instead (record which path you took).

Tool name → definition lookup goes through `RUNTIME_TOOL_CATALOG.get(name)`;
delegation tools resolve `provider="delegation"`, `tool_provider` recorded
accordingly.

**Verify**: `uv run ruff check .` → exit 0.

### Step 5: Tests

`tests/services/agents/runtime/test_dispatch.py` (use `FunctionModel`/
`TestModel` like `test_runtime_core.py`; audit assertions query
`audit_events` through the test session factory — remember the writer
commits on its **own** session, so use the committed-session fixtures
(`committed_db_session_factory`) the way lock tests do):

- happy path: one tool call → one audit row with tool_name/provider, digest
  matches locally computed sha256, `args_bytes` right, latency > 0, status
  success
- raw args never appear in `details` (assert the serialized row does not
  contain a marker argument value)
- tool raising → status failure + error_code; run continues per existing
  retry semantics
- write-tool with `output_model` and a bad return → `ModelRetry` with the
  mutation warning + `unverified_mutation` audit outcome; read-tool bad
  return → plain schema retry
- envelope: a definition with `effect="write"` under a forced
  `side_effect_policy="deny"` envelope → model-visible denial +
  `denied_envelope` audit row, tool function NOT executed
- audit writer failure (monkeypatch the session factory to raise) → tool
  call still succeeds; warning logged
- delegation: depth cap reached → typed error, no child run created
  (extend `test_delegation.py`); delegated child's tool calls produce audit
  rows attributed to the child run
- scheduled regression: `tests/services/agent_schedules` suite green —
  approval-required tools still pause (decision 3)

**Verify**: `uv run pytest tests/services/agents/runtime tests/services/agent_schedules -q`
→ all pass; full suite `uv run pytest -q` → no regressions elsewhere.

## Test plan

Covered by Step 5 (~14–18 tests). The two invariants that must be pinned
hardest: (1) audit failure never breaks a tool call; (2) no behavior change
for existing interactive/scheduled/delegated flows except the new depth
bound (which matches current de-facto depth).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] Migration applied; `uv run alembic check` clean; downgrade tested once
      (`alembic downgrade -1` then `upgrade heads`)
- [ ] `uv run pytest tests/services/agents/runtime tests/services/agent_schedules -q` exits 0
- [ ] `uv run pytest -q` exits 0 (full suite)
- [ ] A manual dev-run of a conversation with `get_runtime_context` shows an
      `EXECUTE`/`agent_run` audit row with populated `tool_name`
- [ ] Step 1 findings recorded in `dispatch.py`'s header comment
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 025 is not DONE (contract fields missing).
- Step 1 finds neither a tool-execution hook nor a workable wrapper-toolset
  seam that covers `tools=[...]`-mounted tools — the mounting strategy is
  then an architecture question, not an executor call.
- Hooks do not receive `RunContext.deps` (envelope enforcement has no data
  path).
- `test_runtime_core.py`'s no-open-transaction-while-streaming test fails
  with the own-session writer — the session lifecycle assumption broke.
- Autogenerate produces anything beyond the two columns + indexes.
- Existing delegation tests fail before your changes.

## Maintenance notes

- Plan 014 (OTel) should wrap the same `dispatch.py` seam — one span per
  invocation with the same attributes as the audit row. Do not let it grow a
  second interception layer.
- Plan 041 (Google Ads et al.) relies on: write tools declaring
  `effect="write"` + `output_model`, envelope enforcement on non-interactive
  principals, and `denied_approval` audit rows. Its "spend ops pause on
  schedules for human approval" is decision 3 + tool policy — no new
  mechanism.
- Plan 029 (governance note) may tighten `side_effect_policy` defaults per
  principal; the envelope is the only place that changes.
- The audit viewer (023) gains `tool_name`/`tool_provider` filter + columns
  — fold into plan 027's frontend batch (its types file mirrors the enums).
- Delegation depth cap is envelope-owned now; if the product ever wants
  depth 2, change `build_run_envelope`, not the delegation code.
- Reviewers should scrutinize: the own-session writer (no leaked sessions,
  no writes on the run session), digest-only details, hook coverage of
  delegation tools, and that denied paths still audit.
