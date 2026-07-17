# Praxis Agents OS

Open source foundations for the system behind
[Praxis Agents](https://www.praxis-agents.ai/).

Praxis Agents OS is a platform for creating, operating, and governing AI
agents: workspaces and identity, agent conversations with tool calls and
approvals, schedules, files, skills, integrations, and audit trails — built as
a small, clean codebase that a small team can run and maintain.

## Status

The core platform is wired end to end (API, worker, and UI):

- Auth and identity: password, OAuth, and TOTP sign-in, sessions, users, and
  workspaces with memberships and invitations.
- Agents and conversations: configurable agents, SSE chat with live tool
  calls, approval workflows with resume, delegation between agents, and run
  cancellation.
- Tooling: a typed tool registry with a single audited dispatch choke point,
  a tool catalog surface, and per-agent tool policies.
- Files and skills: signed two-phase uploads, immutable revisions, background
  markdown extraction, agent file tools, and skill management with document
  pipelines.
- Operations: agent schedules with a leased background worker, a generic jobs
  worker, audit and security event viewers, an LLM model catalog, and
  integration connections (OAuth with PKCE, API keys, encrypted credentials).

Notifications exist as a backend service without routes or UI yet, and
pgvector is provisioned but unused until the knowledge-base work lands. See
`docs/plans/000_MASTER_ROADMAP.md` for the authoritative ordering of what
comes next.

## Repository Layout

```text
.
+-- apps/
|   +-- api/      # FastAPI backend, worker, SQLAlchemy models, migrations
|   +-- web/      # Vite + React frontend
+-- docs/plans/   # Numbered implementation plans and the master roadmap
+-- docker-compose.yml
+-- AGENTS.md     # Contributor and coding-agent guidance (per-app files in apps/)
+-- REVIEW.md     # Code-review focus areas
+-- README.md
```

## Technology

Backend:

- Python 3.12
- FastAPI
- SQLAlchemy 2 with async Postgres access
- Alembic migrations
- Pydantic settings
- pydantic-ai for the agent runtime
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
- Node.js 24
- `pnpm`
- Docker Desktop or another Docker Compose compatible runtime

## Local Make Targets

The root `Makefile` wraps the common local development flow and includes
sectioned targets from `makefiles/`.

Create missing local env files and install dependencies:

```bash
make bootstrap
```

Start the local database, apply migrations, and run the API, worker, and web
app together:

```bash
make dev
```

Useful focused targets:

```bash
make db-up
make migrate
make api-dev
make worker-dev
make web-dev
make api-test
make check
make compose-up
make dev-kill
```

`make dev` runs the API at `http://localhost:8000` and the web app at
`http://localhost:3000`. `make check` runs the full quality gate for both
apps: backend lint and format checks, the migration-drift check, the
database-backed API test suite (provisioning the local test database
automatically), and the complete frontend check.

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

The API reads configuration from environment variables or `.env`. Local
defaults are documented in `apps/api/.env.example`.

Background work (agent schedules and the generic jobs queue) runs in a
separate worker process:

```bash
uv run python -m workers.main
```

Cloud SDKs are optional extras bundled once per cloud provider. Local
development defaults to local providers and installs no cloud SDKs. For an
AWS-backed deployment, for example, the single `aws` extra supplies both
storage and secrets dependencies:

```bash
uv sync --extra aws
docker build --build-arg CLOUD_EXTRA=aws apps/api
```

Supported cloud extras are `gcp`, `aws`, and `azure`.

The database server must expose the `vector` extension. Alembic enables it
with `CREATE EXTENSION IF NOT EXISTS "vector"` during core migrations; if the
provider does not make pgvector available, migration fails instead of silently
degrading.

Important notes:

- The local API runs at `http://localhost:8000` with the command above.
- The app currently disables OpenAPI, Swagger, and ReDoc routes.
- The app verifies database connectivity at startup.
- Migrations are explicit. The API does not apply migrations automatically.

Backend checks:

```bash
cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run alembic check
uv run pytest
```

The API test suite lives under `apps/api/tests`, organized by intent.
Database-backed tests skip cleanly unless `TEST_DATABASE_URL` is set — run
`make api-test` from the repo root to provision the local test database and
run the full suite. When you add behavior, add focused tests alongside it.

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
pnpm check
```

`pnpm check` runs the full gate: typecheck, eslint (zero warnings), the
Vitest unit tests, prettier, knip dead-code detection, dependency-cruiser
architecture rules, and the production build.

## Docker Compose

The root `docker-compose.yml` defines local Postgres, API, worker, and web
services. Compose expects local env files under `.local/`; those files are not
committed and `make bootstrap` creates them.

To create them manually instead:

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

Use `make bootstrap` and `make dev` for the default local development loop.
The manual backend and frontend commands above are useful when you need to
run one app in isolation.

## Project Direction

The platform core is in place; active work is expanding what agents can reach
and remember, and hardening how they behave:

- Integrations: resource discovery, per-workspace active context, and the
  first providers (Gmail, Google Ads, Airtable) with approval-gated writes.
- Knowledge base: embeddings, hybrid search, and agent retrieval tools with
  untrusted-content framing.
- Agent memory: provenance-tracked memories with human-legible editing.
- Artifacts: versioned, sandboxed agent-produced documents and pages.
- Harness hardening: behavior scenario evals, context compaction, parallel
  delegation, and durable run event replay.
- Public launch readiness: community health files, supply-chain automation,
  and a first tagged release.

`docs/plans/000_MASTER_ROADMAP.md` is the authoritative ordering document for
this work.

## Contributing

Read `AGENTS.md` before making changes (plus `apps/api/AGENTS.md` or
`apps/web/AGENTS.md` for the app you are touching). `REVIEW.md` lists what
code review focuses on.

In short:

- Keep changes small and deliberate.
- Prefer clear domain logic over generic framework code.
- Do not commit secrets or local generated files.
- Update docs when setup, commands, schema, or architecture change.
- Run the relevant checks (`make check`) before opening a PR.

## License

Apache License 2.0. See `LICENSE`.
