# Praxis Agents OS

Open source foundations for the system behind
[Praxis Agents](https://www.praxis-agents.ai/).

Praxis Agents OS is being rebuilt from a larger internal project into a cleaner,
smaller codebase for creating, operating, and governing AI agents. The focus is
on practical agent workflows: workspaces, identity, approvals, auditability,
notifications, schedules, conversations, skills, and integrations that can be
maintained by a small team.

## Status

This repository is in an early porting stage.

- The backend foundation is present, including settings, database models,
  migrations, middleware, auth/session utilities, audit/security services,
  workspace services, routes, notifications, and schedule domain logic.
- The web app is a Vite SPA with the initial Praxis auth, shell, and workspace
  management foundation.
- Docker Compose is present for local integration work, but the Docker setup is
  still being normalized as the workspace moves to the final package managers and
  app layout.

Expect sharp edges while the old system is being reduced and rebuilt.

## Repository Layout

```text
.
+-- apps/
|   +-- api/      # FastAPI backend, SQLAlchemy models, Alembic migrations
|   +-- web/      # Vite frontend
+-- docker-compose.yml
+-- AGENTS.md     # Contributor and coding-agent guidance
+-- README.md
```

## Technology

Backend:

- Python 3.12
- FastAPI
- SQLAlchemy 2 with async Postgres access
- Alembic migrations
- Pydantic settings
- `uv` for dependency management

Frontend:

- React 19
- Vite
- TypeScript
- Tailwind CSS 4
- TanStack Router and TanStack Query
- shadcn/base-nova components
- `pnpm` for dependency management

Local infrastructure:

- Postgres 17 with pgvector available; pgvector is enabled by Alembic
- Docker Compose for local service orchestration

## Prerequisites

Install these before running the apps locally:

- Python 3.12
- `uv`
- Node.js 22
- `pnpm`
- Docker Desktop or another Docker Compose compatible runtime

## Local Make Targets

The root `GNUmakefile` wraps the common local development flow and includes
sectioned targets from `makefile/`.

Create missing local env files and install dependencies:

```bash
make bootstrap
```

Start the local database, apply migrations, and run the API and web app together:

```bash
make dev
```

Useful focused targets:

```bash
make db-up
make migrate
make api-dev
make web-dev
make compose-up
make check
```

`make dev` runs the API at `http://localhost:8000` and the web app at
`http://localhost:3000`.

## Backend Development

Start a Postgres database first. The default `apps/api/.env.example` expects
Postgres at `localhost:5432`; the bundled Compose database service starts a
local Postgres instance with pgvector available:

```bash
docker compose up -d postgres
```

From `apps/api`:

```bash
cp .env.example .env
uv sync
uv run alembic upgrade heads
uv run uvicorn main:app --reload --port 8000
```

The API reads configuration from environment variables or `.env`. Local defaults are documented in `apps/api/.env.example`.

The database server must expose the `vector` extension. Alembic enables it with `CREATE EXTENSION IF NOT EXISTS "vector"` during core migrations; if the provider does not make pgvector available, migration fails instead of silently degrading.

Important notes:

- The local API runs at `http://localhost:8000` with the command above.
- The app currently disables OpenAPI, Swagger, and ReDoc routes.
- The app verifies database connectivity at startup.
- Migrations are explicit. The API does not apply migrations automatically.

Backend checks:

```bash
cd apps/api
uv run ruff check .
uv run alembic check
```

No API test suite is committed yet. When you add behavior, add focused tests and
run them with `uv run pytest`.

## Database Migrations

Alembic has separate migration heads for core tables and app tables.

From `apps/api`, apply all migrations:

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

## Frontend Development

From `apps/web`:

```bash
pnpm install
pnpm dev
```

The development server runs at `http://localhost:3000`.

Frontend checks:

```bash
cd apps/web
pnpm lint
pnpm build
```

## Docker Compose

The root `docker-compose.yml` defines local Postgres, API, and web services.
Compose expects local env files under `.local/`; those files are not committed.

Create the local folders and env files:

```bash
mkdir -p .local/generated .local/targets .local/storage
cp apps/api/.env.example .local/generated/local.api.env
touch .local/targets/local.secrets.env
```

Create `.local/generated/local.web.env` with local frontend configuration:

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Intended local service URLs:

- Web: `http://localhost:3000`
- API: `http://localhost:8000`
- Postgres: `postgresql://postgres:postgres@localhost:5432/postgres`

Because the Docker setup is still being normalized, prefer the manual backend and
frontend commands above when you need a dependable local development loop.

## Project Direction

The active work is to turn the extracted foundations into a coherent open source
agent operating system:

- Extend the Vite control-plane UI beyond auth and workspace management.
- Add explicit API routes for new domain services as they become product surfaces.
- Keep auth, workspace boundaries, approval flows, audit events, and scheduling
  easy to inspect and test.
- Remove custom or unused legacy features instead of carrying them forward.
- Add focused tests and CI as each surface becomes real.

## Contributing

Read `AGENTS.md` before making changes. It captures the repository expectations
for coding agents and contributors.

In short:

- Keep changes small and deliberate.
- Prefer clear domain logic over generic framework code.
- Do not commit secrets or local generated files.
- Update docs when setup, commands, schema, or architecture change.
- Run the relevant checks before opening a PR.

## License

No license file has been committed yet. Add one before treating this repository as
ready for public redistribution.
