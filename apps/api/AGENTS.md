# Backend Standards (apps/api)

Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic settings, pydantic-ai
2.x, managed with `uv`. Ruff configuration lives in `apps/api/ruff.toml`.
Repo-wide expectations are in the root `AGENTS.md`.

## Structure

- Keep request handling async all the way through.
- Use SQLAlchemy models and migrations for schema changes. Do not rely on app
  startup to mutate database schema.
- Keep settings in `core/settings`; it is composed from per-concern mixins,
  and the `model_validator` in `core/settings/__init__.py` must keep rejecting
  unsafe production combinations.
- Keep route modules thin. Put reusable domain logic in `services`.
- Each API route operation must live in its own route file. Route package
  `__init__.py` files may only compose routers from those operation modules.
- Each service operation must live in its own service file. Service package
  `__init__.py` files may only re-export operation functions.
- Service-specific helpers belong in `utils.py` inside that service directory.
  Helpers that are not service-specific belong in the top-level
  `apps/api/utils/` package.
- Keep error handling structured through the existing exception layer:
  `core/exceptions` maps typed exceptions to RFC 7807 problem+json. Raise
  those exception types instead of ad-hoc `HTTPException`.
- Maintain the middleware ordering notes in `apps/api/main.py` when adding or
  moving middleware. The comment there is authoritative.

## Agent Runtime And Providers

- The agent runtime lives in `services/agents/runtime/`: SSE streaming with a
  versioned event protocol, run persistence, approval state
  (`DeferredToolRequests`/`DeferredToolResults`), capabilities, cooperative
  cancellation, and agent-to-agent delegation under `runtime/delegation/`.
- Every agent tool flows through the tool registry and the single dispatch
  choke point (`runtime/dispatch.py`), which owns per-invocation audit,
  policy/approval enforcement, run envelopes, and bounded tool results. Do
  not execute tool logic around it.
- LLM providers live in `services/agents/models/`. The catalog in
  `registry.py` is the single source of truth for available models;
  `factory.py` builds pydantic-ai models per provider. Resolve credentials
  only through the `provider_api_key` seam — never rely on implicit env
  pickup. All providers share the retrying HTTP client
  (`retrying_http_client()`).
- Background work runs in the worker process (`python -m workers.main`),
  which supervises the scheduled-agent runner (croniter schedules, TTL leases
  with heartbeats, terminal failure states) and the generic jobs runner over
  the SKIP-LOCKED `jobs` table. Queue new background work as jobs rather than
  inventing ad-hoc task mechanisms.
- Storage goes through the `services/storage` provider abstraction.
  `local_fs` is the local default; cloud providers (`gcs`, `s3`, `azure_blob`)
  must stay behind the `StorageProvider` contract, with their SDKs as
  optional extras (`gcp`, `aws`, `azure`).
- The runtime HTTP dependency is `httpx2`; plain `httpx` is dev-only.

## Auth And Request Handling

- Auth accepts the `session` cookie first, then `Authorization: Bearer`;
  internal HS256 JWTs authenticate scheduled runs and are pinned to their
  workspace.
- The active workspace resolves from the `X-Workspace` header via membership
  lookup; RBAC uses the `require_role`/`require_owner`/`require_editor`/
  `require_read` dependencies.
- CSRF is enforced when a session cookie is present (Origin check plus
  HMAC-signed `X-CSRF-Token`); rate limiting is Postgres-backed and
  fail-closed for auth flows. Do not widen exempt lists casually.
- Preserve auditability for sensitive operations. Workspace, security,
  approval, credential, notification, and schedule flows should leave enough
  context to debug later.

## Tests

- Keep API tests organized by intent under `apps/api/tests`: `contract`,
  `routes`, `services`, `integration`, `integrations`, `middleware`, and
  `utils`, with shared helpers in `factories/` and `support/`. Do not add
  random root-level `test_*.py` files. Test key behavior and high-risk flows
  rather than creating one test file per route or service operation by
  default.
- Pytest is configured in `apps/api/pyproject.toml` with
  `asyncio_mode = "auto"`, so async test functions run without per-module
  markers.
- Database-backed tests run against a real Postgres and skip cleanly unless
  `TEST_DATABASE_URL` is set; `make api-test` provisions the local test
  database and sets that variable automatically. Use the fixtures in
  `conftest.py` and the helpers in `tests/factories/` and `tests/support/`
  instead of hand-rolling setup. Live LLM calls are blocked in tests.

## Commands

```bash
cd apps/api
uv sync
uv run ruff check .
uv run ruff format --check .
uv run alembic check
uv run alembic upgrade heads
uv run pytest
uv run uvicorn main:app --reload --port 8000
```

`make api-test` (from the repo root) is the reliable way to run the full
database-backed suite locally.

## Migrations

Alembic has separate `core` and `app` branch heads. Platform infrastructure
tables go on the `core` branch; the `app` branch is reserved for verticals.
Create migrations from `apps/api`:

```bash
uv run alembic revision --autogenerate \
  --head core@head \
  --version-path alembic/versions/core \
  -m "describe core schema change"

uv run alembic revision --autogenerate \
  --head app@head \
  --version-path alembic/versions/app \
  -m "describe app schema change"
```
