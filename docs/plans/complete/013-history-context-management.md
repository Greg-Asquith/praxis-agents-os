# Plan 013: Bound model context with a cache-stable ProcessHistory trimming capability

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat 6f65cc7..HEAD -- apps/api/services/agents/runtime apps/api/services/agents/models/factory.py apps/api/core/settings/agents.py apps/api/tests/services/agents`
> If any in-scope file changed since this plan was revised, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: HIGH (a wrong trim can produce provider-rejected histories, lose
  context silently, or silently destroy prompt-cache hit rates)
- **Depends on**: plan 018 (DONE, verified 2026-07-03) — trimming must preserve
  `LoadCapabilityCallPart`/`LoadCapabilityReturnPart` pairs or agents silently
  lose loaded skills; see the capability-load invariant below.
- **Category**: tech-debt / correctness-at-scale / cost
- **Planned at**: commit `1a51665`, 2026-07-01
- **Revised at**: commit `6f65cc7`, 2026-07-03 — after verifying `ProcessHistory`
  semantics against installed `pydantic-ai==2.1.0` and researching provider
  prompt-cache behavior. Three material changes: (1) the rolling per-turn
  window was replaced with chunked watermark trimming so provider prefix
  caches keep hitting, (2) the capability-load preservation rule was moved to
  a provider-valid insertion point (the original rule produced assistant-first
  histories some providers reject), (3) a provider-boundary caching step was
  added for parity: OpenAI/Google cache prompt prefixes automatically, while
  Anthropic requires explicit opt-in.

## Why this matters

Every turn feeds the *entire* stored conversation into the model. The code
admits this is a stopgap — `persistence.py:27-28`: "Pending: this intentionally
returns the full stored history. Add trimming or summarization before treating
long-running conversations as context-safe." Long conversations will eventually
exceed provider context windows (hard failure) and, before that, cost linearly
more per turn.

Cost has a second axis: **provider prompt caching**. All major providers cache
by exact prompt prefix — cached input tokens cost roughly 10% of fresh ones,
and agent workloads are overwhelmingly input-heavy. Two consequences shape this
plan:

1. **A rolling "keep last N turns" window is an anti-pattern.** Once a
   conversation passes N, every request drops the oldest turn and shifts the
   whole prefix, so every request is a full cache miss — exactly when
   conversations are longest and most expensive. Trimming must instead be
   **chunked**: append-only for many turns, then one large cut, so the prefix
   stays byte-stable between cuts. This is provider-agnostic — it is what makes
   OpenAI's and Google's *automatic* prefix caching hit, and it is the same
   property Anthropic's explicit cache needs.
2. **Anthropic caches nothing unless asked.** OpenAI and Google cache eligible
   prefixes automatically; Anthropic requires explicit cache markers on the
   request. For parity, this plan enables them at the provider boundary
   (`models/factory.py`) — the one file that already branches per provider —
   so no provider-specific knowledge leaks into the runtime or the trimmer.

The supported trimming lever in Pydantic AI 2.x is the `ProcessHistory`
capability, run before each model request. Its real semantics in 2.1.0 are
stronger than "a view for the model" — see Current state — and the plan
accounts for that.

## Current state

- `apps/api/services/agents/runtime/persistence.py:20-45` —
  `load_message_history` returns the full validated history (docstring quoted
  above). Do NOT change what it returns; trimming happens at request time.
  Each turn therefore re-derives the trim from the full stored history — which
  is why the cut point must be a deterministic, chunked function of that
  history (otherwise it slides every turn and defeats caching).

- `apps/api/services/agents/runtime/capabilities.py:12-30` — the capability
  assembly point; currently returns one `Hooks(id="praxis-runtime-hooks")`
  capability whose `tool_execute` hook delegates to `dispatch_tool_execution`.
  New runtime capabilities are appended to the returned list. The consuming
  site is `loop.py:67-71`, which composes three sources:

  ```python
  capabilities=[
      *build_runtime_capabilities(agent),
      *build_runtime_native_capabilities(agent, resolved_model),
      *build_skill_capabilities(skills),
  ],
  ```

- **`ProcessHistory` semantics, verified against installed
  `pydantic-ai==2.1.0`** (`from pydantic_ai.capabilities import ProcessHistory`
  works; it accepts a sync or async `(list[ModelMessage]) -> list[ModelMessage]`,
  optionally taking a `RunContext`-annotated first parameter; the old
  `Agent(history_processors=...)` kwarg is removed in 2.x):
  - The processor runs before **every model request step**, and its output is
    written back into the run's canonical history
    (`_agent_graph.py:948`: `ctx.state.message_history[:] = messages`). So
    `result.all_messages()` returns the **processed** list, and the next step's
    framework state is derived from it. The repo digest's claim that processors
    "mutate what the model sees, not what you persist"
    (`docs/pydantic-ai/06-messages-and-history.md:215`) is inaccurate for
    2.1.0 — correct it in plan 015.
  - Praxis DB rows nevertheless stay full-fidelity because persistence appends
    `terminal_result.new_messages()` only (`run_persistence.py:60-66,110-117`),
    and `new_messages()` slices by the current run — trimmed *old* messages are
    already stored from prior turns.
  - **The approval-suspension snapshot is post-trim**: `run_persistence.py:73-78`
    stores `terminal_result.all_messages()` into the suspended-run metadata, and
    `resume_run_stream.py:88-97` replays that snapshot as `message_history`. So
    a resumed run rehydrates the *trimmed* history; the trimmer must be
    idempotent and the preserved-capability rule below must hold in that
    snapshot.
  - Framework validation requires the processed history to be non-empty and to
    end with a `ModelRequest`.

- **Capability-load state (plan 018 interaction).** `LoadCapabilityCallPart` /
  `LoadCapabilityReturnPart` (importable from `pydantic_ai.messages`; typed
  subclasses of `ToolCallPart`/`ToolReturnPart` with
  `tool_kind == "capability-load"`) are how the framework knows which deferred
  capabilities are loaded: it rescans `ctx.state.message_history` for the pairs
  **before every request step** and re-seeds from raw `message_history` at run
  start. Because the processor's output becomes that state, a trimmer that
  drops the pairs un-loads the skill from the next step onward and in the
  suspension snapshot. Turn-boundary trimming keeps pairs *within* a kept turn
  but does not protect a kept turn that depends on a capability loaded in a
  trimmed earlier turn — that cross-turn hazard is handled explicitly (Step 2
  requirement 3). Note `apps/api` currently references the load tool only via
  string checks (`execute_run.py:236`); this plan introduces the first typed
  usage.

- **Message-shape invariants for a valid trim** (verified in the installed
  package and provider mappings):
  - Every `ToolCallPart` in a `ModelResponse` must keep its matching
    `ToolReturnPart`/`RetryPromptPart` (paired by `tool_call_id`); orphans in
    either direction are rejected by providers.
  - **The trimmed history must start with a user-role message.** Some provider
    APIs reject assistant-first message lists outright; pydantic-ai's mappings
    do not guard this. Cut points must therefore land on a `ModelRequest` that
    opens a user turn.
  - A `ModelRequest` can carry **both** tool-return parts and a
    `UserPromptPart` (pydantic-ai merges consecutive requests, tool returns
    sorted first). Such a request is NOT a safe cut point — cutting there
    orphans the preceding response's tool calls.

- The runtime uses `instructions=` (`loop.py:60-63`), re-sent on every request
  regardless of history content; trimming cannot lose the system prompt. The
  instruction blocks are static strings (identity/planning/delegation) with no
  timestamps or per-request values — already prefix-stable.

- **Cache observability already exists**: `run_persistence.py:162` maps
  `usage.cache_read_tokens` into `input_tokens_cached` on the run row. That
  column is how this plan's caching claims get validated in real traffic — no
  new hot column is needed for this plan. Pydantic AI's `RunUsage` also exposes
  `cache_write_tokens`; keep the existing raw `usage_json` preservation intact
  and test that cache-write/creation tokens are not dropped, since they explain
  whether Anthropic cache markers are creating cache entries or only reading
  existing ones.

- `apps/api/services/agents/models/factory.py:33-60` — `build_model` sets
  `model_settings = dict(spec.settings) or None` and branches per provider
  (Anthropic / OpenAI Responses / Google / Azure). No caching configuration
  exists anywhere today. Agent-configurable settings are validated elsewhere to
  `thinking`/`temperature` only, so merged cache defaults cannot collide with
  agent-provided keys.

- Settings style: `apps/api/core/settings/agents.py` (`AgentRunSettingsMixin`,
  `Field(default=..., gt=0, description=...)`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Focused tests | `cd apps/api && uv run pytest tests/services/agents -q` | all pass |
| Full API tests | `cd apps/api && uv run pytest -q` | all pass |

## Scope

**In scope**:
- `apps/api/services/agents/runtime/history.py` (create — the trimming processor)
- `apps/api/services/agents/runtime/capabilities.py` (register `ProcessHistory`)
- `apps/api/services/agents/models/factory.py` (provider-native cache enablement)
- `apps/api/core/settings/agents.py` (turn budgets + cache toggle)
- `apps/api/core/settings/__init__.py` (cross-field validation only, if needed)
- `apps/api/tests/services/agents/runtime/test_history_trimming.py` (create)
- `apps/api/tests/services/agents/models/test_model_factory.py` (cache settings cases)
- `apps/api/tests/services/agents/runtime/test_run_persistence.py` (cache-write usage snapshot case)
- `docs/plans/000_README.md` (status row)
- `docs/plans/000_MASTER_ROADMAP.md` (Lane R / suggested-order status)

**Out of scope**:
- `persistence.py` — stored rows stay full-fidelity; do not trim at load or save.
- Summarization/compaction of old turns — deferred to v2. When it lands it must
  follow the same chunking rule: a compaction rewrites the whole prefix, so it
  must be rare and large, never incremental per turn.
- Token-aware budgeting — v2; the trigger becomes token-based (prior-run usage,
  not a tokenizer dependency) but must keep the chunked deterministic cut.
- Truncating/clearing large old tool outputs — v2 pressure valve; note it is a
  mid-prefix edit, so it must batch with the same watermark event.
- Per-conversation OpenAI cache routing keys — only matters at high
  request-rate-per-prefix scale and needs a per-request model-settings seam
  that does not exist; record in maintenance notes, do not build.
- Per-agent context policies; `approval_state.py` snapshot format.

## Git workflow

- Branch: `advisor/013-history-context-management`
- Commit style: `API - History Trimming & Prompt Caching`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the settings

In `apps/api/core/settings/agents.py`, add to `AgentRunSettingsMixin`:

```python
AGENT_HISTORY_MAX_TURNS: int | None = Field(
    default=40,
    gt=0,
    description="Prior-user-turn count that triggers a history trim; None sends full history.",
)
AGENT_HISTORY_KEEP_TURNS: int = Field(
    default=20,
    gt=0,
    description="Prior user turns retained after a trim; must be below AGENT_HISTORY_MAX_TURNS.",
)
AGENT_PROMPT_CACHE_ENABLED: bool = Field(
    default=True,
    description="Enable provider-native prompt caching where the provider needs explicit opt-in.",
)
```

If `AGENT_HISTORY_MAX_TURNS` is set and `AGENT_HISTORY_KEEP_TURNS >= AGENT_HISTORY_MAX_TURNS`,
reject at settings validation (the `model_validator` in
`core/settings/__init__.py` is the existing seam for cross-field checks).

**Verify**: `cd apps/api && uv run ruff check core/settings` → exit 0

### Step 2: Implement the trimming processor

Create `apps/api/services/agents/runtime/history.py`. Requirements:

1. A pure function
   `trim_history(messages: list[ModelMessage], *, max_turns: int, keep_turns: int) -> list[ModelMessage]`:
   - Treat messages from the currently executing run as the untrimmed tail
     when Pydantic AI has already stamped the last request with the current
     `run_id`; trim only the prior-history prefix and append the current-run
     tail unchanged. This keeps synthetic preserved capability-load pairs out
     of `result.new_messages()` without changing persistence.
   - Define a **turn boundary** as a `ModelRequest` whose parts include a
     `UserPromptPart` **and no `ToolReturnPart` or `RetryPromptPart`** (check
     via `isinstance`, the repo convention). The tool-part exclusion matters:
     pydantic-ai merges consecutive requests into `[tool returns..., user
     prompt]` shapes, and cutting at one orphans the preceding response's tool
     calls. Cutting only at clean boundaries guarantees tool pairs are never
     split and the trimmed history always starts with a user-turn request
     (providers reject assistant-first histories).
   - **Chunked watermark cut** — with `T` = number of boundaries and
     `B = max_turns - keep_turns`: if `T <= max_turns`, return the input list
     unchanged (identity, same object). Otherwise drop the oldest
     `((T - keep_turns) // B) * B` boundaries and keep everything from the
     next boundary onward. The cut index is a step function of `T`: it moves
     only once per `B` new turns, so the prompt prefix is byte-stable for `B`
     consecutive turns between cuts (this is the entire caching story — see
     Why this matters). Worked example (`max=40`, `keep=20`, `B=20`):

     | T (boundaries) | dropped | kept |
     |---|---|---|
     | 40 | 0 | 40 |
     | 41 | 20 | 21 |
     | 59 | 20 | 39 |
     | 60 | 40 | 20 |
     | 79 | 40 | 39 |
     | 80 | 60 | 20 |

   - The function must be **idempotent** (`trim(trim(h)) == trim(h)`): the
     approval-suspension snapshot stores the already-trimmed history and the
     processor re-runs on it at resume and on every step within a run.
   - Never trim to an empty list; a resumed-approval history ending in trailing
     tool calls after the last boundary keeps that tail intact by construction
     — test it rather than special-casing.
2. A processor factory `history_trimmer()` returning the function wired to
   `settings.AGENT_HISTORY_MAX_TURNS` / `AGENT_HISTORY_KEEP_TURNS` (no-op
   passthrough when max is `None`). Read settings at call time, not import
   time, so tests can patch them.
3. **Preserve capability loads across the cut (018 invariant).** Scan the
   dropped region for `LoadCapabilityCallPart`/`LoadCapabilityReturnPart`
   pairs (`pydantic_ai.messages`). Skip pairs whose capability id is loaded
   again inside the kept region (dedupe). Batch the surviving call parts into
   one synthetic `ModelResponse` and the matching return parts into one
   synthetic `ModelRequest`, and insert that pair **immediately after the
   first kept boundary request** — NOT before it. Placement rationale, both
   sides load-bearing:
   - before the first kept request the history becomes assistant-first, which
     providers reject;
   - the synthetic messages carry no run id, so they sit outside
     `new_messages()` and are never re-persisted as new rows.

Match the module docstring/comment style of neighbors (single terse lines; see
`events.py`, `persistence.py`).

**Verify**: `cd apps/api && uv run ruff check services/agents/runtime/history.py` → exit 0

### Step 3: Register the capability

In `apps/api/services/agents/runtime/capabilities.py`, import `ProcessHistory`
from `pydantic_ai.capabilities` and `history_trimmer` from
`services.agents.runtime.history`, and return
`[hooks, ProcessHistory(history_trimmer())]` (hooks first, matching the current
list; `Hooks` has no `before_model_request` handler, so relative order does not
affect it).

**Verify**: `cd apps/api && uv run pytest tests/services/agents/runtime -q` → all existing tests pass

### Step 4: Enable provider-native prompt caching at the provider boundary

In `apps/api/services/agents/models/factory.py`, when
`settings.AGENT_PROMPT_CACHE_ENABLED` is true and the provider is Anthropic,
merge cache defaults under the agent-provided settings (agent keys win):

```python
{"anthropic_cache": True, "anthropic_cache_instructions": True, "anthropic_cache_tool_definitions": True}
```

These are plain keys in the settings dict already passed to the model — no new
imports or types. They place stable cache breakpoints on the tool definitions
and static instructions plus an automatic breakpoint on the latest message;
the library enforces the provider's breakpoint limit. Default TTL (5 minutes)
is deliberate — do not add a TTL knob yet.

No changes for OpenAI, Google, or Azure: their prefix caching is automatic and
needs only the prefix stability Step 2 provides. Keep provider knowledge inside
this file; the runtime and trimmer stay provider-agnostic.

**Verify**: `cd apps/api && uv run pytest tests/services/agents/models -q` → all pass

### Step 5: Tests

Create `apps/api/tests/services/agents/runtime/test_history_trimming.py`
(async marker + structure modeled on
`apps/api/tests/services/agents/runtime/test_pydantic_ai_spike.py`), and extend
`apps/api/tests/services/agents/models/test_model_factory.py`:

1. **Unit — chunk math**: synthetic history of 41 user turns (one containing a
   `ToolCallPart`/`ToolReturnPart` chain); `max_turns=40, keep_turns=20` keeps
   exactly the last 21 turns and every kept `tool_call_id` has its return part.
2. **Unit — cut-point stability**: for T = 41…59 the first kept turn is the
   *same* turn (identity of the cut, not just the count); it moves at T = 60.
   This is the regression test for the caching design — a per-turn slide here
   is a silent cost bug even though all shape invariants still pass.
3. **Unit — identity under budget**: `T <= max_turns` returns the input list
   unchanged (same object).
4. **Unit — idempotency**: `trim(trim(h)) == trim(h)` for an over-budget history.
5. **Unit — merged-request boundary**: a `ModelRequest` containing
   `[ToolReturnPart, UserPromptPart]` is not used as a cut point.
6. **Unit — resume shape**: a history ending in a `ModelResponse` with trailing
   `ToolCallPart`s after the last boundary (suspended-approval shape) keeps
   that tail intact.
7. **Unit — user-first invariant**: for every trimmed output, the first message
   is a `ModelRequest` with a `UserPromptPart` and no tool parts — including
   when capability pairs are preserved.
8. **Unit — capability-load survival**: a pair loaded in a dropped turn is
   re-inserted after the first kept boundary request; a pair whose capability
   is re-loaded inside the kept region is not duplicated.
9. **Integration — what the model sees**: `pydantic_ai.models.function.FunctionModel`
   with a capture function (pattern in
   `docs/pydantic-ai/06-messages-and-history.md:190-205`): agent with
   `capabilities=[ProcessHistory(history_trimmer())]`, settings patched to
   `max_turns=2, keep_turns=1`, long `message_history`; assert the captured
   request contains only the expected tail plus the new prompt.
10. **Integration — disabled**: with `AGENT_HISTORY_MAX_TURNS=None`, captured
    messages equal the full input history plus the new prompt.
11. **Integration — persistence purity**: after a trimmed `FunctionModel` run,
    `result.new_messages()` contains only current-run messages (no preserved
    capability pairs, no prior-turn messages) — guards against
    double-persisting old rows, since `ProcessHistory` output replaces
    `all_messages()`.
12. **Factory — cache settings**: Anthropic model receives the three cache keys
    when enabled, none when disabled; agent-provided settings survive the
    merge and win on collision; OpenAI/Google/Azure settings are untouched
    either way.
13. **Usage accounting — cache creation visibility**: `usage_snapshot` preserves
    `cache_write_tokens` in `usage_json` while continuing to map
    `cache_read_tokens` to `input_tokens_cached`. Do not add a cache-write hot
    column in this plan; this is a regression guard for future billing/reporting.
14. **Stable-prefix guard**: add a focused deterministic-prefix test for the
    cache-sensitive inputs outside the trimmer: runtime instruction assembly
    returns the same string for the same agent/delegation inputs, and
    `build_runtime_tools` returns tools in deterministic order for the same
    configured agent. If this ever fails without a functional regression,
    reviewers should treat it as a prompt-cache cost regression.

**Verify**: `cd apps/api && uv run pytest tests/services/agents -q` → all pass

### Step 6: Full check

**Verify**: `cd apps/api && uv run ruff check . && uv run pytest -q` → exit 0, all pass

## Test plan

See Step 5. Three regressions this plan must never allow: split tool pairs
(cases 1, 5, 6), a sliding cut point (case 2 — the cost regression), and
polluted `new_messages()` (case 11 — the double-persistence regression). The
FunctionModel capture (case 9) proves the capability is actually wired into the
runtime agent, not just unit-correct.

## Done criteria

- [ ] `cd apps/api && uv run ruff check .` exits 0
- [ ] `cd apps/api && uv run pytest -q` exits 0; the new tests exist and pass
- [ ] `grep -n "ProcessHistory" apps/api/services/agents/runtime/capabilities.py` shows the registration
- [ ] `grep -n "anthropic_cache" apps/api/services/agents/models/factory.py` shows the gated merge
- [ ] `load_message_history` in `persistence.py` is unmodified (`git diff --stat` shows no change to that file)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back if:

- The drift check shows in-scope changes whose live code contradicts the
  "Current state" excerpts.
- `ProcessHistory` import fails, rejects a plain callable, or the installed
  Anthropic model settings reject the three cache keys (package drift).
- The FunctionModel capture shows the processor NOT running on the
  `run_stream_events` path (capability registered but never invoked) — that
  invalidates the approach; report before working around it.
- Case 11 fails — `new_messages()` containing trimmed-away or synthetic
  messages means old rows would be re-persisted; report the observed slice
  rather than filtering in persistence code.
- Existing approval resume tests
  (`test_execute_run_resumes_approved_tool_and_clears_approval_state`) fail
  after registration — the trim is interacting with rehydrated histories in an
  unexpected way; report the failing shape.

## Maintenance notes

- **Validating the cost claim in production**: `agent_runs.input_tokens_cached`
  (populated from `usage.cache_read_tokens` at `run_persistence.py:162`) is the
  metric. Healthy long conversations should show high cached-token ratios that
  dip once per `B` turns (the chunk cut) — a ratio near zero on long
  conversations means the prefix is unstable and the trimming design is being
  defeated somewhere.
- Prefix stability has two standing obligations outside this plan: instruction
  assembly must stay free of per-request values (timestamps, run ids), and
  `build_runtime_tools` must keep deterministic tool ordering. Reviewers should
  treat a violation of either as a caching regression even though nothing
  functionally breaks. If production cached-token ratios are unexpectedly low,
  add a donor-app-style debug diagnostic that logs stable hashes of the system
  prompt and provider-visible tool definitions; do not log raw prompts, tool
  schemas, credentials, or user content.
- v2 of this feature is token-aware triggering (from the prior run's persisted
  usage — not a tokenizer dependency) and/or summarizing trimmed turns with a
  cheaper agent (`docs/pydantic-ai/06-messages-and-history.md:171-176` has the
  pattern). Both must keep the chunked deterministic cut: a token trigger that
  re-cuts every turn, or a per-turn incremental summarizer, reintroduces the
  rolling-window cost bug. `history.py` is the seam.
- Clearing/truncating large old tool outputs is the cheapest v2 pressure valve
  (keeps the tool call, drops the bulky return content) but is a mid-prefix
  edit — batch it into the same watermark event as the turn cut.
- A per-conversation OpenAI cache routing key (`openai_prompt_cache_key` in
  run-level model settings) can improve hit rates under high parallel load;
  it needs a per-request model-settings seam in `execute_run`. Not worth
  building until traffic justifies it.
- If per-agent context policies land on the Agent row later,
  `build_runtime_capabilities(_agent)` already receives the agent — thread the
  override through there.
- `docs/pydantic-ai/06-messages-and-history.md:215` ("Processors mutate what
  the model sees, not what you persist") is wrong for pydantic-ai 2.1.0 —
  processed output replaces `all_messages()`; Praxis stays full-fidelity only
  because persistence appends `new_messages()`. Fix the digest in plan 015.
