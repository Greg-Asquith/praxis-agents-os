# Plan 076: Bounded tool results — truncation at dispatch and calibrated token estimation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6be5491..HEAD -- apps/api/services/agents/runtime/dispatch.py apps/api/services/agents/runtime/tools/contract.py apps/api/services/agents/models/domain.py apps/api/services/agents/models/registry.py apps/api/services/audit_events/tool_events.py apps/api/core/settings/agents.py apps/api/utils/`
> Compare the "Current state" excerpts against live code; treat a mismatch
> in the dispatch success path, the tool contract fields, or the audit
> `details` seam as a STOP condition. Plans 054 (dispatch branch) and 066
> (`execute_run` decomposition) may land first — reconcile against their
> landed shapes before coding.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (edits the dispatch choke point every tool result flows
  through; a wrong bound corrupts tool outputs the model then acts on)
- **Depends on**: 025/026 (DONE — contract + dispatch), 013 (DONE — its
  cache-stability invariants constrain this design), 066 (hard — lands
  first; it pins the adjacent runtime under characterization tests before
  this area churns further). **Hard ordering: before 056** — 056's
  token-pressure trigger consumes the estimator this plan calibrates —
  **and before 041** — integration tools (Gmail bodies, Airtable rows)
  produce exactly the large outputs this bounds. Coordinate with 054:
  both edit `dispatch.py`; whichever lands second rebases.
- **Category**: Lane H extension — harness hardening, added 2026-07-07
- **Planned at**: working tree at commit `6be5491`, 2026-07-07
- **Completed**: 2026-07-10

## Product intent

The context-management story has an unowned hole. Plan 013 (DONE) trims
whole turns at chunked watermarks; plan 056 (TODO) will summarize the span
below the watermark. Neither bounds a *single oversized tool result inside
a kept turn* — and one 50k-token tool output is the most common real-world
context blowout in agent traffic, which is why mature harnesses cap tool
outputs at the harness layer. The repo already exhibits the hazard:
`read_skill_document` returns an entire converted markdown document as an
unbounded `str`, while `read_file` self-bounds only by its own convention.
Every 041 provider tool would have to remember to do what `read_file` did
by hand.

013's maintenance notes already named "clearing/truncating large old tool
outputs" as the cheapest v2 pressure valve — and warned it is a mid-prefix
cache edit if done retroactively. This plan takes the honest variant:
truncate **at production time**, at the dispatch choke point, before the
result is ever persisted or seen by the model. The truncated bytes are the
persisted bytes, so every later turn replays them identically; retroactive
truncation of stored history stays rejected.

Second gap: the only token-accounting primitive anywhere in the plans is
056's proposed `chars//4` heuristic (056 decision 5), which under-counts
CJK (≈1 token per character) and code badly. This plan ships that
estimator early, calibrated per model through the catalog, so 056 consumes
a real utility instead of a magic number.

## Decisions taken

1. **Truncation lives at the dispatch choke point, sized by settings.**
   `AGENT_TOOL_RESULT_MAX_CHARS` (default `16_000` — roughly 4k tokens at
   4 chars/token, generous for prose, an order of magnitude below a
   blowout; `None` disables, matching the `AGENT_HISTORY_MAX_TURNS`
   convention). `RuntimeToolDefinition` gains `max_result_chars: int |
   None = None` for tools with legitimately large outputs; import-time
   invariant `> 0`. Tools without a catalog entry (dispatch resolves
   `definition=None` for delegation names) get the settings default. The
   helper is a pure in-module function beside `validate_output` — policy
   inside the module the docstring says to extend, not a second layer.
