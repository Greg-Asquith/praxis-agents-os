# Plan 066: Decompose `execute_run` into named phases behind characterization tests

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat d326b68..HEAD -- apps/api/services/agents/runtime/execute_run.py apps/api/tests/services/agents/runtime/`
> If `execute_run.py` changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. This file is the highest-churn
> runtime module and pending roadmap plans (053 cancellation, 054 envelopes,
> 056 compaction) all touch it — this plan must run BEFORE those.

## Status

- **Priority**: P1 (sequenced before roadmap plans 053/054/056)
- **Effort**: M
- **Risk**: MED (core streaming/approval control flow; mitigated by characterization-first)
- **Depends on**: 062 (soft — local DB-backed test running)
- **Category**: tech-debt
- **Planned at**: commit `d326b68`, 2026-07-07

## Why this matters

`execute_run` in `services/agents/runtime/execute_run.py` is a single
~286-line async function (lines 85–371) that owns precondition validation,
lease start, attachment prompt assembly, delegation wiring, the streaming
event loop, suspension/success/failure persistence, and SSE terminal-event
emission. It is the second-highest-churn file in the runtime, and three
pending roadmap plans (cooperative cancellation, envelope enforcement,
context compaction) will each modify it. Every change currently requires
re-reading one deeply nested function; sub-phases cannot be unit-tested in
isolation. Decomposing it into named same-module helpers — with the
transaction boundaries and event ordering pinned by tests first — makes the
subsequent runtime work cheaper and safer.

Deliberately NOT in this plan: splitting
`services/agents/runtime/dispatch.py`. That was audited and rejected — it is
a cohesive choke point whose module docstring pins the "wrap this module,
don't add layers" contract that the OTel plan (014) and envelope plan (054)
build on, and its `OutputContractError` is an internal `ModelRetry` signal,
not an HTTP-facing exception. Leave it alone.

## Current state

- File: `apps/api/services/agents/runtime/execute_run.py` (381 lines).
  `execute_run(db, *, conversation_id, run_id, user_prompt,
  attachment_file_ids, sink, model, client_message_id, owner_instance_id,
  expected_status, message_history, deferred_tool_results, usage)
  -> ExecuteRunResult` at line 85; the only other symbol is
  `_has_delegated_deferred_results` at line 371.
- Its docstring is a load-bearing contract — preserve verbatim:

  ```
  This function owns the run lifecycle transaction boundaries: it commits the
  running+lease state before provider streaming, commits final
  messages/usage/status after the stream, and commits failures before
  re-raising so rollback-based dependencies do not erase diagnostic state.
  ```

- Internal phases as they exist today (line ranges at the planned-at commit):
  1. **Load + validate** (111–144): `load_run_context` (with `lock_run=True`),
     `load_agent_skills`, `load_available_files`, then three `ConflictError`
     precondition checks (unexpected status; no prompt and no deferred
     results; deferred results without message history).
  2. **Start** (146–153): `start_agent_run_with_lease` → `db.commit()` →
     `started = True` → emit `EVENT_RUN_STATUS` running.
  3. **Prompt assembly** (155–170): `load_actor_context`, then attachment
     resolution (`resolve_chat_attachments` + `build_attachment_user_content`)
     appending to `user_prompt` (str → list promotion).
  4. **Agent build** (171–196): delegation visibility, the
     `force_delegation_tools` flag from `_has_delegated_deferred_results`,
     `build_runtime_agent`, `run.model_name` backfill, history load,
     `db.commit()`.
  5. **Deps + denied-approval audit** (197–218): `RuntimeDeps(...)`,
     `record_denied_approval_audit_events` when resuming,
     `EventTranslationState()`, `deferred_tool_call_ids`.
  6. **Stream loop** (220–263): `run_stream_events(...)` context manager;
     per-event handling — capture `AgentRunResultEvent`, skip deferred-resume
     echoes, track `NativeToolCallPart`/audit `NativeToolReturnPart`, record
     skill activation for `capability-load` calls, forward everything through
     `emit_agent_stream_event`; then the "stream ended without a terminal
     result" `RuntimeError`.
  7. **Suspension path** (265–296): `emit_deferred_tool_resume_events`,
     `persist_suspended_run`, `emit_approval_required_events`, run-status +
     done events, early return.
  8. **Success path** (298–335): `build_deferred_tool_result_metadata`,
     `persist_successful_run`, status-dependent status/error/done emission,
     return.
  9. **Failure path** (336–366): `except Exception` → `db.rollback()` → if
     `started`, `persist_failed_run` + status/error/done emission, else
     error+done emission without a status event → re-raise; `finally:
     await event_sink.close()`.
- Existing tests: `tests/services/agents/runtime/test_runtime_core.py`
  (provider-free via `FunctionModel`/`TestModel`, asserts sink event
  sequences, suspension, completion, failure) and
  `tests/routes/conversations/test_turn_streaming.py` (SSE surface). DB-backed
  (skip without `TEST_DATABASE_URL`); async tests need no markers
  (`asyncio_mode = "auto"`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Runtime suite | `cd apps/api && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run pytest tests/services/agents/runtime -q` | all pass |
| Streaming routes | `... uv run pytest tests/routes/conversations -q` | all pass |
| Full suite | `... uv run pytest` | exit 0 |
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |

## Scope

**In scope**:

- `apps/api/services/agents/runtime/execute_run.py`
- `apps/api/tests/services/agents/runtime/test_execute_run_phases.py` (create)

**Out of scope** (do NOT touch):

- `services/agents/runtime/dispatch.py` (rejected split — see "Why this
  matters").
- `services/agents/runtime/loop.py`, `run_persistence.py`,
  `approval_events.py`, `events.py`, sinks, delegation — call them, don't
  change them.
- No behavior changes of any kind: same events in the same order, same
  commits at the same points, same exceptions, same return values.
- No new files for the helpers — they stay private in `execute_run.py`
  (splitting into submodules would churn imports that plans 053/054/056
  already anchor on).

## Git workflow

- Work on `main` unless told otherwise; two commits (tests, then refactor);
  style: `API - Execute Run Decomposition`.
- Do NOT push unless instructed.

## Steps

### Step 1: Characterization tests for the under-pinned paths

Read `test_runtime_core.py` first and reuse its fixtures/harness style
(FunctionModel-driven agents, recording sink). Add
`test_execute_run_phases.py` covering the gaps — skip any case
`test_runtime_core.py` already asserts (check before writing; duplicating is
noise):

1. **Pre-start failure emits no run-status event**: call `execute_run` with
   `expected_status` mismatching the run's status → `ConflictError` raised,
   sink received `EVENT_ERROR` then `EVENT_DONE` with failed status, and NO
   `EVENT_RUN_STATUS` (the `started = False` branch).
2. **Precondition trio**: no prompt + no deferred results → `ConflictError`;
   deferred results without history → `ConflictError`.
3. **Post-start failure ordering**: a run that fails mid-stream emits
   `EVENT_RUN_STATUS` (failed) → `EVENT_ERROR` → `EVENT_DONE`, and the run row
   persists `error_code`/`error_message` (rollback-then-persist contract).
4. **Attachment prompt promotion**: with `attachment_file_ids` and a string
   prompt, the model receives a list `[prompt, *attachment_contents]` (drive
   through FunctionModel capture; use the file factories from
   `tests/factories/files.py`).
5. **Sink always closes**: assert the recording sink is closed on success and
   on failure.

**Verify**: new tests pass against the UNMODIFIED `execute_run.py`:
`uv run pytest tests/services/agents/runtime/test_execute_run_phases.py -q`.

### Step 2: Extract the phase helpers

Refactor `execute_run` into private same-module helpers matching the phase
map above. Target shape (signatures indicative — keep them minimal and typed):

```python
def _validate_execution_preconditions(run, *, user_prompt, message_history, deferred_tool_results, expected_status) -> None
async def _assemble_user_prompt(db, *, workspace, agent, user_prompt, attachment_file_ids) -> str | Sequence[UserContent] | None
async def _build_agent_for_run(db, *, run, agent, workspace, model, deferred_tool_results, skills, available_files)  # returns the runtime agent + delegate wiring
async def _consume_stream(stream, *, deps, state, skills, run, deferred_tool_results, deferred_tool_call_ids, event_sink)  # returns terminal_result
async def _finalize_suspended(db, *, event_sink, conversation, run, terminal_result, client_message_id) -> ExecuteRunResult
async def _finalize_success(db, *, event_sink, conversation, run, terminal_result, client_message_id, history, deferred_tool_results) -> ExecuteRunResult
async def _emit_failure_events(event_sink, *, started, run_id, exc, db) -> None  # the except-block body
```

Hard requirements:

- `execute_run` keeps its public signature, docstring, and the
  try/except/finally skeleton; the helpers are called in the same order with
  the same `await db.commit()` placement (commits may live inside helpers, but
  each must execute at the exact same point in the flow as today).
- `_consume_stream` owns only the `async for` body; the
  `async with ... run_stream_events(...)` context manager stays in
  `execute_run` (its parameters are the resume seam plan 053 will need).
  If threading state makes this awkward, an inner function in `execute_run`'s
  scope is acceptable — prefer module-level helpers where clean.
- No behavior branch is added, removed, or reordered. The diff should read as
  pure extraction.
- Match the repo's terse single-line comment style; do not narrate the
  refactor in comments.

**Verify**: `uv run pytest tests/services/agents/runtime tests/routes/conversations -q`
→ all green with zero assertion changes; `uv run ruff check .` exits 0.

### Step 3: Full-suite confirmation

**Verify**: full `TEST_DATABASE_URL=... uv run pytest` exits 0, and
`uv run ruff format --check .` exits 0. Confirm
`grep -c "" apps/api/services/agents/runtime/execute_run.py` shows the file
did not grow by more than ~40 lines (helper signatures) and `execute_run`
itself is under ~120 lines
(`sed -n '/^async def execute_run/,/^async def \|^def /p' ... | wc -l` or
equivalent).

## Test plan

Step 1 is the test plan: 5 characterization cases in
`test_execute_run_phases.py`, modeled on `test_runtime_core.py`, all passing
before AND after the refactor with unchanged assertions.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `test_execute_run_phases.py` exists with the 5 cases (minus any proven duplicates, named in your report) and passes
- [ ] Full `TEST_DATABASE_URL=... uv run pytest` exits 0
- [ ] `execute_run` body ≤ ~120 lines; helpers are private (`_`-prefixed), same module
- [ ] Public signature and docstring of `execute_run` unchanged (`git diff` shows no edit to either)
- [ ] `dispatch.py` untouched (`git diff --stat` confirms)
- [ ] Status row updated in `docs/plans/000_README.md`

## STOP conditions

Stop and report back (do not improvise) if:

- Any existing runtime/streaming test fails after extraction — event order or
  commit placement changed; revert the offending extraction rather than
  editing the test.
- The characterization tests fail on the UNMODIFIED file (current behavior
  differs from this plan's phase map — the file drifted).
- Extraction requires changing `RuntimeDeps`, sink interfaces, or any
  imported runtime module.
- Plans 053/054/056 have already landed changes that restructured this file
  (check `docs/plans/000_README.md` statuses) — re-anchor with the operator
  instead of merging blind.

## Maintenance notes

- Plans 053 (cancellation), 054 (envelope enforcement), and 056 (compaction)
  edit this file next; the phase helpers give each a named seam
  (cancellation → the stream context/loop; envelopes → deps construction;
  compaction → history load in agent build). Reviewers of those plans should
  reject re-inlining.
- The reviewer of THIS change should scrutinize: commit placement (three
  commits: post-lease, post-agent-build, inside persist helpers), the
  `started` flag semantics in the failure path, and that suspension still
  early-returns before the success path's metadata build.
- Do not reference this plan number from implementation code or docstrings
  (AGENTS.md rule).
