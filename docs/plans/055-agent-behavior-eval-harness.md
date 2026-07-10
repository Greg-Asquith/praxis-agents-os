# Plan 055: Agent behavior eval harness (Gate G5)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Amendment (2026-07-07, plan 075 — prompt-injection threat model)**:
> the decision-4 dataset sketch gains a fifth category, **injection
> resistance** — cases that feed hostile content through real channel
> tools (045's fixture docs via `search_knowledge`, a hostile memory via
> `search_memory`, a hostile pre-compaction span) and grade that the
> model does not comply, does not encode data into outbound tool
> parameters, and reports the attempt. This category is the named home of
> behavioral injection resistance platform-wide (threat-model.md §4):
> live LLM calls are blocked in tests, so resistance is graded here —
> opt-in, never CI. Channel cases land as their plans land (046/048/056
> amendments each add theirs); the category and its first KB-backed cases
> are this plan's deliverable.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/api/services/agents/runtime/ apps/api/tests/ apps/api/pyproject.toml makefiles/`
> Compare the "Current state" excerpts against live code; treat a mismatch
> in the sink/test-support seams or the pydantic-ai/pydantic-evals versions
> as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: LOW-MED (additive test/eval infrastructure; the risk is
  building a platform instead of content, or letting graded evals leak
  into the deterministic CI gate)
- **Depends on**: none hard (all runtime seams landed). **Gate G5
  (delivered by this plan)**: the scenario suite must be green before 048
  memory-write-policy tuning, before 057 changes delegation concurrency,
  and before any default-model or prompt-assembly change ships without a
  scenario run. Complements Gate G4 (retrieval/memory evals, plan 045) —
  G4 grades *what search returns*; G5 pins *what the harness does*.
- **Category**: Lane H — harness hardening (post-roadmap additions
  053–060, added 2026-07-07)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07

## Product intent

Every prompt-block change, model swap, trimming tweak, and tool-policy
adjustment currently ships unverified against agent *behavior*. The test
suite pins services and routes; nothing pins "given this conversation and
this agent config, the harness dispatched these tools, suspended at this
approval, trimmed history to this shape, and produced this kind of
output". Gate G4 (045) will cover retrieval quality; nothing covers the
harness itself.

Decision taken with the operator (2026-07-07): **build eval content, not
an eval platform.** Three layers, two of which are bought:

