# Plan 073: Cancellation hardening — shielded terminal persistence and in-flight tool disposition (amendment to 053)

> **Executor instructions**: This is an amendment plan in the 061 mold —
> its deliverable is the amendment block below, appended verbatim to
> `docs/plans/053-cooperative-run-cancellation.md`, plus the README row.
> No code lands here; the code cost is absorbed into 053's execution.
> When done, update the status row in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff c770a1c..HEAD -- docs/plans/053-cooperative-run-cancellation.md`
> and check 053's status row in `docs/plans/000_README.md`. If 053 has
> already executed (status not TODO, or its scope files show landed cancel
> code), STOP — reconcile against the landed code instead of amending a
> plan that no longer binds anyone.

## Status

- **Priority**: P1
- **Effort**: S (one amendment block + README row; the code delta rides
  inside 053's existing steps)
- **Risk**: LOW as a doc; it *removes* risk from 053's terminal-status
  guarantee before any cancellation code exists
- **Depends on**: 053 (written, TODO). **Binds before 053 executes** — and
  053 is early in the execution order, immediately after Lane Q, so this
  amendment is time-sensitive and must land promptly
- **Category**: Lane B — best-practice amendments (067–074, added
  2026-07-07)
- **Planned at**: working tree at commit `c770a1c`, 2026-07-07

## Decisions taken

1. **053's "no shield needed" claim does not survive its own design.**
   053 decision 1 delivers cancel through two tiers: tier 1 is the
   route-path `RunTaskRegistry.cancel(run_id)`, tier 2 is heartbeat
   cancel-detection after a failed lease renewal. Both target the same
   task with no dedupe, so a tier-2 beat can land a second
   `CancelledError` while the tier-1 unwind is mid-cleanup. 053 decision 3
   acknowledges this exactly — "awaits proceed normally unless a second
   cancel arrives, so no `asyncio.shield` is needed" — and leaves the
   cleanup unprotected: in the step-4 snippet the SSE emits sit under
   `with suppress(Exception)`, which does **not** suppress
   `CancelledError` (a `BaseException`), and
   `await persist_cancelled_run(run_id)` is bare. A second cancel there
   kills the terminal write, downgrading "the row is terminal `cancelled`
   and the stream ends with `done {cancelled}`" from guaranteed to
   eventual (reaper backstop, minutes later, with a hung client stream).
2. **Fix both the cause and the guarantee.** (b) Tier-2 dedupe: the
   heartbeat skips delivery when the task is already done or already has
   a cancel in flight (`cancel_target.done() or
   cancel_target.cancelling()`, stdlib since 3.11) — removing the common
   double-cancel source with zero shared state. (a) Shielded
   finalization: terminal persistence *and* terminal event emission run
   inside `asyncio.shield` with a bounded timeout, so even an undeduped
   second cancel (racing beat, duplicate route call) cannot kill the
   terminal write. (b) alone is probabilistic; (a) alone leaves the hot
   path taking avoidable double deliveries. A registry-side
   delivered-flag was rejected for (b): `Task.cancelling()` carries the
   same information without new registry state.
3. **The interrupted tool call gets a terminal audit disposition.** 053's
   own motivation is stopping money-spending tools, yet cancelling
   mid-dispatch interrupts a tool between issuing an external side effect
   and recording its outcome, and today no audit row exists at all:
   `dispatch_tool_execution` catches `ApprovalRequired` and `Exception`
   only (`dispatch.py:165-197`); `CancelledError` escapes both. Minimum
   viable fix: an `except asyncio.CancelledError` branch in the dispatch
   choke point best-effort records the per-invocation audit row (the 026
   choke point already computes `args_sha256`/`args_bytes` at entry and
   writes rows in an independent committed session that never raises)
   with a new terminal outcome `cancelled`, then re-raises. Operators can
   then reconcile external state from the audit trail: which tool, which
   args digest, interrupted when.
4. **Compensation is out of scope.** Automatic compensation/cleanup hooks
   for interrupted external writes are the deferred end-state, owned by
   the integration-tool plans — this amendment only guarantees the
   *record* that reconciliation needs.
5. **First-turn user-message loss becomes decided behavior.** 053
   decision 5 states the loss outright ("a cancelled first turn shows the
   user message absent") and punts it to STOP condition 3 ("record it and
   ask whether to persist the prompt eagerly"). Since the user prompt
   persists only from terminal `new_messages()` handling
   (`execute_run.py:103-104`), the loss is certain, not hypothetical.
   Decision: persist the user message eagerly in the turn-start commit,
   with terminal persistence skipping the already-persisted prompt; if
   that dedupe cannot be expressed cleanly, STOP and report rather than
   double-writing.

## Why this matters

053's product promise is "a cancelled run persists as `cancelled`, never
`failed`, and its SSE stream terminates with the existing events". The
double-cancel window makes that promise conditional on delivery timing —
a rare, unreproducible lifecycle bug that erodes trust in the kill
switch. And the kill switch exists *because* of external side effects; a
design that can interrupt an external write while leaving no record of
which tool was interrupted defeats its own purpose. Both fixes are a few
lines each when written into 053's steps now, and a forensic debugging
session each if discovered after 041 ships spend-class tools.

## Current state

All anchors verified on the working tree at `c770a1c` (2026-07-07); 053 is
written and TODO, so every anchor is pre-cancellation code.

- **053 step-4 snippet**: emits guarded by `with suppress(Exception)`;
  `persist_cancelled_run` awaited bare; handler re-raises. 053 decision 3
  text: "so no `asyncio.shield` is needed".
- **053 decision 1**: tier 1 `RunTaskRegistry.cancel(run_id)` from the
  cancel service; tier 2 heartbeat cancel-detection on failed renewal.
  No dedupe between tiers is specified anywhere in 053.
- **Dispatch**: `dispatch_tool_execution` (`dispatch.py:131-231`) computes
  `args_sha256, args_bytes = digest_args(args)` at entry; `await
  handler(args)` is wrapped by `except ApprovalRequired` and
  `except Exception` only. `ToolAuditOutcome` (`tool_events.py`) has no
  cancelled/interrupted member; `record_tool_invocation_audit_event`
  opens its own session and swallows its own failures
  (`tool_events.py:96`).
- **User prompt persistence**: `execute_run.py:103-104` — "The user prompt
  is persisted from Pydantic AI's `new_messages()`; callers must not
  insert a separate user message for the same turn." The turn-start
  commit (the `started` flag, `execute_run.py:151-152`) is the natural
  eager-persist seam.
- **Heartbeat**: `heartbeat_agent_run_lease` (`heartbeat.py:39-70`) has no
  `cancel_target` yet — 053 step 3 adds it; the dedupe amends that step,
  not landed code.

## Scope

**In scope:**

- `docs/plans/053-cooperative-run-cancellation.md` (append the amendment
  block below, verbatim)
- `docs/plans/000_README.md` (row for 073; note on 053's row that 073
  amends it)

**Out of scope:**

- Any code — every delta lands through 053's execution.
- Compensation hooks for interrupted external writes (decision 4).
- Partial assistant-message persistence (053 decision 5's follow-up
  stands unchanged).

## The amendment

Append to `docs/plans/053-cooperative-run-cancellation.md`:

```markdown
## Amendment (plan 073, 2026-07-07): terminal hardening

