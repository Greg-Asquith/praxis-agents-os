# Local development and verification

Use this reference for local setup, backend checks, and live evaluations.
The root [README](../../README.md) documents the complete Make target list.

## Local services

Docker Compose expects local env files under `.local/`; they are intentionally
not committed. The Compose `init` service creates them for Docker-only use;
`make bootstrap` invokes the same initialiser and installs dependencies;
the initialiser enables anonymous artifact sharing for local development while
the application default remains disabled for other environments;
`make dev` starts Postgres, migrates, and runs the API, worker, and web dev
servers. In that workflow only Postgres runs in Docker; the API, worker, and
web processes run locally, and `make dev-kill` stops all three. PostgreSQL 18
uses the major-aware `/var/lib/postgresql` mount and a dedicated
`praxis-postgres-18-data` volume. `make compose-dev` runs the complete
development stack in Docker using `docker-compose.dev.yml`, while
`make quickstart` runs the default production-image stack and prompts for an
LLM provider key if none is configured.
Make detects both `docker compose` and legacy `docker-compose`. When changing Docker
behaviour: keep local services bound to
`127.0.0.1`, keep production images small and non-root, and do not bake
runtime secrets into images.

## Backend tests

The following contracts apply in this area:

- Keep API tests organised by intent under `apps/api/tests`: `contract`,
  `routes`, `services`, `integration`, `integrations`, `middleware`,
  `scenarios`, and `utils`, with shared helpers in `factories/` and `support/`.
  Runtime behaviour changes should add or update a deterministic
  `tests/scenarios/` case through the shared scenario helper. Do not add
  random root-level `test_*.py` files. Test key behaviour and high-risk flows
  rather than creating one test file per route or service operation by
  default.
- Pytest is configured in `apps/api/pyproject.toml` with
  `asyncio_mode = "auto"`, so async test functions run without per-module
  markers.
- Database-backed tests run against a real Postgres and skip cleanly unless
  `TEST_DATABASE_URL` is set; `make api-test` provisions the local test
  database and sets that variable automatically. Use the fixtures in
  `conftest.py` and the helpers in `tests/factories/` and `tests/support/`
  instead of hand-rolling setup. The session fixture serialises pytest
  processes that target the same mutable test database; do not bypass that
  fixture for database-backed tests. Live LLM calls are blocked in tests.
- The shared database fixture runs ordinary test sessions under `praxis_app`.
  Multi-workspace fixtures must switch tenant context explicitly; use a
  maintenance session only when the behaviour under test is intentionally
  cross-workspace or system-owned.
- Live-model behaviour evaluations live outside pytest under `apps/api/evals`
  and run only through the explicit `make evals` target with `EVALS_MODEL`
  and matching provider credentials. The same command first runs live memory
  dedup calibration through the configured embedding provider, so its
  credential must also be available. These evals must never enter `make check`.

## Backend commands

From `apps/api/`, use these commands:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run uvicorn main:app --reload --port 8000 --no-access-log
```

After `make bootstrap`, start the local database, apply migrations, and check
for schema drift from the repository root:

```bash
make db-up
make db-wait
make migrate
make api-migrations-check
```

The migration targets export `apps/api/.env` before invoking Alembic.
Alembic reads its database URL from the shell environment; it does not load
the application's `.env` file itself. For direct migration commands, see
[Create a migration](database.md#create-a-migration).

From the repository root, `make api-test` provisions Postgres and sets
`TEST_DATABASE_URL`. Direct `uv run pytest` from `apps/api/` requires that
variable for database-backed coverage.

To run opt-in live evaluations from the repository root, supply model and
embedding credentials and select the model:

```bash
EVALS_MODEL=openai:gpt-5.6-luna make evals
```