1. **Deterministic scenario suite** (built, this plan's core): pytest +
   `FunctionModel`-scripted models driving the real `execute_run` against
   a real test database. Asserts on harness behavior — dispatch, audit,
   approvals, envelopes, prompt assembly, trimming. Runs in CI; no live
   LLM (the existing test guard stays).
2. **Graded evals** (assembled from `pydantic-evals`, already installed
   at 2.1.0 via the pydantic-ai meta-package): dataset-driven cases with
   evaluators (incl. `LLMJudge`) for quality questions determinism cannot
   answer — instruction adherence, tool-selection sensibility, output
   quality. Live provider calls; opt-in `make evals`; never in the CI
   gate.
3. **Production trace review** (deferred): rides plan 014's OTel seam;
   backend choice (Logfire vs self-hosted LangFuse) is an OTLP endpoint
   decision, not code — no work in this plan beyond not blocking it.

## Decisions taken

1. **Scenario tests live under `tests/scenarios/` as a first-class intent
   directory** (AGENTS.md names the organized intents; this adds one, in
   the same DB-backed, skip-without-`TEST_DATABASE_URL` pattern). They are
   pytest tests, run with the normal suite — a scenario is just a test
   whose subject is `execute_run` end-to-end rather than one service.
2. **One scenario helper, not a framework.** `tests/support/scenario.py`
   provides: `build_scenario_agent(...)` (workspace/user/agent/conversation
   via existing factories), `scripted_model(turns=[...])` (a `FunctionModel`
   whose call sequence is declared as data — each turn either returns text
   or requests named tool calls with args), and `run_scenario(...)` →
   `ScenarioResult` capturing the `ExecuteRunResult`, the `CollectingSink`
   events, persisted messages, audit rows for the run, and the run row.
   Assertions are plain pytest on that result object. No YAML DSL, no
   custom runner, no assertion mini-language.
3. **The v1 scenario catalog pins the behaviors we already rely on**
   (each an existing feature with no end-to-end pin today):
   - *Dispatch & audit*: every executed tool yields exactly one audit row
     with digest-only args; a failing tool audits `failed`; an
     output-contract mismatch on a write tool audits `unverified_mutation`
     and retries.
   - *Approvals*: approval-policy tool suspends → `awaiting_approval` +
     `approval_requested` audit + approval-state snapshot; resume-approve
     executes; resume-deny audits `denied_approval` and the model sees the
     typed denial.
   - *Envelopes* (extends as 054 lands): scheduled-principal external
     write suspends; deny audits `denied_envelope`.
   - *Delegation*: parent delegates, child runs on its own
     conversation/run with depth+1, result returns to parent; child
     approval propagates.
   - *Prompt assembly*: block order (identity → planning → delegation →
     available_files), budget truncation marker, skills catalog lines
     present, loaded-skill instructions injected after `load_capability`.
   - *History trimming*: watermark stability across consecutive turns
     (same trim point), `LoadCapability*` pair re-synthesis, current-run
     tail preservation.
   - *Multimodal*: attachment ids resolve to `BinaryContent` parts under
     the file contract (036).
   - *Cancellation* (as 053 lands): mid-tool cancel → `cancelled`, no
     `failed`, terminal events.
   New harness plans add scenarios here as part of their own done
   criteria — that is the "gate" mechanism, and it is why the helper must
   stay boring.
4. **Graded evals live in `apps/api/evals/`, outside `tests/`.** Structure:
   `evals/datasets/*.yaml` (pydantic-evals `Dataset` serialization),
   `evals/evaluators.py` (shared rubric evaluators), `evals/run.py`
   (entrypoint: loads datasets, runs against a named agent config +
   catalog model, prints/writes the report). Invoked by `make evals`
   (new target) with an explicit `EVALS_MODEL` env; it refuses to run if
   provider keys are absent rather than skipping silently. The v1 dataset
   is deliberately small (10-20 cases): instruction adherence (does the
   agent follow its configured identity block), tool selection (given a
   files question, does it call `read_file` rather than answering
   unaided), refusal/boundary cases, and format-following. LLMJudge
   rubrics phrase pass criteria concretely.
5. **CI stays deterministic.** The live-LLM block in the test suite is
   untouched; `evals/` is excluded from pytest collection (no `test_`
   naming, plus an explicit `norecursedirs` entry if needed). `make check`
   does not run evals. A follow-up may add a scheduled CI job for evals;
   not this plan.
6. **Production runs seed future eval cases by hand, not by pipeline.**
   `agent_runs` already persists full histories; when a real conversation
   exposes a behavior gap, the fix lands with a scenario or eval case
   distilled from it. No automated trace→dataset pipeline in v1 (that is
   the LangFuse-tier decision deferred with layer 3).

## Why this matters

The harness is about to get materially more complex (integrations, KB,
memory, fan-out, compaction), and SMEs will edit agent instructions with
no ability to judge regressions themselves. The scenario suite is the
contract that lets the next ten plans change the runtime without
re-manual-testing everything; the graded layer is the only honest answer
to "did this prompt change make the agent worse". Building it now — before
Phase 4/5 land — is the cheap moment: the behaviors to pin are still
enumerable.

## Current state

All anchors verified on the working tree at `c2f08cc` (2026-07-07).

- **Deterministic model tools**: pydantic-ai 2.1.0 installed;
  `FunctionModel`/`TestModel` available (`pydantic_ai.models.function`,
  `.test`) and already referenced by runtime tests. `pydantic-evals 2.1.0`
  is **already installed** as part of the meta-package (verified via
  `uv pip list`) — no new dependency.
- **Test infra**: `pyproject.toml:41` sets `asyncio_mode = "auto"` (C01);
  DB-backed tests skip without `TEST_DATABASE_URL` via `conftest.py`
  fixtures; factories in `tests/factories/`, helpers in `tests/support/`;
  live LLM calls are blocked in tests (AGENTS.md contract). Existing
  runtime tests live in `tests/services/agents/runtime/` and already use
  `CollectingSink` (`services/agents/runtime/sinks.py:62-73`).
- **Runtime seams a scenario drives**: `execute_run`
  (`execute_run.py:85-368`) accepts an injected `model` (line 93 —
  `run_turn_worker` threads it; tests pass `FunctionModel` here),
  `CollectingSink` captures the full sequenced event stream, audit rows
  are committed per invocation (`dispatch.py`), approval state persists
  via `persist_suspended_run`, resume re-enters with `message_history` +
  `DeferredToolResults`.
- **Prompt assembly**: pure functions `runtime_prompt_blocks` /
  `build_system_prompt` (`prompt.py:47-92`) — directly assertable without
  a run.
- **Trimming**: pure `trim_history` (`history.py:21-60`) — directly
  assertable; end-to-end shape via scenario turns.
- **Make targets**: root `Makefile` + `makefiles/` sections; `make
  check` runs the main gates (C01). No `evals` target exists.
- **No eval/scenario directory exists**: `ls apps/api` shows no `evals/`;
  `tests/` has contract/routes/services/integration/middleware/factories/
  support.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Scenario suite | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/scenarios -q` | all pass |
| Full suite | `cd apps/api && TEST_DATABASE_URL=... uv run pytest -q` | all pass, count grows by the scenario tests only |
| Graded evals (opt-in) | `cd apps/api && EVALS_MODEL=openai:gpt-5.4-mini uv run python -m evals.run` (or `make evals`) | report printed; nonzero exit on missing keys |
| CI guard | `uv run pytest --collect-only -q \| grep -c evals` | 0 (evals not collected) |

## Scope

**In scope:**

- `apps/api/tests/scenarios/` (create): `test_dispatch_audit.py`,
  `test_approvals.py`, `test_envelopes.py`, `test_delegation.py`,
  `test_prompt_assembly.py`, `test_history_trimming.py`,
  `test_multimodal.py` (group per decision 3; exact file split may vary —
  keep behavior-intent naming)
- `apps/api/tests/support/scenario.py` (create, decision 2) + factory
  additions if a fixture is missing
- `apps/api/evals/` (create, decision 4): `datasets/`, `evaluators.py`,
  `run.py`, `README.md` (how to run, how to add a case, what never goes
  in CI)
- `makefiles/` — `make evals` target
- `apps/api/pyproject.toml` — only if evals collection needs an explicit
  exclusion; **no new dependencies**
- Roadmap/README wiring for Gate G5 (owned by the 053–060 integration
  changes; verify the gate text names this plan)

**Out of scope (do NOT touch):**

- Any runtime behavior change. This plan only observes. If writing a
  scenario reveals a bug, record it as a follow-up (or a trivially safe
  fix in its own commit) — do not fold fixes into the harness PR.
- OTel/Logfire/LangFuse wiring (plan 014 / deferred layer 3).
- Retrieval/memory eval content (Gate G4, plans 045/048 own those; 048's
  memory eval tests should *reuse* the scenario helper).
- CI workflow changes beyond keeping evals uncollected.
- Frontend.

## Git workflow

- Branch: `advisor/055-agent-behavior-eval-harness`
- Commits: `API - Scenario Harness & Support` / `API - Graded Evals Layer`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: scenario helper

`tests/support/scenario.py` per decision 2. Keep the scripted-model
declaration honest to pydantic-ai's `FunctionModel` contract (probe the
installed signature; record the call-shape in a module docstring the way
`dispatch.py` records hook probes). `ScenarioResult` exposes:
`run`, `output`, `events` (list of `SinkEvent`), `messages` (persisted
conversation messages), `audit_rows` (queried by `run_id`), plus
`tool_calls(name=...)` and `event_names()` conveniences — properties, not
assertion methods.

**Verify**: one smoke scenario (text-only turn) passes; helper has no
imports from route modules.

### Step 2: dispatch/audit + approval scenarios

Write the first two groups from decision 3. The approval group must cover
suspend → approve-with-`override_args` → execute, and suspend → deny →
typed denial visible to the model (assert on the retry/denial message part
in persisted history).

**Verify**: `uv run pytest tests/scenarios -q` green; each scenario
asserts at least one audit row outcome and one persisted-state fact (not
just sink events).

### Step 3: prompt/trimming/delegation/multimodal scenarios

Remaining groups from decision 3 (envelope group lands with/after 054 —
write it against the fixture external-write tool if 054 is in, else leave
a marked TODO scenario that STOPs rather than fakes). Trimming scenarios
drive multiple turns through `execute_run` with `AGENT_HISTORY_MAX_TURNS`
overridden low via settings, asserting watermark stability by comparing
the trim cut across two consecutive turns.

### Step 4: graded evals layer

`evals/` per decision 4: dataset schema via `pydantic_evals.Dataset`
serialization; `run.py` builds the target agent through the real
`build_runtime_agent` seam with a catalog model resolved from
`EVALS_MODEL`; evaluators: 2-3 shared `LLMJudge` rubrics + simple
programmatic checks (called-tool inclusion, output format). Fail loudly
without keys. `make evals` wraps it.

**Verify**: `--collect-only` guard shows evals uncollected; with keys, a
run produces a scored report; without keys, exit code is nonzero with a
clear message.

### Step 5: docs + gate

`evals/README.md`; add the scenario-suite expectation to the harness
plans' review culture by recording Gate G5 in the roadmap/README (see the
053–060 integration edits) and cross-linking from `tests/scenarios/`
module docstrings ("new runtime behavior lands with a scenario").

## Test plan

The plan *is* tests: ~18-25 scenario tests across seven behavior groups,
plus the evals layer's own smoke (a `--collect-only` guard and a mocked
`run.py` unit test for key-absence failure). Existing suites must pass
unchanged — this plan asserts current behavior; any red scenario is
either a wrong assertion or a real bug to report, never a reason to
change runtime code in this PR.

## Done criteria

- [ ] `tests/scenarios/` green under `TEST_DATABASE_URL`, red-lining the
      behaviors in decision 3 (envelope group may track 054)
- [ ] Scenario helper is <~300 lines, framework-free, and used by every
      scenario
- [ ] `evals/` runs pydantic-evals datasets against a catalog model via
      `make evals`, is never collected by pytest, and fails loudly
      without provider keys
- [ ] No runtime source files changed; no new dependencies
- [ ] Gate G5 recorded in the roadmap (this plan named as owner);
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `FunctionModel` in the installed 2.1.0 cannot script multi-turn
  tool-call sequences the way decision 2 assumes — probe and record the
  real shape first; if scripting requires `iter()`-level control, the
  helper wraps that instead, but the scenario-facing API stays
  declarative.
- A scenario exposes a genuine runtime bug (e.g., a missing audit row, a
  trim that breaks capability pairs) — report it; do not fix silently and
  do not assert the buggy behavior as the pin.
- The live-LLM test guard turns out to block `FunctionModel` runs (it
  should not — no network) — fix the guard's discrimination, nothing else.
- Graded evals need a dependency not already shipped by the pydantic-ai
  meta-package.
- You are tempted to build a YAML scenario DSL, a custom assertion
  language, or a results database — that is the platform this plan
  explicitly does not build.

## Maintenance notes

- **Gate G5 discipline**: 048 (memory tuning), 056 (compaction), 057
  (fan-out), 058 (failover), 059 (code execution) each add scenarios here
  as part of their done criteria. A harness plan without a scenario
  addition should fail review.
- **Eval dataset growth**: add cases when real conversations expose gaps
  (decision 6); prune cases that stop discriminating. Keep the dataset
  small enough that `make evals` costs cents, not dollars.
- **Layer 3 (trace review)**: when 014 lands and real traffic exists,
  revisit Logfire vs self-hosted LangFuse as an OTLP backend choice; the
  decision record from 2026-07-07 leans LangFuse-self-hosted for the
  open-source/product-data posture, Logfire for dev convenience — both
  ride the same instrumentation.
- Reviewers should scrutinize: scenarios asserting persisted state (not
  only sink events), the helper staying free of runtime imports beyond
  the public seams, and the evals collection guard.
