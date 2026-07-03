# Plan 011: Cap per-run token spend with UsageLimits token limits

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat 1a51665..HEAD -- apps/api/services/agents/runtime/loop.py apps/api/core/settings/agents.py apps/api/tests/services/agents/runtime`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (additive limit; disabled by default unless configured)
- **Depends on**: none
- **Category**: tech-debt / cost-protection
- **Planned at**: commit `1a51665`, 2026-07-01
- **Completed at**: 2026-07-03

## Why this matters

The runtime caps agent runs only by request count (`max_steps`); there is no
bound on token spend. A single run against a 1M-context model with a large
history can burn arbitrary tokens before the request limit trips. Pydantic AI
2.1.0's `UsageLimits` supports `total_tokens_limit`, `input_tokens_limit`,
`output_tokens_limit`, and `tool_calls_limit` — none are used. The repo's
intent doc (`docs/pydantic-ai/99-applying-to-praxis.md`, feature map row
"Usage limits") planned "per-run `request_limit`/token caps"; only the first
half landed.

## Current state

- `apps/api/services/agents/runtime/loop.py:49` — the only `UsageLimits` use:

  ```python
  usage_limits=UsageLimits(request_limit=resolved_model.max_steps),
  ```

  It is consumed in `apps/api/services/agents/runtime/execute_run.py:159`
  (`usage_limits=runtime_agent.usage_limits` passed to `run_stream_events`).

- Verified fields on the installed 2.1.0 `UsageLimits` dataclass:
  `request_limit` (default 50), `tool_calls_limit`, `input_tokens_limit`,
  `output_tokens_limit`, `total_tokens_limit`, `count_tokens_before_request`
  (all `None`/off by default except `request_limit`). Exceeding a limit raises
  `pydantic_ai.exceptions.UsageLimitExceeded` (exported from `pydantic_ai`).

- Failure handling already does the right thing: an exception in
  `execute_run`'s stream loop rolls back, calls `persist_failed_run` with
  `error_code=exc.__class__.__name__` (so `"UsageLimitExceeded"`), emits
  `error` + `done` SSE events, and re-raises (`execute_run.py:239-269`). No new
  failure plumbing is needed.

- `apps/api/core/settings/agents.py` — `AgentRunSettingsMixin` is where
  runtime knobs live; match its `Field(default=..., gt=0, description=...)`
  style.

- Convention: run-level limits come from settings; per-agent model choices come
  from the Agent row (`services/agents/models/resolution.py`). This plan adds a
  settings-level cap only — do NOT add DB columns.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Focused tests | `cd apps/api && uv run pytest tests/services/agents/runtime -q` | all pass |
| Full API tests | `cd apps/api && uv run pytest -q` | all pass |

## Scope

**In scope**:
- `apps/api/core/settings/agents.py`
- `apps/api/services/agents/runtime/loop.py`
- `apps/api/tests/services/agents/runtime/test_runtime_core.py` (extend)
- `docs/plans/000_README.md` (status row)

**Out of scope**:
- Per-agent or per-workspace token budgets (DB columns, admin UI) — future work.
- `count_tokens_before_request=True` — adds a provider round-trip per request;
  do not enable.
- Usage recording (`run_persistence.usage_snapshot`) — already works.

## Git workflow

- Branch: `advisor/011-token-usage-limits`
- Commit style: `API - Token Usage Limits`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the setting

In `apps/api/core/settings/agents.py`, add to `AgentRunSettingsMixin`:

```python
AGENT_RUN_TOTAL_TOKENS_LIMIT: int | None = Field(
    default=None,
    gt=0,
    description="Maximum total (input+output) tokens per agent run; None disables the cap.",
)
```

**Verify**: `cd apps/api && uv run ruff check core/settings/agents.py` → exit 0

### Step 2: Wire it into the runtime agent

In `apps/api/services/agents/runtime/loop.py`, change the `UsageLimits`
construction to:

```python
usage_limits=UsageLimits(
    request_limit=resolved_model.max_steps,
    total_tokens_limit=settings.AGENT_RUN_TOTAL_TOKENS_LIMIT,
),
```

Import `settings` from `core.settings` (check `loop.py`'s current imports; it
does not import settings today).

**Verify**: `cd apps/api && uv run pytest tests/services/agents/runtime -q` → all pass

### Step 3: Add tests

In `apps/api/tests/services/agents/runtime/test_runtime_core.py`:

1. **Limit trips and run fails cleanly**: model the test after
   `test_execute_run_commits_failed_status_before_reraising` (line ~607).
   Set `AGENT_RUN_TOTAL_TOKENS_LIMIT=1` via the settings override mechanism
   used by existing tests (inspect the file's fixtures/conftest for how
   settings are patched; follow that pattern — likely `monkeypatch.setattr`
   on the settings object). Run `execute_run` with a `TestModel` and assert:
   - the run's final status is failed with `error_code == "UsageLimitExceeded"`,
   - the sink received `error` then `done` events.
2. **Default is uncapped**: with the default `None`, assert
   `build_runtime_agent(...).usage_limits.total_tokens_limit is None` and a
   normal `TestModel` run completes (existing happy-path test may already
   cover the run; the assertion on `usage_limits` is the new bit).

**Verify**: `cd apps/api && uv run pytest tests/services/agents/runtime -q` → all pass, including new tests

### Step 4: Full check

**Verify**: `cd apps/api && uv run ruff check . && uv run pytest -q` → exit 0, all pass

## Test plan

See Step 3. Pattern file: `apps/api/tests/services/agents/runtime/test_runtime_core.py`
(uses `TestModel` + `CollectingSink`; keep provider-free).

## Done criteria

- [ ] `cd apps/api && uv run ruff check .` exits 0
- [ ] `cd apps/api && uv run pytest -q` exits 0; new limit tests exist and pass
- [ ] `grep -n "total_tokens_limit" apps/api/services/agents/runtime/loop.py` shows the wired setting
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back if:

- `UsageLimits` in the installed package rejects `total_tokens_limit` (version drift).
- A tripped limit does NOT surface as a failed run through the existing
  `persist_failed_run` path (e.g. the exception is swallowed inside the stream) —
  report what actually happens instead of adding new handling.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- When per-workspace policies land, this setting becomes the global default that
  workspace/agent-level budgets override — keep the `UsageLimits` construction in
  `build_runtime_agent` as the single merge point.
- A `UsageLimitExceeded` run is terminal today (no auto-resume); if product later
  wants "continue anyway" after a cap, that is a new approval-style flow, not a
  tweak here.
