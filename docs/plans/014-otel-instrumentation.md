# Plan 014: Add config-gated OpenTelemetry instrumentation for agent runs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat 1a51665..HEAD -- apps/api/services/agents/runtime/capabilities.py apps/api/core/settings apps/api/main.py apps/api/workers/agent_runner.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (off by default; risk is accidental content capture when enabled)
- **Depends on**: none
- **Category**: dx / observability
- **Planned at**: commit `1a51665`, 2026-07-01

## Why this matters

AGENTS.md requires sensitive flows to "leave enough context to debug later" and
the intent docs name instrumentation as the mechanism:
`docs/pydantic-ai/13-advanced-and-ecosystem.md` ("Audit/observability: this is
the requirement driver … defaulting to `include_content=False` for sensitive
flows"). Today there is zero tracing: no span shows which model request slowed
a run, what a tool call did, or why a provider errored. The needed packages
(`logfire` 4.37.0, full `opentelemetry-*` stack) already ship with the
`pydantic-ai` meta-package — this is wiring, not new dependencies.

## Current state

- No instrumentation exists anywhere:
  `grep -rn 'logfire\|instrument' apps/api --include='*.py'` (excluding
  `.venv`) returns nothing.

- Verified against installed `pydantic-ai==2.1.0`:
  - `from pydantic_ai.capabilities import Instrumentation` works.
  - `from pydantic_ai.models.instrumented import InstrumentationSettings` works.
  - `InstrumentationSettings(version=...)`: versions 2–4 are deprecated; use
    the default (`version=5`). `include_content=False` strips prompts,
    completions, and tool args from spans.
  - `Agent.instrument_all(...)` classmethod exists; the 1.x
    `Agent(instrument=...)` constructor kwarg was **removed** in 2.x.
  - Per-agent alternative: add `Instrumentation(...)` to `capabilities=[...]`.

- Capability assembly point: `apps/api/services/agents/runtime/capabilities.py`
  (`build_runtime_capabilities` returns `[hooks]` today). The conversation
  naming agent (`services/conversations/naming.py:58-63`) builds its own
  `Agent` without capabilities — a global `Agent.instrument_all()` covers both;
  per-agent capabilities would not.

- App startup: `apps/api/main.py` (FastAPI app with documented middleware
  ordering notes — instrumentation setup is NOT middleware; wire it in the
  lifespan/startup path). Worker startup: `apps/api/workers/agent_runner.py:47`
  calls `setup_logging()` at import time — the worker is a separate process and
  needs the same instrumentation setup.

- Settings conventions: mixins under `apps/api/core/settings/` with
  `Field(default=..., description=...)`; production-unsafe combinations are
  validated in settings (see `core/settings/models.py:91-125` for a
  `model_validator(mode="after")` example — moved from line 74 by the
  token-cap commit `05df2d0`).

- Telemetry-safety note from the maintained Pydantic AI skill: traces are
  diagnostic data; `include_content=True` puts prompts/tool args into spans.
  Praxis handles workspace data — content capture must be an explicit opt-in
  and discouraged for production.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Focused tests | `cd apps/api && uv run pytest tests/services tests/middleware -q` | all pass |
| Full API tests | `cd apps/api && uv run pytest -q` | all pass |

## Scope

**In scope**:
- `apps/api/core/settings/observability.py` (create — settings mixin)
- `apps/api/core/settings/__init__.py` (register the mixin — inspect how the
  other mixins compose into the Settings class and match it)
- `apps/api/core/observability.py` (create — setup function)
- `apps/api/main.py` (call setup during startup/lifespan)
- `apps/api/workers/agent_runner.py` (call setup at worker start)
- `apps/api/tests/` (new focused tests; place under `tests/services` or a
  location matching the existing test-intent layout)
- `docs/plans/000_README.md` (status row)
- `README.md` or the relevant env-var docs IF the repo documents env vars
  (check; AGENTS.md says update docs when env vars change)

**Out of scope**:
- `logfire.instrument_httpx(capture_all=True)` — captures raw provider
  payloads; do not add.
- Instrumenting SQLAlchemy/FastAPI generally — this plan covers agent-run
  tracing only.
- Any hosted-backend account setup (Logfire tokens etc.) — config keys only.
- The audit-record system (`middleware/audit_context.py`) — spans complement,
  not replace, audit rows.

## Git workflow

- Branch: `advisor/014-otel-instrumentation`
- Commit style: `API - Agent Run Instrumentation`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

Create `apps/api/core/settings/observability.py` with an
`ObservabilitySettingsMixin`:

```python
AGENT_TRACING_ENABLED: bool = Field(
    default=False,
    description="Emit OpenTelemetry spans for agent runs, model requests, and tool calls.",
)
AGENT_TRACING_INCLUDE_CONTENT: bool = Field(
    default=False,
    description="Include prompts, completions, and tool args in spans. Keep False outside local debugging.",
)
```

Add a `model_validator(mode="after")` (style: `core/settings/models.py:74`)
that raises when `ENVIRONMENT == "production"` and
`AGENT_TRACING_INCLUDE_CONTENT` is `True` unless an explicit
`AGENT_TRACING_ALLOW_CONTENT_IN_PRODUCTION: bool = False` is also set — this is
the "validate unsafe production combinations" convention from AGENTS.md.
Register the mixin in `core/settings/__init__.py` alongside the others.

**Verify**: `cd apps/api && uv run pytest tests -q -k settings` → passes (and add a test if none covers this — see Test plan)

### Step 2: Setup function

Create `apps/api/core/observability.py`:

```python
def setup_agent_tracing() -> None:
    """Instrument Pydantic AI agents when tracing is enabled; no-op otherwise."""
```

Behavior:
- Return immediately when `settings.AGENT_TRACING_ENABLED` is false.
- Otherwise: `logfire.configure(send_to_logfire="if-token-present")` followed by
  `logfire.instrument_pydantic_ai()` is the simplest correct wiring — logfire's
  SDK is OTel-native and respects standard `OTEL_EXPORTER_OTLP_ENDPOINT` env
  vars, so a plain OTLP collector works without a Logfire account. Pass
  content settings through: check the installed
  `logfire.instrument_pydantic_ai` signature for how it accepts
  `InstrumentationSettings` or an `include_content`-style option
  (`uv run python -c "import logfire, inspect; print(inspect.signature(logfire.instrument_pydantic_ai))"`);
  pre-checked against logfire 4.37.0: it DOES accept `include_content` and
  `version`, but its `version` is `Literal[1,2,3]` while
  `InstrumentationSettings(version=...)` is `Literal[2,3,4,5]` — the
  `Agent.instrument_all(InstrumentationSettings(include_content=settings.AGENT_TRACING_INCLUDE_CONTENT))`
  fallback after `logfire.configure(...)` is the safer path for content
  control; re-verify the installed signature either way.
- Idempotent: guard with a module-level flag so repeated calls (tests, reload)
  don't double-instrument.

**Verify**: `cd apps/api && uv run ruff check core/observability.py` → exit 0

### Step 3: Wire into API startup and the worker

- `apps/api/main.py`: call `setup_agent_tracing()` in the existing
  startup/lifespan hook (read the file first; place it before routes serve
  traffic, do not disturb the middleware-ordering comments).
- `apps/api/workers/agent_runner.py`: call `setup_agent_tracing()` right after
  `setup_logging()` (line 47).

**Verify**: `cd apps/api && uv run pytest -q` → all pass (app import path exercises main.py)

### Step 4: Tests

1. Settings validation test (place with existing settings tests — find them via
   `grep -rl "ENVIRONMENT" apps/api/tests | head`): production +
   `AGENT_TRACING_INCLUDE_CONTENT=True` without the override raises; with the
   override passes; non-production passes.
2. `setup_agent_tracing` no-ops when disabled (assert no logfire configure call
   via monkeypatch) and calls `logfire.configure`/instrumentation exactly once
   when enabled twice (idempotence).

**Verify**: `cd apps/api && uv run pytest -q` → all pass, including new tests

## Test plan

See Step 4 — validation of the unsafe production combination is the high-risk
behavior; idempotence protects test suites and dev reload.

## Done criteria

- [ ] `cd apps/api && uv run ruff check .` exits 0
- [ ] `cd apps/api && uv run pytest -q` exits 0; new tests pass
- [ ] `grep -rn "setup_agent_tracing" apps/api/main.py apps/api/workers/agent_runner.py` shows both call sites
- [ ] With default settings, importing the app emits no tracing (disabled path is the default)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back if:

- `logfire.configure(send_to_logfire="if-token-present")` is not a valid call
  in the installed logfire 4.37.0 — report the actual accepted values.
- Instrumentation measurably breaks the SSE stream tests (spans must not
  interfere with `run_stream_events`) — report the failing test.
- Wiring requires touching middleware ordering in `main.py`.

## Maintenance notes

- Agents already get explicit `name=` values (`loop.py:81-84` `_agent_name`
  slugs — moved from 53-56 by the delegation commit,
  `conversation_title_generator` in naming.py), so spans will be well-labeled —
  keep that convention for future agents.
- **Plan 026 coordination (README dependency note)**: tool-call spans should
  ultimately wrap 026's `dispatch.py` choke point — one span per invocation
  with the same attributes as the audit row, never a second interception
  layer. This plan instruments at the agent level only
  (`Agent.instrument_all`) and leaves the dispatch seam untouched; if this
  lands before 026, that agent-level layer IS the named hook point and 026
  rebases onto it, and if 026 lands first, wrap its `dispatch.py`.
- When evals (`pydantic_evals`, already installed) are adopted, they attach to
  this same Logfire/OTel wiring.
- Deferred: workspace-scoped trace attributes (adding `workspace_id`/`run_id`
  span attributes via the existing `Hooks` capability) — a natural follow-up
  once base spans exist.
