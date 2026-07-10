# Plan 043: Embeddings provider service

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G3 pre-flight (run before Step 1)**: Gate G3 is satisfied —
> `docs/architecture/governance.md` exists (written 2026-07-06 at `0cbbb39`,
> plan 029 DONE). Re-verify the two sections this plan implements before
> coding: §4 Quotas ("Embedding budget | 2 M tokens/month/workspace |
> counter added by 043", governance.md:106) and the "Consumed By" row for
> 043–046 (governance.md:155). If either changed since `0cbbb39`, the note
> wins — reconcile before coding, and flip the §4 embedding-budget cell to
> `[implemented: plan 043]` in the same PR that ships this plan.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/services/agents/models/ apps/api/core/settings/ apps/api/models/ apps/api/alembic/versions/core/ apps/api/pyproject.toml apps/api/tests/conftest.py apps/api/tests/support/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **Amendment (plan 074) pre-flight**: the "Amendment (plan 074,
> 2026-07-07)" block at the end of this file amends this plan; where it
> conflicts with the body above, the amendment wins.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM (new isolated service package + one small table; the
  only shared surfaces touched are settings composition and the credential
  seam, both read-only reuse)
- **Depends on**: none hard — parallel-safe with Phase 3 (030–036). Soft:
  `docs/architecture/governance.md` §4 (embedding budget; Gate G3
  pre-flight above). Plan 044 depends hard on this plan.
- **Category**: Phase 4b knowledge base (roadmap `000_MASTER_ROADMAP.md` §4
  Phase 4b row 043; donor `DONOR_PORT_ROADMAP.md` §4.4 "Embeddings" / §6
  row D1)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **The ABC signature is
   `embed_texts(texts: Sequence[str], *, model: str, dimensions: int) -> EmbeddingBatch`**,
   async, order-preserving, with `EmbeddingBatch` carrying
   `vectors: list[list[float]]`, `total_tokens: int`, and the
   `provider`/`model`/`dimensions` echo. One method, batch-first — callers
   never loop single texts; the provider owns request batching below its
   own API limits. `len(vectors) == len(texts)` is a contract invariant
   the base class asserts.
2. **OpenAI is the default provider; Ollama is the implemented local
   option.** Resolves the roadmap open decision (`000_MASTER_ROADMAP.md`
   §2 "embedding default"; donor §7.2 recommendation confirmed). Default
   model `text-embedding-3-small` — the OpenAI chat catalog in
   `services/agents/models/registry.py` uses plain OpenAI model ids
   (`gpt-5.4-mini` style, registry.py:39), and the same plain-id style
   applies here. The Ollama provider (default model `bge-m3`) is a thin
   `POST {base_url}/api/embed` client so the "local option for
   self-hosters" is real code, not documentation vapor — but it is only
   usable when `EMBEDDINGS_OLLAMA_BASE_URL` is explicitly set (no
   localhost default that could silently point production at nothing).
3. **Dimensions: 1024 by default, via Matryoshka truncation on OpenAI.**
   The donor design allows 512–1024 (`DONOR_PORT_ROADMAP.md:317`); we pin
   the default at 1024 (`text-embedding-3-small` native 1536, truncated
   server-side via the API `dimensions` parameter, which renormalizes).
   The settings field accepts 512–1024; models that do not support
   truncation (Ollama `bge-m3`, native 1024) declare
   `supports_dimensions=False` in the embedding-model registry and reject
   a mismatched `dimensions` argument instead of silently padding or
   client-truncating. **Model+dims are recorded per collection by the
   consumer** (044 stamps `embedding_provider`/`embedding_model`/
   `embedding_dims` on chunks); this plan provides the values, never mixes
   them, and documents that changing either requires a new collection +
   re-embed.
4. **Embeddings get their own tiny registry, not entries in the chat
   catalog.** `services/agents/models/registry.py` is explicitly the chat
   model catalog ("single source of truth for known models" for the agent
   runtime, registry.py:3); embedding models have different metadata
   (native dims, truncation support, batch limits) and no
   `context_window`/`supports_vision` semantics. A parallel
   `services/embeddings/registry.py` with the same frozen-dataclass +
   `_INDEX` shape keeps the pattern without polluting the agent catalog.
