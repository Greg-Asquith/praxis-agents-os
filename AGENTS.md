# AGENTS.md

Guidance for coding agents working in this repository.

## Project Intent

Praxis Agents OS is the open source codebase behind
[Praxis Agents](https://www.praxis-agents.ai/). The goal is to rebuild the useful
parts of an older, larger system into a smaller, cleaner, higher-quality
foundation for agentic work.

This port is intentionally selective. Do not copy old behavior forward just
because it existed. Keep features only when they are clear, general, maintainable,
and aligned with the product direction.

## Current Shape

- `apps/api` is the FastAPI backend. It also ships a separate scheduled-agent
  worker process (`workers/agent_runner.py`).
- `apps/web` is the Vite + React single-page frontend (TanStack Router + TanStack
  Query). It talks to the API over REST and consumes agent turns over SSE.
- `docker-compose.yml` defines local Postgres (pgvector image), the API, the
  worker, and the web app. The root `Makefile` wraps the local dev flow
  (`make bootstrap`, `make dev`, `make check`).
- `docs/plans/` holds the numbered implementation plans and the master roadmap.

Domains wired end to end (service + route + UI): auth (password, OAuth, TOTP,
sessions), users, workspaces (memberships, invitations), agents, conversations
(SSE chat with tool calls and approvals), agent runs (approval resume), the LLM
model catalog, and storage (signed uploads, avatars/icons).

Foundations that exist without public routes or UI yet: agent schedules (worker
driven only), notifications, and audit/security event services. pgvector is
provisioned by migrations but no vector columns exist yet. Prefer honest
incremental work over filling gaps with speculative abstractions.

## Plans And Roadmap

- `docs/plans/000_MASTER_ROADMAP.md` is the authoritative ordering document;
  the table in `docs/plans/000_README.md` tracks per-plan status.
- Before executing a numbered plan, read it fully, honor its STOP conditions,
  and update its status row when done.
- Plans record decisions taken and findings rejected — check both before
  re-proposing something the roadmap already ruled out.

## Working Principles

- Read nearby code before editing. Follow existing local patterns unless they are
  clearly part of the old system being retired.
- Keep changes focused. Avoid opportunistic rewrites outside the task.
- Prefer removing bespoke or unused features over preserving compatibility with
  old internals.
- Keep public behavior explicit. If a capability is not wired end to end, document
  it as pending instead of implying it works.
- Add tests in proportion to risk, especially around auth, permissions, audit
  records, scheduling, migrations, approvals, and provider boundaries.
- Do not commit secrets, generated caches, local virtualenvs, local databases, or
  build outputs.
- Do not reference numbered plan docs from implementation code, comments, or
  docstrings. Plans guide the work; code should describe runtime behavior and
  durable design decisions without citing plan numbers or roadmap files.

## Backend Standards

The backend lives in `apps/api` and uses Python 3.12, FastAPI, SQLAlchemy 2,
Alembic, Pydantic settings, pydantic-ai 2.x, and `uv`. Ruff configuration lives
in `apps/api/ruff.toml`.

### Structure

- Keep request handling async all the way through.
- Use SQLAlchemy models and migrations for schema changes. Do not rely on app
  startup to mutate database schema.
- Keep settings in `core/settings`; it is composed from per-concern mixins, and
  the `model_validator` in `core/settings/__init__.py` must keep rejecting
  unsafe production combinations.
- Keep route modules thin. Put reusable domain logic in `services`.
- Each API route operation must live in its own route file. Route package
  `__init__.py` files may only compose routers from those operation modules.
- Each service operation must live in its own service file. Service package
  `__init__.py` files may only re-export operation functions.
- Service-specific helpers belong in `utils.py` inside that service directory.
  Helpers that are not service-specific and could be reused belong in the
  top-level `apps/api/utils/` package.
- Keep error handling structured through the existing exception layer:
  `core/exceptions` maps typed exceptions to RFC 7807 problem+json. Raise those
  exception types instead of ad-hoc `HTTPException`.
- Maintain the middleware ordering notes in `apps/api/main.py` when adding or
  moving middleware. The comment there is authoritative.

### Agent Runtime And Providers

- The agent runtime lives in `services/agents/runtime/`: SSE streaming with a
  versioned event protocol, run persistence, approval state
  (`DeferredToolRequests`/`DeferredToolResults`), capabilities, and agent-to-agent
  delegation under `runtime/delegation/`.
- LLM providers live in `services/agents/models/`. The catalog in `registry.py`
  is the single source of truth for available models; `factory.py` builds
  pydantic-ai models per provider. Resolve credentials only through the
  `provider_api_key` seam — never rely on implicit env pickup. All providers
  share the retrying HTTP client (`retrying_http_client()`), which handles
  transient HTTP failures at the transport layer.
- Scheduling runs in the separate worker (`workers/agent_runner.py`): croniter
  schedules, TTL leases with heartbeats, terminal failure states. Schedules have
  no HTTP routes yet; that surface is planned, not implied.
- Storage goes through the `services/storage` provider abstraction. `local_fs`
  is the local default; cloud providers are optional extras (`gcs`, `s3`,
  `azure`) and must stay behind the `StorageProvider` contract.
- The runtime HTTP dependency is `httpx2`; plain `httpx` is dev-only.

### Auth And Request Handling

- Auth accepts the `session` cookie first, then `Authorization: Bearer`;
  internal HS256 JWTs authenticate scheduled runs and are pinned to their
  workspace.
- The active workspace resolves from the `X-Workspace` header via membership
  lookup; RBAC uses the `require_role`/`require_owner`/`require_editor`/
  `require_read` dependencies.
- CSRF is enforced when a session cookie is present (Origin check plus
  HMAC-signed `X-CSRF-Token`); rate limiting is Postgres-backed and fail-closed
  for auth flows. Do not widen exempt lists casually.
- Preserve auditability for sensitive operations. Workspace, security, approval,
  notification, and schedule flows should leave enough context to debug later.

### Tests

- Keep API tests organized by intent under `apps/api/tests`: contract, routes,
  services, integration, middleware, factories, and support. Do not add random
  root-level `test_*.py` files. Test key behavior and high-risk flows rather
  than creating one test file per route or service operation by default.
- Pytest is configured in `apps/api/pyproject.toml` with
  `asyncio_mode = "auto"`, so async test functions run without per-module
  markers.
- Database-backed tests run against a real Postgres and skip cleanly unless
  `TEST_DATABASE_URL` is set; `make api-test` provisions the local test database
  and sets that variable automatically. Use the fixtures in `conftest.py` and
  the helpers in `tests/factories/` and `tests/support/` instead of hand-rolling
  setup. Live LLM calls are blocked in tests.

Useful backend commands:

```bash
cd apps/api
uv sync
uv run ruff check .
uv run alembic check
uv run alembic upgrade heads
uv run pytest
uv run uvicorn main:app --reload --port 8000
```

### Migrations

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

## Frontend Standards

The frontend lives in `apps/web` and uses Vite, React 19, TypeScript (strict,
with `exactOptionalPropertyTypes` and friends), Tailwind CSS 4, and `pnpm`. It
is a single-page app with no server runtime.

### Structure

- `src/app/` is bootstrap only (App, router, query client); `src/config/` is
  plain data and env parsing; `src/lib/` holds framework-light helpers
  including the API client; `src/components/ui/` holds shadcn primitives;
  `src/routes/` holds top-level route shells.
- Feature code lives in `src/features/<feature>/` with `api/`, `components/`,
  `routes/`, and a feature-local `types.ts`. Follow this layout for new
  features.
- Layering is enforced by `.dependency-cruiser.cjs` (`pnpm arch`): no cycles;
  `components/ui` stays generic; `lib/api` stays framework-light; features do
  not import route shells; routes do not import `app/`. Fix violations by
  restructuring, not by editing the rules.
- Routing is TanStack Router with a code-based route tree in
  `src/app/router.tsx` (no file-based routing). Lazy-load route components with
  `lazyRouteComponent`; gate auth in `beforeLoad`.

### Data And API

- TanStack Query is the data layer. Each `features/*/api/*.ts` file is one
  operation: reads export `queryOptions` factories, `useSuspenseQuery` hooks,
  and structured `queryKeys`; writes export `useMutation` hooks that invalidate
  or seed the cache. Workspace-scoped query keys include the workspace slug.
- All requests go through `src/lib/api/client.ts`, which sends credentials,
  the CSRF header, and the `X-Workspace` header. Do not call `fetch` directly
  from features.
- SSE handling lives in `src/features/conversations/stream/`: a hand-written
  parser, a typed versioned event protocol, and a reducer. The parser throws on
  unknown event names, so a new server-side event breaks stale clients — ship
  the client change first.
- API types are hand-written per feature in `types.ts`; there is no OpenAPI
  codegen. Use `type` aliases, not `interface` (lint-enforced).
- Forms use native HTML forms plus `FormData` with the helpers in
  `src/lib/forms.ts` and hand-rolled validation models. Do not introduce a form
  or schema-validation library.

### UI

- Components are shadcn (`base-nova` style) built on `@base-ui/react`, with
  Tailwind 4 configured CSS-first in `src/index.css` (no `tailwind.config.js`),
  lucide icons, and `cn()` from `lib/utils.ts`. `src/components/ui/` is treated
  as vendored output (excluded from knip, relaxed lint) — prefer adding shadcn
  components over hand-building primitives.
- Build the real product interface, not marketing pages, unless the task
  explicitly asks for marketing content.
- Keep UI dense, practical, and clear. This is an operational tool for building
  and running agents. Prefer simple, accessible controls over custom widgets.
- Do not leave default scaffold copy, metadata, or assets in user-facing screens.
- Keep frontend environment values explicit with `VITE_*` only — every such
  value is inlined into the browser bundle. Currently the only one is
  `VITE_API_BASE_URL`; there is no Vite dev proxy, the browser calls the API
  origin directly.

### Checks

Vitest is installed for focused frontend unit tests. `pnpm test` runs inside
`pnpm check` and CI, with tests kept under `apps/web/tests/` using paths that
mirror the source module under test. Do not add colocated frontend tests under
`apps/web/src/`. The rest of the gate is static analysis: typecheck, eslint
(zero warnings), prettier, knip dead-code detection, dependency-cruiser, and
the build. Run `pnpm check` (or the relevant subset) before finishing frontend
work.

```bash
cd apps/web
pnpm install
pnpm check
pnpm dev
```

## Local Development

The root `Makefile` (with sections in `makefiles/`) wraps the local flow:
`make bootstrap` creates missing `.local/` env files and installs dependencies,
`make dev` starts Postgres, migrates, and runs the API, worker, and web dev
servers, and `make check` runs the main backend and frontend gates.

Docker Compose expects local env files under `.local/`. They are intentionally
not committed. See the root `README.md` for the current bootstrap flow.

When changing Docker behavior:

- Keep local services bound to `127.0.0.1` unless there is a deliberate reason not
  to.
- Keep production images small and non-root.
- Do not bake runtime secrets into images.

## Security And Product Constraints

- Treat workspace boundaries, approval workflows, delegation, audit trails, and
  session handling as high-risk areas.
- Never loosen CORS, cookie, CSRF, rate-limit, or provider validation just to make
  local development easier. Add explicit local configuration instead.
- Local-only providers such as console email and local filesystem storage should
  stay local-only; settings validation must keep rejecting them outside local
  environments.
- Agent actions that affect external systems should be permissioned, observable,
  and reversible where practical.

## Before Finishing Work

- Run the most relevant checks you can for the files changed (`make check` runs
  the main gates for both apps).
- Update docs when setup steps, commands, routes, env vars, or architecture change.
- Call out any checks you could not run.
- Leave unrelated user changes untouched.