Binding deltas; where this section conflicts with the text above, this
section wins.

**Decision deltas**

- Decision 3's "no `asyncio.shield` is needed" is superseded. The
  cleanup's `suppress(Exception)` guards do not stop a second
  `CancelledError` (`BaseException`), and decision 1's two delivery
  tiers can double-deliver. Terminal persistence and terminal event
  emission are shielded (see step 4 below).
- Decision 1 gains tier dedupe: heartbeat cancel-detection must skip
  delivery when `cancel_target.done()` or
  `cancel_target.cancelling() > 0` — a task the registry already
  cancelled is not cancelled again.
- New decision: cancellation landing inside `dispatch_tool_execution`
  records a terminal audit row for the interrupted invocation. Add
  `"cancelled"` to `ToolAuditOutcome`; an
  `except asyncio.CancelledError` branch around `await handler(args)`
  best-effort records (status `FAILURE`, outcome `cancelled`,
  `error_code="CancelledError"`, the entry-computed args digest) under
  `suppress(BaseException)`, then re-raises. For write-effect tools the
  row is the reconciliation record — the external action may or may not
  have completed. Compensation hooks are explicitly deferred.
- Decision 5 delta / STOP condition 3 resolved: persist the user message
  eagerly in the turn-start commit (`started`, `execute_run.py:152`);
  terminal `persist_new_messages` skips the already-persisted prompt,
  and the `execute_run` docstring contract is updated to match.