5. **Credentials flow through the existing `provider_api_key` seam and the
   shared retrying client — nothing new.** The OpenAI provider constructs
   `openai.AsyncOpenAI(api_key=provider_api_key(PROVIDER_OPENAI),
   http_client=retrying_http_client())` — the exact composition
   `factory.py:44-49` already uses for chat models, and the seam AGENTS.md
   mandates ("Resolve credentials only through the `provider_api_key`
   seam — never rely on implicit env pickup"). `provider_api_key` is
   already re-exported from `services.agents.models`
   (`services/agents/models/__init__.py:16`); this plan adds
   `retrying_http_client` to that re-export list (allowed: service
   `__init__` re-exports). The `openai` SDK is already installed
   (2.44.0, transitive via `pydantic-ai`) — no new dependency for the
   default provider. The Ollama provider reuses `retrying_http_client()`
   for its HTTP calls (no API key; base URL is its only credential-shaped
   input).
6. **Per-workspace embedding-token usage counter, counter-first, no hard
   enforcement** — implementing governance.md §4 verbatim ("all limits are
   soft in v1 — counters + admin visibility first"; "Embedding budget |
   2 M tokens/month/workspace | 043"). One table
   `embedding_token_usage` (workspace_id, month period, tokens_used) with
   an atomic `INSERT ... ON CONFLICT ... DO UPDATE` increment. The public
   `embed_texts` service op records provider-reported `total_tokens` after
   every successful call and logs a WARNING when a workspace's month total
   crosses `EMBEDDINGS_MONTHLY_TOKEN_BUDGET` (default 2,000,000). No
   route, no rejection — the admin-visible surface and hard enforcement
   are later slices (047 UI is the natural surface owner; the docstring
   must say so, mirroring plan 030's `count_in_flight_jobs` precedent).
7. **Tests never touch the network, enforced structurally.**
   `tests/conftest.py:24` sets
   `pydantic_ai_models.ALLOW_MODEL_REQUESTS = False`, which blocks
   pydantic-ai *chat* calls — it does NOT cover raw `openai` SDK
   embeddings calls. So this plan ships a deterministic
   `FakeEmbeddingProvider` in `tests/support/embeddings.py` and makes
   provider injection first-class: `embed_texts(..., provider=None)`
   accepts an explicit provider, and the provider factory is a
   monkeypatch-friendly module function. The fake embeds by a
   **bag-of-words token-hash projection** (per-token sha256 → seeded unit
   vector, summed and normalized) so that texts sharing vocabulary get
   graded cosine similarity — deterministic, offline, and good enough for
   plan 045's retrieval eval harness to make meaningful semantic
   assertions. This design is a cross-plan contract: 045 consumes this
   exact fake.
8. **Retry/failure posture**: transient HTTP failures are handled by the
   transport (`retrying_http_client()`, statuses 408/409/429/5xx/529 per
   `services/agents/models/utils.py:26`); anything that survives the
   transport retries surfaces as a typed `EmbeddingProviderError` from
   `services/embeddings/domain.py`. This service does NOT add its own
   retry loop — plan 044's embed jobs ride the jobs harness's bounded
   retries (030), and double-retrying would multiply latency. Misconfig
   (unknown provider/model, dims mismatch) raises
   `EmbeddingConfigurationError` — non-retryable by design, mirroring
   `ModelConfigurationError` (`services/agents/models/domain.py`).
9. **The usage-counter migration goes on the core branch (D5)** like every
   roadmap table. Head at planning time is `core_0008`
   (`alembic/versions/core/0008_add_conversation_todos.py:16`); Phase 3
   plans (030–033) will consume numbers before this executes — renumber
   against the real head at execution time, exactly as plan 030's STOP
   language prescribes.

## Why this matters

Every Phase 4b/5 retrieval feature is downstream of one question: "turn
these texts into vectors, reliably, attributably, and without vendor
lock-in." Plan 044 embeds KB chunks, 045 embeds search queries, 048 embeds
memories and dedups by cosine — all through this one seam. The donor
proved the shape (a trimmed provider ABC is called out as the thing to
port, `DONOR_PORT_ROADMAP.md:314-317`) and also proved the failure mode:
its knowledge-graph vectors were untyped columns filled by ad-hoc calls,
so no index was possible and no migration path existed. Recording
provider+model+dims per collection from day one, resolving credentials
through the audited seam, and metering tokens per workspace
(governance.md §4) are all cheap now and expensive to retrofit. This plan
is deliberately small and dependency-free so it can land in parallel with
Phase 3.

## Current state

All anchors verified at `0cbbb39`. Nothing embeddings-shaped exists yet:

- `apps/api/services/agents/models/utils.py` — the credential seam and
  shared transport this plan reuses: `provider_api_key(provider)`
  resolves `SecretStr` settings and raises `ModelConfigurationError` when
  missing (lines 68–83); `retrying_http_client()` is an `lru_cache`d
  `httpx.AsyncClient` over `AsyncTenacityTransport` with
  `Retry-After`-aware backoff (lines 41–65); retryable statuses frozenset
  at line 26. Provider constants `PROVIDER_OPENAI` etc. in
  `services/agents/models/domain.py:15-18`.
- `apps/api/services/agents/models/factory.py:44-49` — the composition
  precedent: `OpenAIProvider(api_key=provider_api_key(PROVIDER_OPENAI),
  http_client=retrying_http_client())`.
- `apps/api/services/agents/models/__init__.py:16` re-exports
  `provider_api_key`; `retrying_http_client` is not yet re-exported.
- `apps/api/core/settings/models.py` — `LLMSettingsMixin`: nullable
  `SecretStr` provider keys (lines 69–73) and a mixin-level
  `model_validator` requiring credentials for active providers in
  production (lines 97–131). This plan's settings mixin copies both
  patterns. Mixins compose in `core/settings/__init__.py:30-46`.
- Installed packages (probed 2026-07-06): `openai` 2.44.0 (transitive via
  `pydantic-ai>=2.1.0`); `pgvector` **not installed** and not in
  `pyproject.toml` (verified: no `pgvector` line in the dependencies
  list) — not needed by this plan (vectors here are plain
  `list[float]`); plan 044 adds it.
- `apps/api/models/base.py` — `UUIDMixin` (line 18), `TimestampMixin`
  (line 24), soft-delete `BaseModel` (line 130). The usage-counter table
  follows the `RateLimitAttempt` non-soft-delete composition
  (`models/rate_limiting.py:16`), same as plan 030's `Job`. New models
  must be imported in `models/__init__.py` (registry comment, lines 1–12).
- Migrations: `apps/api/alembic/versions/core/` head is `core_0008`
  (`0008_add_conversation_todos.py:16` has
  `down_revision = "core_0007"`). D5: core branch for all roadmap tables.
- Tests: `pydantic_ai_models.ALLOW_MODEL_REQUESTS = False` at
  `tests/conftest.py:24` (blocks chat models only — see decision 7);
  DB-backed tests gate on `TEST_DATABASE_URL` via
  `require_test_database_url` (`tests/support/database.py:13-23`, skips
  cleanly when unset); per-test rollback session fixtures
  `db_session`/`db_session_factory` (`tests/conftest.py:105-174`).
  `tests/support/` holds cross-cutting helpers (`settings.py`,
  `database.py`, `storage.py`) — `embeddings.py` joins them.
- Exceptions: typed service exceptions with `details` dicts are the
  precedent (`ModelConfigurationError` in
  `services/agents/models/domain.py`; `AppValidationError` at
  `core/exceptions/general.py:16`) — RFC 7807 mapping via
  `core/exceptions/exception_handlers.py`.
- Governance: `docs/architecture/governance.md:106` "Embedding budget |
  2 M tokens/month/workspace | 043"; §4 law "counters + admin visibility
  first, hard enforcement second".
- Will exist after sibling plans (do not assume now): `services/jobs/`
  enqueue/`@job_handler` (030), `kb_chunks` consumers (044), the query
  embedder (045), memory dedup-by-cosine (048).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations after Step 2 |
| Apply migration | `uv run alembic upgrade heads` | `embedding_token_usage` created |
| Settings smoke | `uv run python -c "from core.settings import settings; print(settings.EMBEDDINGS_PROVIDER, settings.EMBEDDINGS_MODEL, settings.EMBEDDINGS_DIMENSIONS)"` | `openai text-embedding-3-small 1024` |
| Registry smoke | `uv run python -c "from services.embeddings.registry import list_embedding_models; print([m.qualified_id for m in list_embedding_models()])"` | includes `openai:text-embedding-3-small`, `ollama:bge-m3` |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/embeddings -q` | all pass; DB tests skip without the env var |
| Full regression | `uv run pytest -q` | all pass |

## Scope

**In scope:**

- `apps/api/services/embeddings/` (create): `__init__.py`, `domain.py`,
  `registry.py`, `get_embedding_provider.py`, `embed_texts.py`,
  `record_embedding_usage.py`, `get_embedding_usage.py`, `utils.py`,
  `providers/__init__.py`, `providers/openai.py`, `providers/ollama.py`
- `apps/api/core/settings/embeddings.py` (create —
  `EmbeddingsSettingsMixin`) + `apps/api/core/settings/__init__.py`
  (compose it)
- `apps/api/models/embedding_usage.py` (create) +
  `apps/api/models/__init__.py` (register import)
- `apps/api/alembic/versions/core/00XX_*.py` (create — core branch, D5;
  renumber against the real head, decision 9)
- `apps/api/services/agents/models/__init__.py` (add
  `retrying_http_client` to re-exports — one line)
- `apps/api/tests/support/embeddings.py` (create — the deterministic
  fake), `apps/api/tests/services/embeddings/` (create)

**Out of scope (do NOT touch):**

- ANY vector columns, pgvector dependency, chunking, or KB tables — 044.
- ANY job kinds or `services/jobs/` wiring — the embed *jobs* are 044's;
  this plan is a plain async service that jobs will call.
- HTTP routes and UI. The usage counter has **no public surface** in this
  plan; per AGENTS.md, document it as pending (047's KB UI is the natural
  admin-visibility owner — say so in the counter op's docstring).
- Hard budget enforcement (governance §4: counters first).
- Reranking, query-time logic, RRF — 045.
- The chat model catalog (`services/agents/models/registry.py`) — no new
  entries there (decision 4).
- Secret-manager providers — `provider_api_key` stays settings-backed
  until the 037 secret-reference work; its docstring already names that
  seam swap (`services/agents/models/utils.py:5-8`).

## Git workflow

- Branch: `advisor/043-embeddings-provider-service`
- Commit style: `API - Embeddings Provider Service`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

Create `core/settings/embeddings.py` with `EmbeddingsSettingsMixin`
(shape of `LLMSettingsMixin`, `core/settings/models.py:23`):

```python
EMBEDDINGS_PROVIDER: Literal["openai", "ollama"] = Field(
    default="openai", description="Embedding provider for KB and memory vectors.")
EMBEDDINGS_MODEL: str = Field(
    default="text-embedding-3-small", description="Embedding model id from the embedding registry.")
EMBEDDINGS_DIMENSIONS: int = Field(
    default=1024, ge=512, le=1024,
    description="Vector dimensions; Matryoshka-truncated where supported. Recorded per collection.")
EMBEDDINGS_MAX_BATCH_TEXTS: int = Field(
    default=64, gt=0, description="Maximum texts per provider embedding request.")
EMBEDDINGS_MAX_TEXT_CHARS: int = Field(
    default=32_000, gt=0, description="Per-text character cap; longer inputs are a caller bug.")
EMBEDDINGS_OLLAMA_BASE_URL: str | None = Field(
    default=None, description="Ollama base URL (e.g. http://127.0.0.1:11434). Required when provider=ollama.")
EMBEDDINGS_MONTHLY_TOKEN_BUDGET: int = Field(
    default=2_000_000, gt=0,
    description="Soft per-workspace monthly embedding-token budget (governance §4). Observed, not enforced.")
```

Add a mixin-level `model_validator(mode="after")` (the
`validate_llm_provider_credentials` pattern, `models.py:97-131`):

- `EMBEDDINGS_PROVIDER == "ollama"` and `EMBEDDINGS_OLLAMA_BASE_URL`
  unset/blank → `ValueError` (any environment — a selected provider must
  be reachable by explicit configuration, decision 2).
- `ENVIRONMENT == "production"` and `EMBEDDINGS_PROVIDER == "openai"` and
  `OPENAI_API_KEY is None` → `ValueError` naming `OPENAI_API_KEY`.

Compose the mixin into `Settings` in `core/settings/__init__.py:30-46`
alphabetically among the others.

**Verify**: the settings smoke command above prints
`openai text-embedding-3-small 1024`;
`EMBEDDINGS_PROVIDER=ollama uv run python -c "from core.settings import Settings; Settings()"`
fails with the base-URL message; `uv run ruff check .` → exit 0.

### Step 2: Usage-counter model + core migration

Create `models/embedding_usage.py` with
`EmbeddingTokenUsage(Base, UUIDMixin, TimestampMixin)` (non-soft-delete,
the `RateLimitAttempt`/plan-030 `Job` composition),
`__tablename__ = "embedding_token_usage"`:

- `workspace_id` UUID FK `workspaces.id`, not null, `ondelete="CASCADE"`
- `period_month` Date not null — always the first day of the UTC month
- `tokens_used` BigInteger not null, server_default `0`, CHECK
  `tokens_used >= 0`
- `UniqueConstraint("workspace_id", "period_month",
  name="uq_embedding_token_usage_workspace_month")` — the upsert target

Import it in `models/__init__.py`. Generate on the core branch:
`uv run alembic revision --autogenerate --head core@head --version-path
alembic/versions/core -m "add embedding token usage table"` — renumber
the filename/revision id against the real head (decision 9; `core_0008`
at planning time, Phase 3 plans will have moved it). This table has no
expression indexes, so autogenerate should be complete — still hand-check
the unique constraint and CHECK made it in, with a matching `downgrade`.

**Verify**: `uv run alembic upgrade heads` applies cleanly;
`uv run alembic check` → no pending operations; downgrade round-trips
(`uv run alembic downgrade core@-1 && uv run alembic upgrade heads`).

### Step 3: Domain + embedding-model registry

`services/embeddings/domain.py`:

```python
@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    total_tokens: int
    provider: str
    model: str
    dimensions: int

class EmbeddingProvider(ABC):
    provider: ClassVar[str]

    @abstractmethod
    async def embed_texts(
        self, texts: Sequence[str], *, model: str, dimensions: int
    ) -> EmbeddingBatch: ...

class EmbeddingConfigurationError(Exception): ...  # + message/details, ModelConfigurationError shape
class EmbeddingProviderError(Exception): ...       # transient-exhausted or provider-side failure
```

Also `EMBEDDING_PROVIDER_OPENAI = "openai"` /
`EMBEDDING_PROVIDER_OLLAMA = "ollama"` constants (string values must
match `PROVIDER_OPENAI` where they overlap so the credential seam keys
line up — assert that in a test rather than importing the agents
constant into domain).

`services/embeddings/registry.py` (the `services/agents/models/registry.py`
`_CATALOG`/`_INDEX` shape, decision 4):

```python
@dataclass(frozen=True)
class EmbeddingModelInfo:
    provider: str
    model: str
    native_dimensions: int
    supports_dimensions: bool   # Matryoshka truncation via API param
    max_batch_texts: int

    @property
    def qualified_id(self) -> str: return f"{self.provider}:{self.model}"

_CATALOG = (
    EmbeddingModelInfo("openai", "text-embedding-3-small", 1536, True, 2048),
    EmbeddingModelInfo("openai", "text-embedding-3-large", 3072, True, 2048),
    EmbeddingModelInfo("ollama", "bge-m3", 1024, False, 64),
)
```

Plus `get_embedding_model(provider, model)` raising
`EmbeddingConfigurationError` for unknown pairs and
`list_embedding_models()`. Validation rule enforced here:
`supports_dimensions=False` models require `dimensions ==
native_dimensions` (decision 3) — checked in `embed_texts` (Step 5).

`services/embeddings/utils.py`: `chunk_batches(texts, size)` (pure
splitter preserving order), `current_period_month()` (first day of the
current UTC month), `assert_batch_shape(batch, expected_len)` (raises
`EmbeddingProviderError` on a length mismatch — the decision-1
invariant).

**Verify**: registry smoke command prints both qualified ids; ruff exit 0.

### Step 4: Providers

`services/embeddings/providers/openai.py` — `OpenAIEmbeddingsProvider`:

```python
class OpenAIEmbeddingsProvider(EmbeddingProvider):
    provider = EMBEDDING_PROVIDER_OPENAI

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=provider_api_key(PROVIDER_OPENAI),   # the seam — never env pickup
            http_client=retrying_http_client(),          # shared transient-retry transport
        )

    async def embed_texts(self, texts, *, model, dimensions) -> EmbeddingBatch:
        kwargs = {"model": model, "input": list(texts), "encoding_format": "float"}
        if get_embedding_model(self.provider, model).supports_dimensions:
            kwargs["dimensions"] = dimensions
        response = await self._client.embeddings.create(**kwargs)
        vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        return EmbeddingBatch(vectors, response.usage.total_tokens, self.provider, model, dimensions)
```

Wrap the API call: `openai.APIError`/`httpx.HTTPError` →
`EmbeddingProviderError` with provider/model in `details` (never the
input texts — they may be private document content).

`services/embeddings/providers/ollama.py` — `OllamaEmbeddingsProvider`:
`POST {EMBEDDINGS_OLLAMA_BASE_URL}/api/embed` with
`{"model": model, "input": [...]}` via `retrying_http_client()`; response
`embeddings` field → vectors. Ollama does not report token usage —
estimate `total_tokens = sum(len(t) // 4 for t in texts)` and mark the
estimate in a code comment (the counter stays meaningful for
self-hosters). Constructor raises `EmbeddingConfigurationError` if the
base URL is unset (belt to Step 1's braces).

`services/embeddings/get_embedding_provider.py` — the factory op:

```python
def get_embedding_provider() -> EmbeddingProvider:
    """Build the configured embedding provider. Module-level function so tests monkeypatch it."""
```

Match on `settings.EMBEDDINGS_PROVIDER`; unknown → 
`EmbeddingConfigurationError`. Do NOT `lru_cache` it — the OpenAI client
construction is cheap (the underlying http client is already cached) and
an uncached factory keeps monkeypatching trivial (decision 7).

Add `retrying_http_client` to `services/agents/models/__init__.py`
re-exports and import both seam functions from `services.agents.models`
(the package surface, not the private module).

**Verify**: `uv run python -c "from services.embeddings.get_embedding_provider import get_embedding_provider; print(type(get_embedding_provider()).__name__)"`
→ `OpenAIEmbeddingsProvider` when `OPENAI_API_KEY` is set locally;
without any key it raises `ModelConfigurationError` mentioning
`OPENAI_API_KEY` (the seam working). Ruff exit 0.

### Step 5: The public op — `embed_texts` with batching + metering

`services/embeddings/embed_texts.py` — the single entry point every
consumer (044 chunks, 045 queries, 048 memories) calls:

```python
async def embed_texts(
    db: AsyncSession,
    texts: Sequence[str],
    *,
    workspace_id: UUID,
    provider: EmbeddingProvider | None = None,
) -> EmbeddingBatch:
```

Behavior, in order:

1. Empty `texts` → `EmbeddingBatch([], 0, ...)` without a provider call.
2. Validate: any text empty/whitespace or over
   `EMBEDDINGS_MAX_TEXT_CHARS` → `EmbeddingConfigurationError` naming the
   offending index (callers chunk before embedding; a giant text here is
   a caller bug, not a truncation opportunity).
3. Resolve model info via the registry; enforce the decision-3 dims rule.
4. Split into batches of
   `min(settings.EMBEDDINGS_MAX_BATCH_TEXTS, info.max_batch_texts)`;
   call `provider.embed_texts` per batch sequentially (deterministic
   order, no concurrency — the jobs harness parallelizes at the job
   level); concatenate vectors, sum tokens,
   `assert_batch_shape` on the final result.
5. `await record_embedding_usage(db, workspace_id=workspace_id,
   tokens=total_tokens)` — metering is not optional and lives here, not
   in providers (a provider swap must never lose the counter).
6. Return the combined `EmbeddingBatch`.

`services/embeddings/record_embedding_usage.py`:

```python
async def record_embedding_usage(db, *, workspace_id: UUID, tokens: int) -> int:
    """Atomically add tokens to this workspace's month row; return the new month total."""
```

`INSERT INTO embedding_token_usage (workspace_id, period_month,
tokens_used) VALUES (...) ON CONFLICT (workspace_id, period_month) DO
UPDATE SET tokens_used = embedding_token_usage.tokens_used +
EXCLUDED.tokens_used RETURNING tokens_used` (via
`sqlalchemy.dialects.postgresql.insert`). When the returned total crosses
`EMBEDDINGS_MONTHLY_TOKEN_BUDGET`, log one WARNING with workspace id,
total, and budget (decision 6 — observe, don't enforce). `tokens <= 0`
is a no-op returning the current total.

`services/embeddings/get_embedding_usage.py`:
`get_embedding_usage(db, *, workspace_id, period_month=None) -> int` —
the read side, docstring naming 047 as the pending admin surface (plan
030 `count_jobs.py` precedent).

`services/embeddings/__init__.py` re-exports only the operation
functions (`embed_texts`, `get_embedding_provider`,
`record_embedding_usage`, `get_embedding_usage`) per the AGENTS.md
service-package rule.

**Verify**: `uv run ruff check .` → exit 0; `uv run pytest -q` (existing
suite) still green.

### Step 6: The deterministic fake

`tests/support/embeddings.py` — `FakeEmbeddingProvider(EmbeddingProvider)`
(decision 7, and a 045 contract):

- `provider = "fake"`; constructor takes `dimensions=1024`.
- Per text: lowercase, split on non-alphanumerics; for each token, seed
  `random.Random(sha256(token).digest())`, draw a `dimensions`-length
  Gaussian vector, normalize; sum token vectors; normalize the sum
  (empty text → a fixed unit basis vector).
- `total_tokens = sum(len(t) // 4 for t in texts)`.
- Properties that MUST hold (pin them in its own test): identical texts →
  identical vectors; texts sharing more tokens → higher cosine than
  disjoint texts; all vectors unit-norm; zero network.

**Verify**: covered by Step 7's `test_fake_provider.py`.

### Step 7: Tests

`tests/services/embeddings/` (async modules set
`pytestmark = pytest.mark.asyncio`; DB-backed tests use the `db_session`
fixture and skip cleanly without `TEST_DATABASE_URL`):

- `test_registry.py` (no DB): known/unknown model lookup; qualified ids;
  `supports_dimensions=False` + non-native dims rejected via
  `embed_texts` path; provider constants match the agents seam keys
  (`EMBEDDING_PROVIDER_OPENAI == PROVIDER_OPENAI`).
- `test_settings.py` (no DB): defaults (`openai`,
  `text-embedding-3-small`, 1024); dims bounds (511 and 1025 rejected);
  ollama-without-base-URL rejected; production-without-OPENAI_API_KEY
  rejected (construct `Settings` objects directly with env overrides,
  do not mutate the global).
- `test_fake_provider.py` (no DB): the decision-7 pinned properties,
  including a graded-similarity triple
  (`"vpn setup guide"` closer to `"how to set up the vpn"` than to
  `"quarterly revenue report"`).
- `test_embed_texts.py` (DB): batching splits at the configured size and
  preserves order across batches (use a recording fake that logs call
  sizes); empty input short-circuits; oversized text raises with the
  index; usage row written with provider-reported tokens; over-budget
  WARNING emitted exactly once per crossing call (caplog);
  length-mismatch from a misbehaving fake → `EmbeddingProviderError`.
- `test_usage_counter.py` (DB): upsert increments across calls; separate
  workspaces and months isolated; concurrent increments via
  `committed_db_session_factory` both land (no lost update);
  `tokens<=0` no-op.
- `test_openai_provider.py` (no DB, no network): construct with a mocked
  transport (`httpx.MockTransport` injected by building the provider
  around a stubbed `AsyncOpenAI`) — asserts the `dimensions` kwarg is
  sent for Matryoshka models, response order restored by `index`, API
  error mapped to `EmbeddingProviderError` without echoing input text.
  Never construct a real-network provider in tests — pin that as a
  review invariant.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/embeddings -q` → all
pass; without the env var the DB modules skip, not fail;
`uv run pytest -q` → full suite green.

## Test plan

Covered by Step 7 (~16–20 tests). The pinned invariants: **no test ever
makes a network call** (fake/mock providers only — `ALLOW_MODEL_REQUESTS`
does not cover the openai SDK, decision 7), **every successful embed call
meters tokens against the right workspace-month** (counter-first
governance §4), **order and length are preserved end to end** (decision 1
contract), and **credentials only flow through `provider_api_key`** (grep
the new package for `os.environ`/`getenv` — must be zero hits).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no pending operations; migration is
      on the **core** branch (D5) and downgrade round-trips
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/embeddings -q`
      exits 0; suite-wide `uv run pytest -q` green
- [ ] Settings smoke prints `openai text-embedding-3-small 1024`;
      ollama-without-URL and production-without-key are rejected
- [ ] `grep -rn "os.environ\|getenv" services/embeddings/` → no hits;
      `grep -rn "provider_api_key" services/embeddings/` → the OpenAI
      provider only
- [ ] `get_embedding_usage` docstring names 047 as the pending admin
      surface; no routes package exists
- [ ] `docs/architecture/governance.md` §4 embedding-budget cell flipped
      to `[implemented: plan 043]` in the same change
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated (add the 043 row if
      absent)

## STOP conditions

Stop and report back (do not improvise) if:

- `services/embeddings/`, `models/embedding_usage.py`, an
  `embedding_token_usage` table, or `tests/support/embeddings.py` already
  exists (someone started the seam first).
- `provider_api_key` or `retrying_http_client` no longer match the
  "Current state" signatures (`services/agents/models/utils.py:41-83`) —
  the reuse contract this plan is built on has moved; reconcile before
  coding rather than duplicating the seam.
- The installed `openai` package no longer exposes
  `AsyncOpenAI(...).embeddings.create(..., dimensions=...)` (verify:
  `uv run python -c "import openai; print(openai.__version__)"` — 2.44.0
  at planning time).
- `governance.md` §4 has changed the embedding budget row or its
  counter-first law — the note wins; reconcile the defaults here first.
- The core migration head at execution time contains a migration touching
  an `embedding_token_usage` or similarly-named table.
- You feel the need to add HTTP routes, hard budget enforcement, vector
  columns, a job kind, or a chat-catalog entry — scope leaking in
  (047 / 044 / later plans).

## Maintenance notes

- **Consumers**: 044 (chunk embedding jobs — the only caller allowed to
  loop `embed_texts` in bulk; its job payloads carry chunk ids, never
  text), 045 (query embedding — one small call per search; embeds count
  against the same workspace counter, deliberately), 048 (memory
  embedding + dedup-by-cosine — reuses the provider and the fake). All
  three must inject `FakeEmbeddingProvider` in tests.
- **Collection discipline**: `provider`/`model`/`dimensions` from
  `EmbeddingBatch` must be stamped onto every stored vector's row (044
  does this for `kb_chunks`; 048 for memories). Changing
  `EMBEDDINGS_MODEL` or `EMBEDDINGS_DIMENSIONS` does NOT migrate existing
  collections — it changes what *new* vectors look like, and mixed rows
  must be re-embedded before search trusts them. A reviewer who sees a
  search query comparing vectors without filtering on model+dims should
  block the PR (045 builds that filter in).
- **Enforcement second**: when the embedding budget graduates from
  counter to hard limit, the seam is Step 5's `embed_texts` (check the
  returned month total before the provider call and raise a typed quota
  error); do not bolt checks into providers. Update governance.md §4 in
  the same PR.
- **Secret-manager migration** (037): swapping `provider_api_key`'s body
  to secret references upgrades this service for free — that is the point
  of the seam. Do not add a second credential path here in the meantime.
- Reviewers should scrutinize: the ON CONFLICT increment (no lost updates
  under concurrency), that metering happens in `embed_texts` and not in
  providers, that error details never contain input text, and that no
  test constructs a networked provider.

## Amendment (plan 074, 2026-07-07): 3-large registry posture

Where this block conflicts with the body above, this block wins.

**New decision 10.** `text-embedding-3-large` stays in the catalog, and
its entry gains a comment stating the posture: with
`EMBEDDINGS_DIMENSIONS` capped at `le=1024` and 044's collection fixed at
`HALFVEC(1024)`, its native 3072 dims are unreachable by design — it is
only ever used Matryoshka-truncated via the API `dimensions` param
(`supports_dimensions=True`; Step 4 already sends it), which is safe and
deliberate: 3-large truncated to 1024 outperforms 3-small at 1024, so
the entry is a quality knob needing no schema change. Kept rather than
dropped for exactly that reason. **Step 7 delta** (`test_registry.py`):
every catalog entry must be usable under the settings bounds —
`supports_dimensions is True` or `512 <= native_dimensions <= 1024` — so
a future non-Matryoshka large model cannot be registered unstorable.
