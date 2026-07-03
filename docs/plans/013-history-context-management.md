# Plan 013: Bound model context with a ProcessHistory trimming capability

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat 1a51665..HEAD -- apps/api/services/agents/runtime apps/api/core/settings/agents.py apps/api/tests/services/agents/runtime`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (a wrong trim can produce provider-rejected histories or lose context silently)
- **Depends on**: **execute AFTER plan 018** (roadmap constraint, D2/README):
  trimming must preserve `LoadCapabilityCallPart`/`LoadCapabilityReturnPart`
  pairs or agents silently lose loaded skills on resume — see the
  capability-load invariant below. Compatible with 011/012 (both DONE).
- **Category**: tech-debt / correctness-at-scale
- **Planned at**: commit `1a51665`, 2026-07-01

## Why this matters

Every turn feeds the *entire* stored conversation into the model. The code
admits this is a stopgap — `persistence.py:27-28`: "Pending: this intentionally
returns the full stored history. Add trimming or summarization before treating
long-running conversations as context-safe." Long conversations will eventually
exceed provider context windows (hard failure) and, before that, cost linearly
more per turn. The supported lever in Pydantic AI 2.x is the `ProcessHistory`
capability: it runs before each model request, mutates only what the model
sees, and leaves persisted rows untouched — exactly the split the repo's
intent doc prescribes (`docs/pydantic-ai/06-messages-and-history.md`, "How
Praxis should use this": "Use a `ProcessHistory` capability for context-window
management … Persisted `ConversationMessage` history stays complete; the
processor decides what the model sees per request.").

## Current state

- `apps/api/services/agents/runtime/persistence.py:20-45` —
  `load_message_history` returns the full validated history (docstring quoted
  above). Do NOT change what it returns; trimming happens at request time.

- `apps/api/services/agents/runtime/capabilities.py` — the capability assembly
  point; currently returns one `Hooks` capability with tool logging:

  ```python
  # capabilities.py:15-21
  def build_runtime_capabilities(_agent: Agent) -> list[AgentCapability[RuntimeDeps]]:
      """Return capabilities attached to every runtime agent. ..."""
      hooks = Hooks(id="praxis-runtime-hooks")
  ```

  New runtime capabilities are appended to this list. The consuming site is
  `loop.py:71` (`capabilities=build_runtime_capabilities(agent)` — moved from
  line 46 by the delegation commit `f83d210`).

- Verified against installed `pydantic-ai==2.1.0`:
  `from pydantic_ai.capabilities import ProcessHistory` works.
  `ProcessHistory(processor)` accepts a sync or async function
  `(list[ModelMessage]) -> list[ModelMessage]`, optionally taking `RunContext`
  as first parameter. The old `Agent(history_processors=...)` kwarg is
  **removed** in 2.x — do not use it.

- Message shapes (from `docs/pydantic-ai/06-messages-and-history.md`, verified
  in the installed package): `ModelMessage = ModelRequest | ModelResponse`,
  discriminated by `kind` (`'request'`/`'response'`). `ModelRequest.parts` may
  contain `UserPromptPart` (`part_kind == 'user-prompt'`), `ToolReturnPart`
  (`'tool-return'`), `RetryPromptPart` (`'retry-prompt'`), etc.
  **Critical invariant**: every `ToolCallPart` in a `ModelResponse` must keep
  its matching `ToolReturnPart`/`RetryPromptPart` in a later `ModelRequest`
  (paired by `tool_call_id`) — "Dropping a `ToolCallPart` without its matching
  return (or vice versa) via a processor produces an invalid history that some
  providers reject" (06 doc, Gotchas).

- The runtime uses `instructions=` (not `system_prompt=`) — `loop.py:64`,
  now assembled via `_runtime_instructions(agent, include_delegation=...)`
  (which may append `DELEGATION_INSTRUCTIONS`) — so instructions are re-sent
  on every request regardless of history content. No `ReinjectSystemPrompt`
  is needed; trimming cannot lose the system prompt.

- **Capability-load invariant (plan 018 interaction — the reason this plan
  runs after 018).** Once 018 lands, loaded-skill state is reconstructed
  from `LoadCapabilityCallPart`/`LoadCapabilityReturnPart` pairs in history
  (both live in `pydantic_ai.messages` and subclass
  `ToolCallPart`/`ToolReturnPart`). A trimmer that drops them silently
  un-loads skills on resume. Turn-boundary trimming keeps pairs *within* a
  kept turn, but does NOT protect a kept turn that depends on a capability
  loaded in a trimmed *earlier* turn — that cross-turn hazard must be
  handled explicitly (see Step 2 requirement 3).

- The approval resume path (`resume_run_stream.py` →
  `execute_run(message_history=..., deferred_tool_results=...)`) replays a
  rehydrated history that ends with pending tool calls. The processor runs on
  that path too — the turn-boundary rule below must never separate those
  trailing tool calls from their results.

- Settings style: `apps/api/core/settings/agents.py` (`AgentRunSettingsMixin`,
  `Field(default=..., gt=0, description=...)`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Focused tests | `cd apps/api && uv run pytest tests/services/agents/runtime -q` | all pass |
| Full API tests | `cd apps/api && uv run pytest -q` | all pass |

## Scope

**In scope**:
- `apps/api/services/agents/runtime/history.py` (create — the trimming processor)
- `apps/api/services/agents/runtime/capabilities.py` (register `ProcessHistory`)
- `apps/api/core/settings/agents.py` (the turn-budget setting)
- `apps/api/tests/services/agents/runtime/test_history_trimming.py` (create)
- `docs/plans/000_README.md` (status row)

**Out of scope**:
- `persistence.py` — stored rows stay full-fidelity; do not trim at load or save.
- Summarization of old turns with a cheaper agent — explicitly deferred (see
  Maintenance notes); this plan ships count-based trimming only.
- Token counting (`count_tokens_before_request` or tiktoken estimates) — v2 of
  this feature; keep v1 deterministic and cheap.
- `approval_state.py` snapshot contents.

## Git workflow

- Branch: `advisor/013-history-context-management`
- Commit style: `API - History Context Trimming`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the setting

In `apps/api/core/settings/agents.py`, add to `AgentRunSettingsMixin`:

```python
AGENT_HISTORY_MAX_TURNS: int | None = Field(
    default=40,
    gt=0,
    description="Maximum prior user turns sent to the model per request; None sends full history.",
)
```

**Verify**: `cd apps/api && uv run ruff check core/settings/agents.py` → exit 0

### Step 2: Implement the trimming processor

Create `apps/api/services/agents/runtime/history.py`. Requirements:

1. A pure function `trim_history(messages: list[ModelMessage], *, max_turns: int) -> list[ModelMessage]`:
   - Define a **turn boundary** as a `ModelRequest` whose parts include a
     `UserPromptPart` (`part_kind == 'user-prompt'`, check via
     `isinstance(part, UserPromptPart)` — the repo convention is isinstance
     over discriminator strings).
   - Walk boundaries from the end; keep everything from the `max_turns`-th
     boundary (counting backward) onward. Cutting only at user-turn boundaries
     guarantees tool-call/return pairs are never split (a tool chain never
     spans a user turn).
   - If there are `<= max_turns` boundaries, or no boundary exists before the
     cut point, return the input list unchanged.
   - Never trim to an empty list; the resumed-approval history (which may have
     trailing tool calls after the last user turn) must always retain the
     final user turn onward intact — the boundary rule above already
     guarantees this, add a test for it rather than special-case code.
2. A processor factory `history_trimmer()` returning the function wired to
   `settings.AGENT_HISTORY_MAX_TURNS` (no-op passthrough when the setting is
   `None`). Read the setting at call time, not import time, so tests can
   patch it.
3. **Preserve capability loads across the cut (018 invariant).** Before
   discarding trimmed turns, scan them for
   `LoadCapabilityCallPart`/`LoadCapabilityReturnPart` pairs
   (`pydantic_ai.messages`; identifiable via `tool_kind ==
   "capability-load"`) and re-prepend each surviving pair (call + return,
   in order) ahead of the kept turns, so capabilities loaded in trimmed
   turns remain loaded for the model. Add a test asserting a
   `LoadCapability*` pair from a trimmed turn survives trimming.

Match the module docstring/comment style of neighbors (single terse lines; see
`events.py`, `persistence.py`).

**Verify**: `cd apps/api && uv run ruff check services/agents/runtime/history.py` → exit 0

### Step 3: Register the capability

In `apps/api/services/agents/runtime/capabilities.py`, import `ProcessHistory`
from `pydantic_ai.capabilities` and `history_trimmer` from
`services.agents.runtime.history`, and return
`[hooks, ProcessHistory(history_trimmer())]` (order: hooks first, matching the
current list; `ProcessHistory` position does not affect the hooks).

**Verify**: `cd apps/api && uv run pytest tests/services/agents/runtime -q` → all existing tests pass

### Step 4: Tests

Create `apps/api/tests/services/agents/runtime/test_history_trimming.py`
(async marker + structure modeled on
`apps/api/tests/services/agents/runtime/test_pydantic_ai_spike.py`):

1. **Unit — boundary math**: build a synthetic history of N user turns
   (ModelRequest with `UserPromptPart` + ModelResponse pairs, including one
   turn with a `ToolCallPart`/`ToolReturnPart` chain); assert
   `trim_history(..., max_turns=2)` keeps exactly the last 2 turns and the tool
   chain inside a kept turn is complete (every `tool_call_id` in kept responses
   has its return part present).
2. **Unit — under budget**: `len(boundaries) <= max_turns` returns the list
   unchanged (identity, same objects).
3. **Unit — resume shape**: a history ending in a `ModelResponse` with a
   trailing `ToolCallPart` after the last user turn (the suspended-approval
   shape) keeps that tail intact under any `max_turns >= 1`.
4. **Integration — what the model sees**: use
   `pydantic_ai.models.function.FunctionModel` with a capture function (pattern
   in `docs/pydantic-ai/06-messages-and-history.md:190-205`): build an `Agent`
   with `capabilities=[ProcessHistory(history_trimmer())]`, patch
   `AGENT_HISTORY_MAX_TURNS=1`, run with a long `message_history`, and assert
   the captured request contains only the final prior turn plus the new prompt.
5. **Integration — disabled**: with the setting patched to `None`, the captured
   messages equal the full input history plus the new prompt.
6. **Unit — capability-load survival**: a history where turn 1 contains a
   `LoadCapabilityCallPart`/`LoadCapabilityReturnPart` pair and
   `max_turns=1` keeps the pair (re-prepended) alongside the final turn.

**Verify**: `cd apps/api && uv run pytest tests/services/agents/runtime/test_history_trimming.py -q` → all pass

### Step 5: Full check

**Verify**: `cd apps/api && uv run ruff check . && uv run pytest -q` → exit 0, all pass

## Test plan

See Step 4 — the tool-pairing invariant (cases 1 and 3) is the regression this
plan must never allow; the FunctionModel capture (case 4) proves the capability
is actually wired into the runtime agent, not just unit-correct.

## Done criteria

- [ ] `cd apps/api && uv run ruff check .` exits 0
- [ ] `cd apps/api && uv run pytest -q` exits 0; the 5 new tests exist and pass
- [ ] `grep -n "ProcessHistory" apps/api/services/agents/runtime/capabilities.py` shows the registration
- [ ] `load_message_history` in `persistence.py` is unmodified (`git diff --stat` shows no change to that file)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back if:

- Plan 018 is not DONE (this plan must trim histories that already carry
  capability-load parts, with the preservation rule tested — not land first
  and hope).
- `ProcessHistory` import fails or rejects a plain callable (package drift).
- The FunctionModel capture shows the processor NOT running on the
  `run_stream_events` path (capability registered but never invoked) — that
  invalidates the approach; report before working around it.
- Existing approval resume tests
  (`test_execute_run_resumes_approved_tool_and_clears_approval_state`) fail
  after registration — the trim is interacting with rehydrated histories in an
  unexpected way; report the failing shape.

## Maintenance notes

- v2 of this feature is token-aware budgeting and/or summarizing old turns with
  a cheaper agent (`docs/pydantic-ai/06-messages-and-history.md:171-176` has
  the pattern). The `history.py` seam added here is where that lands; the
  setting then becomes a token budget rather than a turn count.
- If per-agent context policies land on the Agent row later,
  `build_runtime_capabilities(_agent)` already receives the agent — thread the
  override through there.
- Reviewers should scrutinize the turn-boundary definition against real
  multi-tool histories (especially denied-tool `retry-prompt` shapes) before
  merge.
- This plan honors plan 018's maintenance note: history trimming MUST
  preserve `LoadCapabilityCallPart`/`LoadCapabilityReturnPart` pairs
  (Step 2 requirement 3). If 018 has not landed when this executes, STOP —
  the ordering is a roadmap constraint, not a suggestion.