**Step deltas**

- Step 3: apply the tier-dedupe check before `cancel_target.cancel()`.
- Step 4: replace the snippet's cleanup with a shielded finalizer:

      except asyncio.CancelledError:
          finalize = asyncio.ensure_future(
              _finalize_cancelled_run(db, run_id, event_sink)
          )
          try:
              await asyncio.shield(finalize)
          except asyncio.CancelledError:
              with suppress(BaseException):
                  async with asyncio.timeout(CANCEL_FINALIZE_TIMEOUT):
                      await finalize
          raise

  `_finalize_cancelled_run` owns the rollback, `persist_cancelled_run`,
  and the `run.status`/`done` emits, and never raises; the timeout
  (a few seconds) bounds the second-cancel wait so a stuck DB cannot
  block the unwind.
- Step 4 (dispatch): add the `except asyncio.CancelledError` audit
  branch and the `ToolAuditOutcome` member.
- Step 4 (messages): implement the eager user-message persist + terminal
  dedupe. If `new_messages()` shapes make the skip ambiguous, STOP and
  report (record deferral rather than double-writing).

**Test-plan deltas** (+3 on the estimate)

- Double-cancel: cancel a scripted run, deliver a second cancel while
  finalization is in flight (slow `persist_cancelled_run` fake); assert
  the row ends `cancelled` (never `failed`/stuck `running`) and the sink
  received `done {cancelled}`.
- Interrupted dispatch: cancel while a scripted tool sleeps inside its
  handler; assert one `tool_call` audit row with outcome `cancelled`,
  the tool name, and a non-empty `args_sha256`.
- First-turn cancel: cancel a first turn mid-stream; the user message is
  present in the conversation afterwards.
```

## Steps

1. Append the amendment block above to 053, verbatim, after its
   "Maintenance notes" section.
2. Update `docs/plans/000_README.md`: add the 073 row (P1 / S / depends
   053, binds before it executes / TODO→DONE on completion) and annotate
   053's row that 073 amends it.

## Done criteria

- [ ] 053 ends with the amendment block, character-identical to the
      fenced block in this plan
- [ ] 053's decision-3 "no shield" sentence is superseded in the
      amendment, not edited in place (history stays honest)
- [ ] `docs/plans/000_README.md` has a 073 row and 053's row references
      the amendment
- [ ] No code changed (`git diff --stat` touches only the two plan docs)

## STOP conditions

- 053 has started or finished executing (drift check) — reconcile with
  landed code; the shield/dedupe/audit deltas become a normal code plan.
- 053's text has materially changed since `c770a1c` such that the quoted
  decisions or the step-4 snippet no longer exist as described — re-verify
  before appending.

## Git workflow

- Branch: `advisor/073-cancellation-terminal-hardening`
- Commit: `Docs - Cancellation Terminal Hardening Amendment`
- Do NOT push or open a PR unless the operator instructed it.

## Maintenance notes

- **Plan 057 (parallel fan-out)** inherits the shielded-finalizer pattern:
  concurrent children each need their own terminal write protected the
  same way; its STOP list already re-verifies cancellation propagation.
- **Plan 041** should treat the `cancelled` audit outcome as part of its
  reconciliation story for spend-class tools — the row exists so an
  operator can check the provider side after a mid-write cancel.
- If `Task.cancelling()` proves unreliable under pydantic-ai's internal
  `uncancel()` usage (none observed at `c770a1c`), fall back to a
  registry-side delivered-flag for the dedupe and record the deviation —
  the shield still holds the guarantee either way.
