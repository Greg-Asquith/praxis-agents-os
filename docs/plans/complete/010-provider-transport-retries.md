# Plan 010: Retry transient provider HTTP failures at the transport layer

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat 1a51665..HEAD -- apps/api/services/agents/models apps/api/core/settings/models.py apps/api/tests/services/agents/models`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches every model request path; a wrong retry config can multiply provider load)
- **Depends on**: none
- **Category**: tech-debt / reliability
- **Planned at**: commit `1a51665`, 2026-07-01

## Why this matters

Every agent run currently makes provider HTTP requests with no retry policy. A
single transient 429/500/529 from Anthropic/OpenAI/Google/Azure fails the whole
run terminally: `execute_run` marks the `AgentRun` failed, and for scheduled
runs repeated flakiness can eventually disable a schedule. Pydantic AI ships a
tenacity-backed httpx transport (`pydantic_ai.retries`) that retries transient
failures and honors `Retry-After` — and `tenacity` is already installed as a
dependency of the `pydantic-ai` meta-package, so this needs no new dependency.
The repo's own reference doc (`docs/pydantic-ai/13-advanced-and-ecosystem.md`,
"How Praxis should use this") already prescribes exactly this:
"wrap provider HTTP clients in `AsyncTenacityTransport` with `wait_retry_after`
so transient 429/5xx are handled uniformly and `Retry-After` is honored, with
`reraise=True` feeding the existing exception layer."

## Current state

- `apps/api/services/agents/models/factory.py` — builds one Pydantic AI
  `Model` + provider per resolved spec. No `http_client` is passed anywhere:

  ```python
  # factory.py:37-49
  if spec.provider == PROVIDER_ANTHROPIC:
      provider = AnthropicProvider(api_key=provider_api_key(PROVIDER_ANTHROPIC))
      return AnthropicModel(spec.model, provider=provider, settings=model_settings)

  if spec.provider == PROVIDER_OPENAI:
      provider = OpenAIProvider(api_key=provider_api_key(PROVIDER_OPENAI))
      return OpenAIResponsesModel(spec.model, provider=provider, settings=model_settings)

  if spec.provider == PROVIDER_GOOGLE:
      return GoogleModel(spec.model, provider=_google_provider(), settings=model_settings)

  if spec.provider == PROVIDER_AZURE:
      return _build_azure_model(spec, model_settings)
  ```

  The Google branch has two paths (`factory.py:57-70`): Gemini Developer API
  (`GoogleProvider(api_key=...)`) and Vertex AI, which constructs a
  `google.genai.Client` directly — the Vertex path does NOT go through httpx
  the same way and is out of scope for this plan.

- `apps/api/services/agents/models/utils.py` — the service's helper module
  (`provider_api_key` credential seam). New service-specific helpers belong
  here per AGENTS.md ("Service-specific helpers belong in `utils.py` inside
  that service directory").

- `apps/api/core/settings/models.py` — `LLMSettingsMixin` holds LLM/provider
  settings, using `pydantic.Field` with defaults and descriptions (see the
  `DEFAULT_MODEL_PROVIDER` field at line 25 for the style to match).

- Verified against the installed `pydantic-ai==2.1.0` (do not re-derive):
  - `from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after` imports successfully.
  - `AnthropicProvider`, `OpenAIProvider`, `AzureProvider`, and `GoogleProvider`
    all accept an `http_client` keyword argument.
  - `tenacity` 9.1.4 is already in the environment.

- Reference implementation shape (from `docs/pydantic-ai/13-advanced-and-ecosystem.md:74-91`):

  ```python
  transport = AsyncTenacityTransport(
      config=RetryConfig(
          stop=stop_after_attempt(5),
          wait=wait_retry_after(fallback_strategy=wait_exponential(multiplier=1, max=60), max_wait=300),
          reraise=True,
      ),
      validate_response=lambda r: r.raise_for_status(),
  )
  client = AsyncClient(transport=transport)
  ```

- Error-handling convention: configuration failures raise
  `ModelConfigurationError` from `services/agents/models/domain.py`; runtime
  failures propagate and are persisted by `execute_run`'s failure path. Do not
  add new exception types.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `cd apps/api && uv sync` | exit 0 |
| Lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Focused tests | `cd apps/api && uv run pytest tests/services/agents/models -q` | all pass |
| Full API tests | `cd apps/api && uv run pytest -q` | all pass |

## Scope

**In scope** (the only files you should modify):
- `apps/api/services/agents/models/utils.py` (add the shared retrying client helper)
- `apps/api/services/agents/models/factory.py` (pass `http_client=` to providers)
- `apps/api/core/settings/models.py` (retry settings)
- `apps/api/tests/services/agents/models/test_model_factory.py` (extend)
- `apps/api/tests/services/agents/models/test_retry_transport.py` (create)
- `docs/plans/000_README.md` (status row)

**Out of scope** (do NOT touch, even though they look related):
- The Vertex AI path in `_google_provider()` (`google.genai.Client` has its own
  transport; leave it un-retried and note it in the code with a single terse comment).
- `services/agents/runtime/**` — run-level failure handling stays as is.
- Schedule-level retry semantics (`services/agent_schedules/**`) — the plans
  index records a deliberate decision not to retry failed runs at that layer.
- `FallbackModel` provider failover — explicitly deferred (see README rejected/deferred notes).

## Git workflow

- Branch: `advisor/010-provider-transport-retries`
- Commit style: match repo (`git log --oneline`): `API - Provider Transport Retries`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add retry settings

In `apps/api/core/settings/models.py`, add to `LLMSettingsMixin` (match the
existing `Field` style):

- `LLM_HTTP_RETRY_MAX_ATTEMPTS: int = Field(default=4, gt=0, description=...)`
- `LLM_HTTP_RETRY_MAX_WAIT_SECONDS: float = Field(default=60.0, gt=0, description=...)`
- `LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS: float = Field(default=120.0, gt=0, description=...)`

Setting `LLM_HTTP_RETRY_MAX_ATTEMPTS=1` must effectively disable retries
(tenacity `stop_after_attempt(1)` = one try, no retry) — mention that in the
field description.

**Verify**: `cd apps/api && uv run ruff check core/settings/models.py` → exit 0

### Step 2: Add the shared retrying HTTP client helper

In `apps/api/services/agents/models/utils.py`, add:

```python
from functools import lru_cache

import httpx
from tenacity import stop_after_attempt, wait_exponential

from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after


@lru_cache(maxsize=1)
def retrying_http_client() -> httpx.AsyncClient:
    """Shared async client that retries transient provider failures.

    Honors Retry-After on 429s and re-raises the final error so the runtime's
    existing failure persistence still sees the real exception.
    """
    transport = AsyncTenacityTransport(
        config=RetryConfig(
            stop=stop_after_attempt(settings.LLM_HTTP_RETRY_MAX_ATTEMPTS),
            wait=wait_retry_after(
                fallback_strategy=wait_exponential(
                    multiplier=1, max=settings.LLM_HTTP_RETRY_MAX_WAIT_SECONDS
                ),
                max_wait=settings.LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS,
            ),
            reraise=True,
        ),
        validate_response=lambda response: response.raise_for_status(),
    )
    return httpx.AsyncClient(transport=transport)
```

Notes:
- `settings` is already imported in this module.
- IMPORTANT retry-safety nuance: `raise_for_status()` makes ALL 4xx/5xx raise,
  and tenacity would retry them. Retrying a 401/403/404 wastes provider quota
  and delays failure. Restrict retryable statuses: instead of the bare
  `raise_for_status`, use a small module-level function that only raises for
  status codes in `{408, 409, 429, 500, 502, 503, 504, 529}` (raise
  `response.raise_for_status()` only when `response.status_code` is in that
  set). Non-listed error statuses pass through un-retried and fail naturally
  in the provider SDK.
- `lru_cache` keeps one client (one connection pool) per process. The API app
  and the scheduled `agent_runner` worker are separate processes, each with a
  single event loop, so a process-global client is safe here.

**Verify**: `cd apps/api && uv run ruff check services/agents/models/utils.py` → exit 0

### Step 3: Wire the client into the factory

In `apps/api/services/agents/models/factory.py`, pass
`http_client=retrying_http_client()` to `AnthropicProvider`, `OpenAIProvider`,
`AzureProvider`, and the non-Vertex `GoogleProvider(api_key=...)` construction.
Leave the Vertex branch (`Client(vertexai=True, ...)`) untouched.

**Verify**: `cd apps/api && uv run pytest tests/services/agents/models -q` → all existing tests pass

### Step 4: Add tests

Create `apps/api/tests/services/agents/models/test_retry_transport.py`
(model the file layout after the existing
`apps/api/tests/services/agents/models/test_model_factory.py`):

1. **Retries a 429 then succeeds**: build the transport/client via
   `retrying_http_client.__wrapped__()` (bypass the cache) with a mocked inner
   transport — use `httpx.MockTransport` handler that returns 429 with
   `Retry-After: 0` on the first call and 200 on the second; assert the final
   response is 200 and the handler was called twice.
   (If `AsyncTenacityTransport` does not accept a wrapped inner transport
   directly, use `monkeypatch` on `httpx.AsyncHTTPTransport.handle_async_request`
   — check `AsyncTenacityTransport.__init__` in the installed package first.)
2. **Does not retry a 401**: handler returns 401 always; assert exactly one call
   and the client returns/raises the 401 without retry.
3. **Exhaustion re-raises**: handler always 503; assert the final
   `httpx.HTTPStatusError` propagates after `LLM_HTTP_RETRY_MAX_ATTEMPTS` calls.
4. In `test_model_factory.py`, assert built providers use the shared client
   (e.g. the provider's client `is retrying_http_client()`), for at least
   Anthropic and OpenAI. Inspect how the provider exposes its client
   (`provider.client` / `_client`) in the installed package before asserting.

Keep tests provider-free (no network, no API keys beyond fake values already
used by existing factory tests).

**Verify**: `cd apps/api && uv run pytest tests/services/agents/models -q` → all pass, including the new tests

### Step 5: Full check

**Verify**: `cd apps/api && uv run ruff check . && uv run pytest -q` → exit 0, all pass

## Test plan

Covered in Step 4: retry-then-success on 429 (honoring Retry-After), no-retry
on non-transient 4xx, exhaustion re-raise, and factory wiring assertions.
Pattern file: `apps/api/tests/services/agents/models/test_model_factory.py`.

## Done criteria

- [ ] `cd apps/api && uv run ruff check .` exits 0
- [ ] `cd apps/api && uv run pytest -q` exits 0; new retry-transport tests exist and pass
- [ ] `grep -n "http_client=retrying_http_client()" apps/api/services/agents/models/factory.py` shows 4 matches (anthropic, openai, azure, google-non-vertex)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- `AsyncTenacityTransport` in the installed package has a different constructor
  than `(config=..., validate_response=...)` — report the actual signature.
- Any provider rejects `http_client=` at construction (should not happen —
  verified against 2.1.0 — but if a version bump landed, stop).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If a `FallbackModel` provider-failover layer is added later, it composes on
  top of this: transport retries handle transient blips; FallbackModel handles
  hard provider outages.
- Reviewers should scrutinize the retryable-status set and the attempt/wait
  defaults — total worst-case added latency is bounded by
  `LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS` and must stay well under
  `AGENT_RUN_MAX_DURATION_SECONDS` (1200s) and the run lease TTL heartbeat.
- Deferred: retrying the Vertex AI (`google.genai.Client`) path; per-provider
  retry overrides.
