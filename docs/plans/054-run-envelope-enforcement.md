# Plan 054: Run envelope enforcement — principal-derived side-effect policy

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/api/services/agents/runtime/envelope.py apps/api/services/agents/runtime/dispatch.py apps/api/services/agents/runtime/tools/contract.py apps/api/services/agents/runtime/delegation/ apps/api/services/agents/runtime/execute_run.py`
> Compare the "Current state" excerpts against live code; treat a mismatch
> in the `RunEnvelope` shape, `check_envelope`, or the tool contract fields
> as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (changes what unattended runs are allowed to do; a wrong
  default silently blocks scheduled runs or silently grants them writes)
- **Depends on**: 025/026 (landed). **Hard ordering: before 041** — the
  envelope is the principal-based backstop for money-spending integration
  tools; treat this as an extension of Gate G1.
- **Category**: Lane H — harness hardening (post-roadmap additions
  053–060, added 2026-07-07)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07

## Product intent

Plan 026 built the envelope *machinery*: `RunEnvelope` carries a
`side_effect_policy` (`allow | require_approval | deny`) and
`max_delegation_depth`, `check_envelope` blocks write tools under `deny`
(audited as `denied_envelope`), and delegation enforces the depth cap. But
the *input side* was never parameterized: `build_run_envelope`
(`envelope.py:26-30`) sets only `principal` from the run trigger and every
run — a user watching live, a 3am scheduled run, a delegated child — gets
the identical grant `("allow", depth 1)`. Two enforcement branches are dead
in practice: no envelope is ever built with `deny`, and `require_approval`
is not even checked by `check_envelope` (`dispatch.py:105` tests `deny`
only).

Why it has not bitten: write tools default to `approval` and scheduled runs
pause on approval. But that protection lives in the *per-agent tool policy*
layer, which any editor can flip to `auto` per agent. From that moment the
agent's unattended runs execute writes with nobody watching. Governance §2
already states the law for *what tools do* (spend ⇒ non-weakenable
approval); the envelope is the same law keyed on *who is running* — and it
must be wired before 041 ships tools whose writes cost money.

## Decisions taken

1. **Tool contract grows an explicit side-effect scope.**
   `RuntimeToolDefinition` gains `effect_scope: Literal["internal",
   "external"]` (default `"internal"`), meaningful only for
   `effect="write"`. Internal writes mutate Praxis-owned state (todos,
   scratch, memory notes later); external writes touch systems outside
   Praxis (integration writes, durable file promotion, artifact creation,
   KB writes). This mirrors governance §2's internal/external split, which
   the contract currently cannot express. Landed write tools classify as:
   `write_todos` internal, `write_file` **scratch-mode internal /
   durable-mode external** — since the mode is an argument, not a
   definition, classify the *definition* external iff it can produce a
   durable write; `promote_scratch` external. Import-time validation:
   `effect="read"` tools must not declare `external`.
2. **Envelope policy derives from the principal.** `build_run_envelope`:
   - `interactive` → `allow`
   - `scheduled` → `settings.AGENT_SCHEDULED_SIDE_EFFECT_POLICY`, default
     `require_approval`
   - `delegated` → inherited (decision 4), never wider than the parent
   `max_delegation_depth` moves to
   `settings.AGENT_MAX_DELEGATION_DEPTH` (default 1 — unchanged behavior;
   plan 057 keeps it at 1 and adds breadth, not depth).
3. **`require_approval` gets its enforcement branch.** In
   `check_envelope`/`dispatch_tool_execution`: for `effect="write"` +
   `effect_scope="external"` tools, when the envelope says
   `require_approval` and `ctx.tool_call_approved` is false, raise
   `ApprovalRequired` — the existing dispatch `except ApprovalRequired`
   branch audits it (`approval_requested`) and pydantic-ai suspends into
   the normal `DeferredToolRequests` flow, so scheduled runs pause exactly
   as they do for `approval`-policy tools today (005's resume finalization
   applies unchanged). `deny` keeps its current model-visible-retry
   behavior; internal writes are untouched by `require_approval` (a
   scheduled morning-report agent must keep writing todos/scratch without
   a human).
4. **Delegated inheritance is recorded at mint time.**
   `delegate_to_agent` stamps the parent's effective policy into the child
   run's server-minted metadata
   (`metadata["envelope"] = {"side_effect_policy": ...}`) at
   `create_agent_run` time; `build_run_envelope` reads it for
   `trigger="delegated"` and falls back to the *most restrictive* of the
   configured defaults if absent (fail-closed for legacy rows). The
   envelope remains derived from persisted server state, never client
   input — the docstring's law (`envelope.py:19`) still holds.
5. **No per-agent or per-schedule override in v1.** A future plan may let a
   schedule owner grant `allow` to a specific schedule (with audit); doing
   it now adds a permission surface before any external-write tool exists.
   The settings-level default is the whole v1 configuration story. Record
   in governance §2 as `[implemented: plan 054]` for the non-interactive
   rows.
6. **Spend-class tools are double-locked.** 041's
   `supports_auto=False` tools are unaffected by envelope logic (approval
   is already unconditional); the envelope matters for the *rest* of the
   external-write catalog. State this in the plan so nobody "simplifies"
   one layer away.

## Why this matters

This is the difference between "approval defaults that an editor can
weaken" and "an execution grant the server mints per principal". It is
also the cheapest plan in Lane H: the enforcement point, audit outcome
vocabulary (`denied_envelope`), and suspension flow all exist — the change
is deriving the grant and adding one branch, with tests. After this plan,
the statement "an unattended run cannot perform an external write without
a human approving it" is enforced by construction, not by configuration
discipline.

## Current state

All anchors verified on the working tree at `c2f08cc` (2026-07-07).

- **Envelope**: `services/agents/runtime/envelope.py` — frozen
  `RunEnvelope(principal, side_effect_policy="allow",
  max_delegation_depth=1)`; `build_run_envelope(run)` sets principal from
  `run.trigger` only (lines 17-30). Built once per run at
  `execute_run.py:205` into `RuntimeDeps.envelope` (`context.py:29`).
- **Enforcement**: `dispatch.py:98-107` — `check_envelope` returns the
  denial message only for `effect == TOOL_EFFECT_WRITE and
  side_effect_policy == "deny"`; denial audits as `denied_envelope`
  (lines 148-163) and raises `ModelRetry(ENVELOPE_DENIAL_MESSAGE)`.
  `ApprovalRequired` raised from a handler is audited `approval_requested`
  and re-raised (lines 167-181). `ctx.tool_call_approved` marks approved
  replays (line 146; probe notes lines 5-16).
- **Depth**: `delegation/delegate_to_agent.py:59-65` fails fast when
  `envelope.max_delegation_depth <= deps.delegation_depth`; child runs are
  created with `delegation_depth + 1` and `parent_run_id` (lines 117-133);
  child metadata is server-assembled at lines 126-132 (the seam for
  decision 4).
- **Tool contract**: `runtime/tools/contract.py` —
  `RuntimeToolDefinition` has `effect` (`read`/`write`),
  `default_policy`, `supports_auto`/`supports_approval`, `output_model`,
  `kind`, `defer_loading`, `supported_model_providers`, `auto_mount`,
  `presentation`; **no external/internal distinction**. Import-time
  `validate_definition` runs invariants; the registry read API
  (`/api/v1/tools/catalog`) projects contract metadata.
- **Landed write tools**: `write_todos` (planning.py, auto, internal
  state), `write_file` (staged approval for durable writes; scratch writes
  auto per governance §2 `[implemented: plan 034]`), `promote_scratch`
  (approval). `web_search` is `effect="read"`-class native helper with
  default `approval`.
- **Settings**: `core/settings/agents.py` holds the runtime knobs
  (lease/heartbeat/history/token-cap, lines 34-91) — the natural home for
  the two new settings; the production-safety `model_validator` lives in
  `core/settings/__init__.py:51+`.
- **Governance**: `docs/architecture/governance.md` §2 — non-interactive
  rows currently read "scheduled runs pause on approval (026 decision,
  *(enforced today)*); delegated runs inherit the parent envelope's cap
  *(enforced today: 026 envelopes)*" — the cap is enforced; the
  side-effect policy is not. This plan updates those cells.
- **Scheduled runs today have no external-write tools** — the default flip
  is behaviorally invisible until 041, which is exactly why it must land
  first.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Focused tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agents/runtime tests/services/agent_schedules -q` | all pass |
