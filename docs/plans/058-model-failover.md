# Plan 058: Model failover chain

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/api/services/agents/models/ apps/api/services/agents/runtime/run_persistence.py`
> Compare the "Current state" excerpts against live code; treat a mismatch
> in the factory/resolution seam or the installed `FallbackModel` API as a
> STOP condition.

## Status

- **Priority**: P3 (operator decision 2026-07-07: wanted, but lower
  priority — schedule as filler alongside 015; do not displace Lane H
  P1s or Phase 4)
- **Effort**: S-M
- **Risk**: LOW-MED (behavioral: a silent provider swap changes cost and
  output character; the design makes the swap observable)
- **Depends on**: 010 (transport retries, DONE). Soft: 055 (a failover
  scenario joins the suite), 014 (spans make failover visible in traces).
- **Category**: Lane H — harness hardening (post-roadmap additions
  053–060, added 2026-07-07)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07
- **Supersedes**: the 2026-07-01 rejection recorded in
  `docs/plans/000_README.md` ("FallbackModel provider failover: not
  planned … needs a product decision first") — the product decision was
  taken 2026-07-07: failover is wanted, opt-in, observable, and
  same-capability-class only.

## Product intent

Transport retries (010) absorb transient HTTP failures *within* one
provider; a provider outage or hard model error still fails the run
terminally (`persist_failed_run`). For interactive chat that is a
tolerable retry-by-human; for overnight scheduled runs it is a missed
morning report. This plan adds an opt-in failover chain so a run survives
a provider outage by falling back to an explicitly configured equivalent
model — visibly, never silently.

## Decisions taken

1. **Use pydantic-ai `FallbackModel`, configured in the catalog.**
   Installed signature (probed 2026-07-07):
   `FallbackModel(default_model, *fallback_models,
   fallback_on=(ModelAPIError,))` from `pydantic_ai.models.fallback`;
   each chain member keeps its own `settings`. Catalog entries in
   `registry.py` gain an optional `fallback: tuple[str, ...]` of
   *qualified catalog ids* (e.g. Anthropic primary → OpenAI equivalent).
   The catalog stays the single source of truth — no per-agent fallback
   editing in v1 (an agent opts in or out; it does not invent chains).
2. **Opt-in twice: a global switch and per-agent consent.**
   `AGENT_MODEL_FALLBACK_ENABLED` (settings, default `False`) AND the
   agent's `model_settings` flag (`"fallback": true`) must both hold
   before the factory wraps. Default-off preserves current behavior
   exactly; scheduled agents are the intended opt-in audience.
3. **Fallback fires on provider errors only** — keep the default
   `fallback_on=(ModelAPIError,)`. No response-content handlers
   (truncation/semantic fallback) in v1: those change results, not just
   availability.
4. **Chains are same-capability-class.** Import-time validation: every
   fallback id must exist in the catalog and must not lose capabilities
   the primary declares (`supports_vision`, `supports_thinking`,
   `supports_structured_output`) — a multimodal turn falling back to a
   text-only model is a worse failure than the outage. Context-window
   shrink is allowed but the smallest window in the chain drives 056's
   pressure math (record the min over the chain in `ResolvedModel`).
5. **The swap is observable.** `run.model_name` currently records the
   *resolved primary* (`execute_run.py:188-189`). With failover, the
   actually-used model comes from the response messages
   (`ModelResponse.model_name`); terminal persistence records it (a
   `model_used` addition to the run's `usage_json`/hot columns decision
   is the executor's — prefer `usage_json` to avoid a migration) and logs
   a warning per fallback activation. Anthropic-only cache settings
   (`factory.py:83-92`) apply per member (decision 1's per-member
   settings), so a fallback to OpenAI simply runs uncached — fine.
6. **Credentials must exist for every chain member** — resolution fails
   fast at agent-save/spec-resolution time (the `provider_api_key` seam
   raises for missing keys), not mid-outage. A chain member whose
   provider has no key configured is dropped from the chain with a
   warning at build time (degrade to a shorter chain, never to a runtime
   surprise).

## Why this matters

Reliability for unattended runs is the whole point of schedules; a
single-provider dependency is the largest remaining single point of
failure once cancellation (053) and envelopes (054) land. Doing it
through `FallbackModel` keeps `execute_run` library-agnostic (the
architecture doc's stated swap-seam principle) — the change is contained
to the catalog and factory.

## Current state

All anchors verified on the working tree at `c2f08cc` (2026-07-07).

- **Factory**: `services/agents/models/factory.py` — `build_model(spec)`
  branches per provider with explicit `provider_api_key(...)` +
  `retrying_http_client()`; Anthropic cache settings injected at
  `_model_settings_for` (83-92). One `Model` returned; no wrapping seam
  yet.
- **Resolution**: `services/agents/models/resolution.py` —
  `resolve_agent_model(agent)` merges agent row config over catalog
  defaults into `ResolvedModel` (provider, model, settings,
  `max_steps`, `context_window`, `azure_deployment`, `qualified_id`).
- **Catalog**: `services/agents/models/registry.py` `_CATALOG` — entries
  carry `context_window` and `supports_*` flags; no fallback field.
- **Run model recording**: `execute_run.py:188-189` stamps
  `run.model_name = runtime_agent.resolved_model.qualified_id` before
  streaming; `run_persistence.usage_snapshot` maps provider usage into
  `usage_json` + hot columns.
- **Installed API (probe 2026-07-07)**: `pydantic_ai.models.fallback.
  FallbackModel(default_model, *fallback_models, fallback_on=
  (ModelAPIError,))`; `fallback_on` accepts exception tuples or handler
  callables; per-member settings honored (docs digest
  `05-models-and-providers.md:93,123-145`).
- **Prior rejection**: `docs/plans/000_README.md` "Findings Considered
  And Rejected" — superseded per the Status block; the README bullet gets
  a supersession note in the 053–060 integration edits.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Focused tests | `cd apps/api && uv run pytest tests/services/agents -q` | all pass |
| Scenario suite | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/scenarios -q` | all pass |

