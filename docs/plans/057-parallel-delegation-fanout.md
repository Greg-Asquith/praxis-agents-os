# Plan 057: Parallel delegation fan-out (breadth, not depth)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/api/services/agents/runtime/delegation/ apps/api/services/agents/runtime/execute_run.py apps/api/services/agents/runtime/prompt.py apps/web/src/features/conversations/`
> Compare the "Current state" excerpts against live code; treat a mismatch
> in `delegate_to_agent`'s session/usage handling or the installed
> pydantic-ai tool-execution concurrency model as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (concurrency over shared seams: usage accounting, DB pool,
  multi-child approval suspension, cancellation propagation)
- **Depends on**: 054 (envelope inheritance — children of a fan-out must
  each inherit correctly), 055 (scenario suite — the concurrency claims
  below land as scenarios), 053 soft (cancellation propagation must be
  re-proven under fan-out, per 053's maintenance note).
- **Category**: Lane H — harness hardening (post-roadmap additions
  053–060, added 2026-07-07)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07

## Product intent

Decision taken with the operator (2026-07-07): **no deeper nesting —
`max_delegation_depth` stays 1 — but parallel fan-out at depth 1 should
work.** A primary agent researching across knowledge, files, and (post-041)
integrations should be able to delegate three independent subtasks in one
step and have them run concurrently, instead of serially awaiting each
child.

The mechanism already half-exists: the installed pydantic-ai 2.1.0
executes the tool calls of one model response **concurrently** (probe
recorded 2026-07-07: `pydantic_ai/_tool_execution.py:608-627` segments
calls by `sequential=True` barriers / the run-scoped
`parallel_execution_mode('sequential')`, then `asyncio.create_task`s each
call), and Praxis mounts `delegate_to_agent` without a `sequential` flag —
so two delegate calls in one response *already* run concurrently today,
un-designed, un-prompted, un-bounded, and un-tested. This plan turns that
accident into a contract: bound it, prove the shared seams safe, prompt
the model to use it, and render it sanely.

## Decisions taken

1. **Depth stays 1; breadth is the feature.** No change to
   `AGENT_MAX_DELEGATION_DEPTH` (054). A delegate agent still cannot
   delegate (`enable_delegation = run.trigger != RUN_TRIGGER_DELEGATED`
   remains). Fan-out means: multiple `delegate_to_agent` calls in one
   model response execute concurrently.
2. **Concurrency is bounded by a workspace-safe cap.** New setting
   `AGENT_DELEGATION_MAX_PARALLEL` (default 3). Enforced with an
   `asyncio.Semaphore` held in `RuntimeDeps`-scope (per parent run, minted
   in `execute_run`, not module-global — two simultaneous parent runs must
   not share a limiter). Calls beyond the cap queue on the semaphore
   rather than failing — the model sees normal (slower) results. Rationale
   for 3: each child opens its own DB session and provider stream; the
   default must stay well inside the SQLAlchemy pool and provider
   rate-limit envelope for a small deployment.
3. **Shared usage accounting is verified, not assumed.** Children pass
   `usage=ctx.usage` (`delegate_to_agent.py:152`) so parent `UsageLimits`
   see aggregate spend. Under concurrency, `RunUsage` mutation happens
   from multiple tasks on one event loop — probe the installed
   implementation for non-atomic read-modify-write across awaits; record
   findings in the module docstring (the dispatch.py probe-note pattern).
   If unsafe, wrap increments behind a lock in our seam — do not fork
   pydantic-ai types.
4. **Multi-child approval suspension must collapse into one
   `DeferredToolRequests`.** Today a single child raising
   `ApprovalRequired` suspends the parent
   (`raise_delegate_approval_required`). With fan-out, two children may
   suspend in the same step; pydantic-ai collects deferred calls from
   parallel tools into one `DeferredToolRequests` output — verify against
   the installed package, and verify the resume path
   (`resume_approved_delegate_run` + `_has_delegated_deferred_results`)
   re-enters *both* children on one resume. The approval-state snapshot
   and `get_approval_state` projection already model lists of pending
   approvals (052 consumed them) — the UI contract should hold unchanged;
   pin it.
5. **Cancellation propagates to concurrent children.** pydantic-ai owns
   the child tasks (created in `_tool_execution`); cancelling the parent
   task must cancel them (structured-concurrency unwind through the tool
   gather). Prove it in a scenario (053's maintenance note assigns this
   here). If the installed version detaches tool tasks on cancel, add
   explicit child-run cancellation in `delegate_to_agent`'s
   `CancelledError` unwind (each child's `execute_run` already persists
   its own `cancelled` row per 053).
6. **The model is told it may fan out.** `DELEGATION_INSTRUCTIONS`
   (`prompt.py:19-28`) gains one rule: independent subtasks may be
   delegated in a single response and will run in parallel; dependent
   subtasks must be sequenced. No new tools — `list_delegate_agents` /
   `delegate_to_agent` are unchanged in schema.
7. **No fan-out orchestration API.** A "delegate_many" batch tool and a
   graph-based orchestrator were considered and rejected: parallel tool
   calls are the provider-native idiom, they keep approvals/audit
   per-child, and pydantic-graph remains available later for scheduled
   pipelines (docs digest 08) without a new runtime surface now.
8. **UI: concurrent delegation rows render independently.** The chat
   already renders one `DelegationToolRow` per tool call; concurrent
   children stream interleaved `tool.call`/`tool.result` events with
   distinct `tool_call_id`s over the existing protocol — no new SSE
   events. Verify interleaving renders correctly (rows keyed by call id,
   spinners resolve independently); fix key/ordering bugs if found, do
   not redesign the rows.

## Why this matters

Fan-out is the single biggest wall-clock lever for knowledge work once
children have real tools (041 integrations, 046 KB search): three
5-second lookups become one. It is also currently an *unmanaged* behavior
— a model that happens to emit two delegate calls today already runs them
concurrently against seams nobody has tested. Bounding and pinning it is
harness hardening as much as capability work.

## Current state

All anchors verified on the working tree at `c2f08cc` (2026-07-07).

- **Concurrent tool execution (installed package probe, 2026-07-07)**:
  `.venv/.../pydantic_ai/_tool_execution.py:608-627` — calls are
  segmented by barriers (`sequential=True` tools or
  `parallel_execution_mode('sequential')`); each non-barrier call runs in
  its own `asyncio.create_task`. Praxis sets no `sequential` flags
  anywhere (`grep sequential services/agents/runtime -r` → none).
- **Delegation tools**: `delegation/build_delegation_tools.py` — plain
  `Tool(...)` mounts, `delegate_to_agent` has `timeout=None`,
  `list_delegate_agents` `timeout=10`.
- **`delegate_to_agent`** (`delegation/delegate_to_agent.py`): depth check
  against the envelope (59-65); `ctx.tool_call_approved` resume shortcut
  (67-73); **fresh session per child** via `get_async_db_session_factory()`
  (75-76); child conversation `source=delegated` + child run
  `trigger=delegated, parent_run_id, delegation_depth+1` (93-135); own
  heartbeat task (138-141); `await execute_run(..., usage=ctx.usage)`
  (145-153); child `DeferredToolRequests` →
  `raise_delegate_approval_required` (155-161); errors return a bounded
  `DelegateRunResult` instead of raising (170-188).
- **Parent resume with delegated deferred results**:
  `execute_run.py:177-186` forces delegation tools to stay registered on
  resume (`_has_delegated_deferred_results`, 371-381);
  `resume_approved_delegate_run` re-enters the child.
- **Prompt guidance**: `prompt.py:19-28` — sequencing rules only; nothing
  about parallelism.
- **Envelope**: depth from `deps.envelope.max_delegation_depth`
  (054 moves the constant into settings; children inherit policy per
  054 decision 4).
- **Frontend**: delegation rows render per tool call
  (`message-parts/`-driven; `DelegationToolRow` branch landed with
  `603fff7`); the stream reducer keys parts by call id.
- **DB pool**: engine configured in `core/database.py` — check pool size
  vs `AGENT_DELEGATION_MAX_PARALLEL` × plausible concurrent parents and
  record the arithmetic in the plan-execution notes.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Focused tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agents/runtime tests/scenarios -q` | all pass |
| Full suite | `cd apps/api && TEST_DATABASE_URL=... uv run pytest -q` | all pass |
| Frontend gate | `cd apps/web && pnpm check` | all gates pass |
| Manual smoke | `make dev`; agent with 2+ delegates; prompt forcing two independent subtasks | both rows stream concurrently; results interleave |

## Scope

**In scope:**

- `core/settings/agents.py` (`AGENT_DELEGATION_MAX_PARALLEL`)
- `services/agents/runtime/execute_run.py` /
  `services/agents/runtime/context.py` (per-run semaphore in
  `RuntimeDeps`)
- `services/agents/runtime/delegation/delegate_to_agent.py` (semaphore
  acquisition around the child execution; concurrency probe notes;
  explicit child cancellation if decision 5's verification demands it)
- `services/agents/runtime/prompt.py` (`DELEGATION_INSTRUCTIONS` rule,
  decision 6)
- `tests/scenarios/test_delegation_fanout.py` (new scenario group) +
  runtime unit additions
- `apps/web` — only if decision 8's verification finds rendering bugs
  (keyed rows / interleaving); otherwise no frontend change

**Out of scope (do NOT touch):**

- Delegation depth, re-delegation, or agent-graph orchestration
  (decisions 1/7).
- The delegation tool schemas and the SSE protocol.
- Live child-transcript streaming into the parent conversation (children
  keep `NullSink`; their transcripts remain reachable via the delegated
  conversation link — a future UX plan may revisit).
- Provider `parallel_tool_calls` model-setting overrides (leave provider
  defaults; the semaphore is our control point).

## Git workflow

- Branch: `advisor/057-parallel-delegation-fanout`
- Commit: `API - Bounded Parallel Delegation Fan-Out`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: probes, recorded

Probe the installed pydantic-ai and record findings as a module-docstring
block in `delegate_to_agent.py` (the dispatch.py pattern):
(a) parallel tool tasks and barrier semantics (already captured above —
re-verify at execution time); (b) `RunUsage` mutation safety under
concurrent increments (decision 3); (c) multi-tool `ApprovalRequired`
collection into one `DeferredToolRequests` (decision 4); (d) parent-task
cancellation reaching child tool tasks (decision 5). Each probe is a
small throwaway script or a scenario-suite test — prefer tests that stay.

**Verify**: probe results written down; any ✗ answer routes to the STOP
list before code is written.

### Step 2: semaphore + setting

Per-run `asyncio.Semaphore(settings.AGENT_DELEGATION_MAX_PARALLEL)`
minted in `execute_run` into `RuntimeDeps`; `delegate_to_agent` wraps the
child block (session open → execute) in `async with`. The
resume shortcut path (approved replay) does not acquire — it re-enters an
existing child, not a new concurrent one; record why.

**Verify**: unit test — 5 scripted concurrent delegate calls, cap 2 ⇒
max 2 children in-flight (instrument with an event-recording fixture
agent), all 5 complete.

### Step 3: fan-out scenarios

Scenario group (055 suite): (a) two independent children run
concurrently and both results return to the parent turn; (b) two children
suspend on approval in one step ⇒ one `awaiting_approval` parent, both
pending approvals visible in approval-state, one resume approving both
re-enters both children; (c) parent cancel (053) mid-fan-out ⇒ parent +
both children `cancelled`; (d) usage: aggregate parent-visible tokens
equal the sum of scripted child usages (pins decision 3).

### Step 4: prompt rule + UI verification

Add the fan-out sentence to `DELEGATION_INSTRUCTIONS` (keep it two lines
max). Manual UI pass per decision 8; fix row-keying bugs only if found.

**Verify**: `pnpm check` (if web touched); manual smoke per the commands
table.

## Test plan

Step 2's cap unit + Step 3's four scenarios are the substance (~8-10
tests). The approval-pair scenario (b) is the most load-bearing — it pins
the contract 052's pending-approvals endpoint and the approval UI already
assume (lists of pending tools per run).

## Done criteria

- [ ] Independent delegate calls in one model response execute
      concurrently, bounded by `AGENT_DELEGATION_MAX_PARALLEL`
- [ ] Multi-child approval suspension collapses into one suspension and
      one resume; approval-state projection unchanged
- [ ] Parent cancellation cancels in-flight children (rows `cancelled`)
- [ ] Aggregate usage accounting proven under concurrency; probes
      recorded in the module docstring
- [ ] Depth remains 1; no schema or SSE changes;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any Step 1 probe fails: usage races, approvals do not collect into one
  `DeferredToolRequests`, or cancellation detaches child tasks — each
  invalidates a decision above and needs a design amendment, not a local
  workaround.
- The resume path re-enters only the first of two suspended children —
  the `_has_delegated_deferred_results` / `resume_approved_delegate_run`
  seam needs redesign; report with the probe evidence.
- DB pool arithmetic shows the default cap can exhaust connections in a
  realistic deployment — propose the corrected default rather than
  silently raising the pool.
- Fan-out requires touching `parallel_tool_calls` model settings to work
  on any catalog provider — record which provider and ask before changing
  provider defaults.

## Maintenance notes

- **041/046 tool latency** is what makes fan-out valuable — once
  integration/KB tools exist on delegate agents, revisit the default cap
  with real latency data.
- **Child transcript UX**: `NullSink` children mean the parent
  conversation shows call/result rows only. If users ask "what is the
  delegate doing", the answer is a future live-child-stream plan — not
  widening this one.
- **Depth**: any future request for depth 2 must revisit the envelope
  inheritance chain (054) and the semaphore scoping (per-root-run, not
  per-parent) — recorded here so the temptation gets a checklist.
- Reviewers should scrutinize: semaphore scope (per run, not global), the
  approved-replay path not consuming a slot, and scenario (b)'s
  both-children-resume assertion.