| Contract tests | `cd apps/api && uv run pytest tests/contract -q` | all pass |
| Full suite | `cd apps/api && TEST_DATABASE_URL=... uv run pytest -q` | all pass |

## Scope

**In scope:**

- `services/agents/runtime/envelope.py` (derivation per decisions 2/4)
- `services/agents/runtime/dispatch.py` (`require_approval` branch,
  decision 3)
- `services/agents/runtime/tools/contract.py` (+ `effect_scope`,
  import-time invariant) and the landed tool definitions' classifications
  (decision 1)
- `services/agents/runtime/delegation/delegate_to_agent.py` (metadata
  stamp, decision 4)
- `core/settings/agents.py` (`AGENT_SCHEDULED_SIDE_EFFECT_POLICY`,
  `AGENT_MAX_DELEGATION_DEPTH`)
- `/api/v1/tools/catalog` projection + frontend catalog types if the new
  field should display (keep additive; the agent form does not gate on it)
- `docs/architecture/governance.md` §2 cell updates (same PR, per the
  governance doc's own rule)
- Tests: envelope derivation, dispatch branches, delegation inheritance,
  scheduled-run suspension end-to-end

**Out of scope (do NOT touch):**

- Per-schedule/per-agent envelope overrides (decision 5).
- Any change to per-tool `default_policy` values or the `supports_auto`
  machinery.
- 041 provider tools (they arrive with `effect_scope="external"` already
  in their plan's hands — add a one-line note to plan 041's drift check
  instead).
- The approval-resume protocol and SSE events.

## Git workflow

- Branch: `advisor/054-run-envelope-enforcement`
- Commit: `API - Principal-Derived Run Envelopes`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: contract `effect_scope`

Add the field + default, import-time invariant (`read` ⇒ must be
`internal`), classify landed tools per decision 1, expose through the
catalog schema additively. Update contract tests.

**Verify**: `uv run pytest tests/contract -q`; catalog response carries the
field.

### Step 2: settings + derivation

Add the two settings; rewrite `build_run_envelope` per decision 2 with the
delegated fallback per decision 4 (read
`run.metadata_json.get("envelope")`). Keep the frozen dataclass; keep the
trigger validation error.

**Verify**: unit tests — interactive/scheduled/delegated × configured
policies, legacy delegated row fail-closed.

### Step 3: dispatch `require_approval` branch

Extend `check_envelope` to return a structured verdict (deny message |
needs-approval | pass) or add a sibling helper; in
`dispatch_tool_execution`, raise `ApprovalRequired` for the needs-approval
verdict when `ctx.tool_call_approved` is false. Confirm the existing
`except ApprovalRequired` audit branch records it and that an approved
resume replays through with `tool_call_approved=True` and executes.

**Verify**: runtime test with a `FunctionModel`-scripted external-write
fixture tool — scheduled-trigger run suspends (`awaiting_approval`,
`approval_requested` audit row), resume-approve executes and audits
`completed`; interactive run executes without suspension; `deny` policy
still audits `denied_envelope`.

### Step 4: delegation inheritance

Stamp the parent policy at child-run creation; envelope derivation reads
it. Test: interactive parent → child inherits `allow`; scheduled parent →
child inherits `require_approval` and a child external write suspends and
propagates through the existing delegated-approval path
(`raise_delegate_approval_required`).

### Step 5: end-to-end scheduled suspension

Worker-harness test: a scheduled run whose script calls the external-write
fixture pauses, `agent_schedule_runs` reflects awaiting-approval (existing
005/021 seams), approve → resume → finalize. No changes to those seams —
this is a regression pin, not new behavior.

### Step 6: governance + docs

Update governance §2 non-interactive cells to
`[implemented: plan 054]`, note the two settings, and record decision 6.

## Test plan

~12-16 tests: contract invariants (2-3), derivation matrix (4), dispatch
branches incl. approved replay (4-5), delegated inheritance (2), scheduled
end-to-end (1-2). All deterministic (`FunctionModel`/`TestModel`) — no live
LLM.

## Done criteria

- [ ] `build_run_envelope` no longer returns a constant grant; scheduled
      default is `require_approval` via settings
- [ ] External-write tools suspend for approval on scheduled/delegated-
      from-scheduled runs even when their per-agent policy is `auto`
- [ ] `deny` and depth enforcement behave exactly as before (regression
      tests pass unchanged)
- [ ] Delegated children can never hold a wider policy than their parent
- [ ] Catalog exposes `effect_scope`; governance §2 cells updated in the
      same PR
- [ ] Full API suite green; `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Raising `ApprovalRequired` from the dispatch hook (rather than from a
  tool body) does not produce a well-formed `DeferredToolRequests`
  suspension in the installed pydantic-ai — probe first, and if the hook
  layer cannot suspend, move the check into a shared tool-body guard and
  record the deviation.
- `write_file`'s dual scratch/durable nature cannot be honestly expressed
  as a single `effect_scope` — do not split the tool here; report the
  contract tension (the staged-approval flow may already make the durable
  path safe enough to classify the definition `internal`; that call needs
  the operator).
- Any existing scheduled-run test starts suspending on internal writes —
  the internal/external line is wrong, not the tests.
- You are tempted to add per-schedule overrides or a new permission — that
  is decision 5's deferred plan.

## Maintenance notes

- **Plan 041** must construct every integration write tool with
  `effect_scope="external"`; its review checklist should treat a missing
  scope as a blocking defect. Spend-class tools stay `supports_auto=False`
  on top (decision 6).
- **Plan 057** consumes `AGENT_MAX_DELEGATION_DEPTH` and must not raise it
  as a side effect of fan-out work.
- If a future plan adds `deny` as a schedule-level choice, the enforcement
  already exists — only the derivation and a permission surface are new.
- Reviewers should scrutinize: the delegated fallback being fail-closed,
  the approved-replay path (`tool_call_approved`) not re-suspending, and
  that no code path builds a `RunEnvelope` from request input.
