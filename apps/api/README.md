# Praxis Agents OS API

This service is the backend and worker runtime for Praxis Agents OS. It owns
identity, workspaces, agent runs, tool dispatch, integrations, durable jobs,
and the platform's audit trail. For the quickest way to run the whole product,
start with the [repository README](../../README.md#quickstart-docker-only).

## Development Setup

```bash
# Install all dependencies (including dev group)
uv sync

# Run locally
uv run python main.py
# or directly via uvicorn
uv run uvicorn main:app --reload --port 8000 --no-access-log

# Run the background worker (agent schedules and the generic jobs queue)
uv run python -m workers.main
```

## Runtime Notes

- The API binds to `0.0.0.0:8080` in Docker; locally it defaults to port `8000` when run via `python main.py`.
- Environment variables are loaded from `.env` (see `.env.example` for required keys).
- Auth and user-management routes are registered under `/api/v1`:
  - `/api/v1/auth/*` handles provider discovery, email login/register, OAuth URL generation/code exchange, sessions, profile updates, password changes, and TOTP setup/verification.
  - `/api/v1/users/*` handles super-admin user CRUD and admin password setting.
  - OAuth routes never redirect. The frontend owns provider redirects and calls the API only for server-to-server provider work.

## API Module Layout

- Every FastAPI route operation lives in its own route file. Package
  `__init__.py` files compose those route modules into routers.
- Every service operation lives in its own service file. Package `__init__.py`
  files re-export operation functions only.
- Service-specific helpers live in that service directory's `utils.py`.
  Reusable helpers live in the top-level `utils/` package.
- Route files should stay thin: validate HTTP boundary concerns, call one service
  operation, and return its response model.

## Test Layout

Tests live under `tests/` and are grouped by what they prove:

- `contract/` for cheap API-shape tests such as registered paths, HTTP methods,
  and OpenAPI boundary rules.
- `routes/` for thin route tests covering request parsing, dependency wiring,
  status codes, response models, and cookie behavior.
- `services/` for service operation behavior, including auth decisions, user
  mutations, provider work, audit logging, and security logging.
- `integration/` for key end-to-end API/database journeys only.
- `middleware/` for CSRF, rate limit, security header, request ID, and request
  transaction behavior.
- `factories/` and `support/` for shared test data builders and pytest helpers.

Do not create one test file for every route or service operation by default.
Prioritize high-risk, security-sensitive, externally observable, and regression-
prone behavior. Database-backed tests should use PostgreSQL via
`TEST_DATABASE_URL`; do not use SQLite as a behavioral substitute for this API.

Run the suite:

```bash
uv run pytest
```

## Database Migrations

Alembic owns database schema changes for this service. Migrations are run
explicitly from `apps/api`; the API does not apply migrations at startup.

Required runtime environment variables, including `DATABASE_URL`, `SECRET_KEY`,
and an application encryption source (`ENCRYPTION_KEYS` or
`ENCRYPTION_KEYS_SECRET_NAME`), must be present when running Alembic because
the model registry imports the normal application settings.

Apply all migration heads:

```bash
uv run alembic upgrade heads
```

Create a core-schema migration:

```bash
uv run alembic revision --autogenerate \
  --head core@head \
  --version-path alembic/versions/core \
  -m "describe core schema change"
```

Create an app-schema migration:

```bash
uv run alembic revision --autogenerate \
  --head app@head \
  --version-path alembic/versions/app \
  -m "describe app schema change"
```

Check that the current models match the migration state:

```bash
uv run alembic check
```

## Application Encryption Rotation

`ENCRYPTION_KEYS` is a newest-first comma-separated list or JSON array of
Fernet keys. Non-local environments can set `ENCRYPTION_KEYS_SECRET_NAME`; the
API and worker resolve that secret through the configured `SECRET_PROVIDER` at
startup.

Rotate without data loss:

1. Prepend the new Fernet key to the ring and restart or redeploy the API and
   worker.
2. Run `uv run python -m bin.application_encryption converge` from `apps/api`
   with the deployment's normal worker configuration.
3. Run `uv run python -m bin.application_encryption check`; require both
   `stale` and `undecryptable` in the JSON result to be zero.
4. Remove the old key and restart or redeploy again.
5. Run the check command again and require zero `stale` and `undecryptable`.

The convergence report's `stale` count records values encountered before they
were rewritten; only the separate check pass is removal proof. The scan covers
TOTP secrets, backup codes, and legacy user OAuth access and refresh tokens.
OAuth browser-binding cookies are intentionally not rewritten because they are
short-lived; the ring keeps old cookies readable during the rotation window.
Every converge and check pass also writes its counts and job ID to the retained
global audit log without recording key material.

This is separate from `SECRET_KEY` rotation, which invalidates signed transient
tokens, and credential-vault root rotation, which uses
`integrations.rotate_credential_encryption` and its `encryption_key_id` proof.