2. **Head+tail with a deterministic elision marker.** Keep the first 80%
   and last 20% of the character budget with a marker between them stating
   how many characters were elided and the approximate token count
   (decision 5's estimator, default divisor). The marker is a pure
   function of the sizes — no timestamps, no ids — and instructs the model
   to re-invoke the tool with narrower arguments (offset/pagination where
   the tool supports it). Spilling the full output to the 034 scratch seam
   (marker names a scratch entry the agent can `read_file`) was weighed
   and deferred to a named follow-up: writing scratch from the dispatch
   hook turns every oversized *read* into a state mutation inside the
   audit choke point, system-written entries would consume the agent's
   `SCRATCH_MAX_ENTRIES_PER_SCOPE` (20) quota, and
   `SCRATCH_MAX_ENTRY_BYTES` (256 KiB) truncates the "full" copy anyway.
3. **Structure-aware rule: only free-text results are cut.** A result is
   truncated iff it is a plain `str` and its definition declares no
   `output_model`. Everything else — mappings, sequences, `BaseModel`
   instances, `ToolReturn` rich results, and anything covered by a
   declared `output_model` — is exempt: blind string surgery on serialized
   structures corrupts JSON and would break the very output contract
   `validate_output` just enforced. Exempt results are still *measured*
   (best-effort serialized length) and flagged when oversized (decision
   4), so structured blowouts stay visible. Delegation already returns a
   bounded structured `DelegateRunResult` — exempt by construction.
4. **No silent cuts.** The per-invocation audit row's `details` gains
   `result_chars`, `result_truncated`, and `result_original_chars` (set
   only when truncated); a `logger.warning` fires on every truncation and
   on any exempt result measuring over the limit. This rides the existing
   `record_invocation` → `details=json_safe_details` seam — no schema
   change, no new audit columns.
5. **Calibrated token estimation, no tokenizer.** New `utils/tokens.py`
   with `estimate_tokens(text, *, chars_per_token: float = 4.0) -> int`:
   ASCII characters divide by `chars_per_token`; non-ASCII characters
   count one token each (a conservative floor that fixes the CJK
   under-count without any dependency). `ModelInfo` gains
   `chars_per_token: float = 4.0` so per-model calibration is a one-line
   catalog edit informed by offline measurement. Rejected: a per-provider
   tokenizer (056 decision 7 already rejected it; that stands) and
   provider count-tokens round-trips anywhere in the turn path (fine for
   *offline* recalibration of the catalog constants only). 056 gets an
   amendment block pointing its decision-5 estimator here.
6. **Determinism is a tested invariant.** Truncation is a pure function of
   `(result, limit)`: same input, same truncated bytes, every time. The
   truncated result is the stored result, so 013's byte-stable-prefix
   property holds by construction and the approval-resume snapshot replays
   identical content. A determinism test guards this the way 056's
   byte-stability pin guards its injection.

## Why this matters

Trimming and compaction manage *many turns*; nothing today stops *one
turn* from torching the window, the cache, and the bill in a single tool
call. Bounding at dispatch means every tool — landed, delegated, and every
041 provider tool to come — inherits the bound with zero per-tool code,
exactly as they inherit audit and envelope checks. Shipping the calibrated
estimator now means 056 and every later window tenant budget against one
shared, honestly-labeled approximation instead of scattering `//4` around.

## Current state

All anchors verified on the working tree at `6be5491` (2026-07-07).

- **Dispatch success path returns results unbounded**:
  `services/agents/runtime/dispatch.py` — `result = await handler(args)`
  (line 166), `validate_output(definition, result)` (lines 199-200), the
  success audit (lines 218-230), then `return result` (line 231). Nothing
  measures or bounds the result. The hook mount delegating here is
  `capabilities.py:21-29` (`@hooks.on.tool_execute`).
- **The wrap-don't-layer contract**: the module docstring
  (`dispatch.py:18-21`) — hooks "keep timing, envelope checks, output
  validation, mutation warnings, and audit emission in one
  invocation-local scope. Future instrumentation should wrap this module
  rather than adding another interception layer." Truncation joins that
  scope as a sibling of `validate_output`; it does not add a layer.
- **Tool contract**: `services/agents/runtime/tools/contract.py` —
  `RuntimeToolDefinition` (lines 77-102) carries `effect`,
  `default_policy`, `output_model`, `presentation`, etc.; **no result
  size field**. `validate_definition` (lines 154-213) is the import-time
  invariant seam. 054 adds `effect_scope` here — additive, no conflict.
- **Unbounded string tool, landed**: `services/agents/runtime/skills.py`
  — `read_skill_document(...) -> str` (lines 131-135) returns the whole
  converted markdown document (lines 158-162), mounted through a skill
  capability's `tools=[...]` (line 58), not the agent `tools=` argument;
  the dispatch docstring's hook probe covered agent-mounted tools only,
  so capability-mounted coverage needs a probe (Step 1).
- **Self-bounded pattern this generalizes**: `slice_text`
  (`runtime/tools/files/utils.py:67-105`) caps `read_file` content at
  `READ_FILE_MAX_CONTENT_BYTES` with a `truncated`/`hint` continuation.
  That convention stays; dispatch backstops tools that lack one.
- **Delegation**: `delegation/delegate_to_agent.py:44-49` returns a
  `DelegateRunResult` ("a bounded structured result") — exempt under
  decision 3.
- **Audit seam**: `services/audit_events/tool_events.py` —
  `record_tool_invocation_audit_event` (line 34) writes
  `details=json_safe_details({...})` (line 77) with `args_sha256`,
  `latency_ms`, `outcome`, etc. — the extension point for decision 4.
- **Token accounting**: `estimate_tokens` and `chars_per_token` appear
  nowhere in `apps/api` (grep-verified). 056 decision 5 *plans*
  `utils/tokens.py` with a chars//4 heuristic and decision 7 rejects
  per-provider tokenizers; this plan lands the utility first, calibrated.
- **Catalog**: `services/agents/models/domain.py:43-55` — frozen
  `ModelInfo(provider, model, display_name, context_window, ...)`; every
  `registry.py` entry (lines 19-132) carries `context_window`. `ModelInfo`
  is the home for `chars_per_token`. Settings live in
  `core/settings/agents.py:8-93` (`AgentRunSettingsMixin`, including the
  nullable `AGENT_HISTORY_MAX_TURNS` pattern to copy).
- **Persistence**: run persistence appends `new_messages()` only (013's
  verified excerpts) — the dispatch-returned result *is* the stored
  `ToolReturnPart` content, which makes production-time truncation
  cache-stable and replay-stable.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Focused tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agents/runtime tests/contract -q` | all pass |
| Full suite | `make api-test` (starts local Postgres, sets `TEST_DATABASE_URL`) | all pass, no DB skips |

## Scope

**In scope:**

- `services/agents/runtime/dispatch.py` (truncation + measurement in the
  invocation-local scope; audit field threading)
- `services/agents/runtime/tools/contract.py` (`max_result_chars` +
  import-time invariant)
- `services/audit_events/tool_events.py` (optional `result_*` params into
  `details`)
- `utils/tokens.py` (create — `estimate_tokens`)
- `services/agents/models/domain.py` / `registry.py`
  (`chars_per_token` field + per-entry values)
- `core/settings/agents.py` (`AGENT_TOOL_RESULT_MAX_CHARS`)
- `docs/plans/056-context-compaction.md` (amendment block: decision-5
  estimator consumes `utils/tokens.py` from this plan)
- Tests: dispatch truncation units, contract invariant, estimator math,
  end-to-end FunctionModel case

**Out of scope (do NOT touch):**

- History trimming (`history.py`) and compaction — 013 landed, 056 owns
  summaries; this plan changes neither.
- Retroactive truncation of already-persisted tool results (rejected —
  mid-prefix cache edit; see Product intent).
- Scratch spillover of full outputs (named follow-up, decision 2) and
  recursive truncation inside structured results (decision 3).
- SSE protocol, frontend, per-workspace/per-agent limit overrides.

## Git workflow

- Branch: `advisor/076-tool-result-truncation`
- Commit: `API - Bounded Tool Results & Token Calibration`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: probe hook coverage for capability-mounted tools

Run a `FunctionModel` test mounting a skill capability whose `tools=[...]`
tool returns a long string; assert whether the `tool_execute` hook fires.
Record the finding where truncation lands. If capability-mounted tools
bypass the hook, `read_skill_document` does not inherit the bound — bound
it at its return site in `skills.py` as a one-off and note the gap.

**Verify**: probe result recorded; no ambiguity about which tools inherit.

### Step 2: estimator + catalog calibration

Create `utils/tokens.py` per decision 5. Add
`chars_per_token: float = 4.0` to `ModelInfo`; set per-entry values from a
one-off offline measurement (default 4.0 is acceptable v1 for all entries
if measurement is deferred — the field existing is the seam 056 needs).

**Verify**: estimator unit tests — ASCII text of length N gives
`ceil(N / divisor)`; a CJK string of N chars gives ≥ N; empty gives 0.

### Step 3: setting + contract field

Add `AGENT_TOOL_RESULT_MAX_CHARS: int | None` (default 16_000, `gt=0`,
nullable disables) to `AgentRunSettingsMixin`. Add
`max_result_chars: int | None = None` to `RuntimeToolDefinition` with a
`validate_definition` invariant rejecting values `< 1`. Expose nothing new
through the catalog route — the bound is runtime policy, not UI metadata.

**Verify**: `uv run pytest tests/contract -q` passes; invalid override
raises at import time in a unit test.

### Step 4: dispatch truncation

In `dispatch.py`, add a pure helper `truncate_result(definition, result,
*, default_limit)` returning the (possibly cut) result plus a truncation
record, implementing decisions 1-3: limit = per-tool override or settings
default; head 80% / tail 20% of the budget; deterministic marker with
elided char count and `estimate_tokens` figure; `str`-without-
`output_model` only. Apply it on the success path after `validate_output`
and before the success `record_invocation`; measure exempt results
best-effort and log when oversized. Read the setting at call time, not
import time, so tests can patch it.

**Verify**: unit tests over the helper (bound, marker, exemptions,
determinism); existing dispatch tests pass unchanged.

### Step 5: audit visibility

Thread `result_chars` / `result_truncated` / `result_original_chars`
through `record_invocation` into
`record_tool_invocation_audit_event(details=...)` as optional keyword
params defaulting to absent, so denial/approval/failure call sites are
untouched.

**Verify**: DB-backed dispatch test asserts the success audit row's
`details` carries the truncation fields for an oversized string result.

### Step 6: end-to-end + 056 amendment

FunctionModel run with a scripted tool returning an oversized string:
assert the model-visible tool return and the persisted messages both carry
the truncated content with the marker (same bytes). Add an amendment block
to `docs/plans/056-context-compaction.md`: decision 5's `estimate_tokens`
is implemented by this plan's `utils/tokens.py` with per-model
`chars_per_token` — consume, do not re-create.

**Verify**: `make api-test` green; 056 contains the amendment.

## Test plan

~12 deterministic tests, no live LLM:

1. Over-limit string → length ≤ limit + marker length; head and tail are
   the original prefix and suffix.
2. Marker states the exact elided char count and estimated tokens.
3. At/under limit → returned unchanged (same object).
4. `None` setting disables truncation entirely.
5. Per-tool `max_result_chars` overrides the default (both directions).
6. Exemptions: dict result, `ToolReturn` result, and a str-returning
   definition *with* `output_model` are never cut.
7. Oversized exempt dict → warning + audit `result_chars`, content intact.
8. Determinism: identical input twice → byte-identical output (the
   cache-stability pin).
9. Contract invariant: `max_result_chars=0` rejected at import time.
10. Estimator math: ASCII, CJK floor, divisor, empty string.
11. Audit fields present on truncation, absent otherwise (DB-backed).
12. FunctionModel end-to-end: truncated content is what the model sees and
    what persists; approval-resume replay is byte-identical.

## Done criteria

- [x] `grep -n "AGENT_TOOL_RESULT_MAX_CHARS" apps/api/core/settings/agents.py`
      and `grep -n "max_result_chars"
      apps/api/services/agents/runtime/tools/contract.py` both hit
- [x] `grep -n "estimate_tokens" apps/api/utils/tokens.py` and
      `grep -n "chars_per_token" apps/api/services/agents/models/domain.py`
      both hit
- [x] Oversized string tool results are bounded with a head+tail marker;
      structured results are never cut (tests 1-7 pass)
- [x] Truncation is deterministic and audit-visible (tests 8, 11, 12 pass)
- [x] `docs/plans/056-context-compaction.md` carries the estimator
      amendment block
- [x] `make api-test` green; `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Truncation cannot live inside `dispatch_tool_execution`'s
  invocation-local scope without a second interception layer — the module
  docstring's wrap-don't-layer contract is the law; report the tension
  rather than adding a wrapper capability.
- Structured outputs cannot be exempted cleanly — e.g. a landed tool
  returns huge free text nested inside a dict and the honest rule leaves
  it unbounded in practice — stop and report; do not invent recursive
  structure-aware truncation.
- The Step 1 probe shows catalog function tools bypassing the
  `tool_execute` hook — the choke-point premise is broken; report before
  relocating the bound.
- An approval-resume or history test fails because a replayed tool result
  changed bytes — determinism is violated; report the diff.
- You are tempted to truncate persisted history rows or trim inside
  `history.py` — that is the rejected retroactive variant.

## Maintenance notes

- **Plan 041** providers must treat the default bound as the design
  budget: output models should carry free text in bounded designated
  fields, and any `max_result_chars` override must be declared
  deliberately with a review-visible rationale — a thoughtless override
  is a blocking review defect.
- **Plan 056** consumes `estimate_tokens` with the resolved model's
  `chars_per_token` for its pressure trigger; if the estimator drifts for
  a provider, recalibrate the catalog constant offline (count-tokens
  endpoints are fine there — never in the turn path).
- **Gate G5**: once 055 lands, add a scenario where a scripted tool
  returns an oversized result and the agent visibly recovers via the
  marker's guidance.
- The scratch-spillover follow-up (decision 2) becomes worth planning
  when a real workflow needs the elided remainder more than once per
  conversation; it needs system-entry quota semantics on the 034 scratch
  table first.
- Reviewers should scrutinize: the determinism test, the exemption rule's
  boundary (str + no `output_model`), and that no code path truncates
  before `validate_output` runs on the full result.
