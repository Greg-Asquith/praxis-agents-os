# Praxis Agents OS — Backend API

FastAPI backend for the Praxis Agents OS platform.

## Dev setup

```bash
# Install all dependencies (including dev group)
uv sync

# Run locally
uv run python main.py
# or directly via uvicorn
uv run uvicorn main:app --reload --port 8080
```

## Notes

- The API binds to `0.0.0.0:8080` in Docker; locally it defaults to port `8000` when run via `python main.py`.
- Environment variables are loaded from `.env` (see `.env.example` for required keys).
- Auth and user-management routes are registered under `/api/v1`:
  - `/api/v1/auth/*` handles provider discovery, email login/register, OAuth URL generation/code exchange, sessions, profile updates, password changes, and TOTP setup/verification.
  - `/api/v1/users/*` handles super-admin user CRUD and admin password setting.
  - OAuth routes never redirect. The frontend owns provider redirects and calls the API only for server-to-server provider work.

## API module layout

- Every FastAPI route operation lives in its own route file. Package
  `__init__.py` files compose those route modules into routers.
- Every service operation lives in its own service file. Package `__init__.py`
  files re-export operation functions only.
- Service-specific helpers live in that service directory's `utils.py`.
  Reusable helpers live in the top-level `utils/` package.
- Route files should stay thin: validate HTTP boundary concerns, call one service
  operation, and return its response model.

## Test layout

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

## Database migrations

Alembic owns database schema changes for this service. Migrations are run
explicitly from `apps/api`; the API does not apply migrations at startup.

Required runtime environment variables, including `DATABASE_URL`, `SECRET_KEY`,
`ENCRYPTION_KEY`, and `INTERNAL_SCHEDULE_TRIGGER_SECRET`, must be present when
running Alembic because the model registry imports the normal application
settings.

Apply all migration heads:

```bash
uv run alembic upgrade heads
```

Create a public/core-schema migration:

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