## Scope

**In scope:**

- `services/agents/models/registry.py` (fallback field + import-time
  chain validation per decision 4)
- `services/agents/models/factory.py` (wrap when both opt-ins hold;
  drop keyless members with a warning per decision 6)
- `services/agents/models/resolution.py` (chain-aware `ResolvedModel`
  additions: effective min context window; fallback flag)
- `core/settings/agents.py` (`AGENT_MODEL_FALLBACK_ENABLED`)
- `services/agents/runtime/run_persistence.py` (record actually-used
  model per decision 5)
- Catalog API projection (additive field) — the agent form may later
  surface "fallback available"; no UI work required in v1
- Tests: chain validation, factory wrapping/degrading, used-model
  recording; one scenario (scripted primary failure → fallback answers)

**Out of scope (do NOT touch):**

- Per-agent custom chains, response-content fallback handlers, retry-
  then-fallback tuning (transport retries stay as-is underneath).
- Cost controls (a fallback can be pricier; the workspace-budget
  follow-up noted in 056 owns spend visibility).
- `execute_run` — if this plan needs to touch it beyond persistence
  recording, the seam is wrong; stop.

## Git workflow

- Branch: `advisor/058-model-failover`
- Commit: `API - Opt-In Model Failover Chains`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

1. **Catalog + validation**: fallback ids on 2-3 sensible pairs (one per
   provider family; choose closest-capability peers), import-time checks
   (existence, capability superset, no cycles/self-reference).
   *Verify*: registry tests.
2. **Factory wrap + degrade**: build members via the existing per-provider
   branches; wrap in `FallbackModel` when enabled (decision 2); drop
   keyless members with one warning. *Verify*: unit tests with fake key
   presence/absence.
3. **Observability**: record actually-used model at terminal persistence;
   warning log on fallback activation (detect: used != primary).
   *Verify*: `FunctionModel`-based test simulating `ModelAPIError` from
   the primary (pydantic-ai test models can script this; otherwise a stub
   `Model` raising on request) — run completes on fallback, `usage_json`
   carries the fallback id, log emitted.
4. **Scenario + docs**: scenario-suite addition (055); note in
   `docs/architecture/agent-runtime.md` provider section; README
   supersession cross-check.

## Test plan

~8-10 tests: validation matrix (existence/capability/cycle), enabled ×
consent matrix (4 combinations — only both-on wraps), keyless degrade,
failover execution + recording scenario.

## Done criteria

- [ ] Default behavior byte-identical with the switch off (regression
      suite unchanged)
- [ ] With both opt-ins, a primary `ModelAPIError` completes on the
      configured fallback; the used model is persisted and logged
- [ ] Chains validated at import time; capability-losing chains are a
      boot failure, keyless members degrade with a warning
- [ ] `docs/plans/000_README.md` row updated and the old rejection bullet
      carries the supersession note

## STOP conditions

Stop and report back (do not improvise) if:

- `FallbackModel` interacts badly with streaming (`run_stream_events`)
  in the installed version — e.g., fallback cannot engage after the
  stream has started. Probe first; if mid-stream failover is unsupported,
  record that failover covers request-start failures only (that is still
  the outage case) and note the limitation in the plan and code.
- Recording the used model requires a migration to be honest (hot column
  vs `usage_json`) — propose, don't pick silently if it changes the run
  read API.
- Capability validation would block every sensible cross-provider pair
  (flags too coarse) — report; do not weaken the rule to ship a chain.

## Maintenance notes

- Revisit the default-off switch once 014 traces show real provider
  error rates — evidence may justify default-on for scheduled principals
  only (a natural composition with 054's principal-derived envelopes).
- If provider breadth ever outgrows pydantic-ai, the architecture doc's
  LiteLLM note applies beneath this same seam — chains stay a catalog
  concept.
- Reviewers should scrutinize: the both-opt-ins gate, the keyless-member
  degrade path, and that no chain can silently downgrade vision/structured
  output.
