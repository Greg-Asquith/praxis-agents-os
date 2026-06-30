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

- `apps/api` is the FastAPI backend.
- `apps/web` is the Vite + React single-page frontend.
- `docker-compose.yml` defines local Postgres with pgvector available, the API, and the web app. pgvector is enabled through Alembic.

The repository is still early in the port. Some foundations exist before their
public routes or UI are complete. Prefer honest incremental work over filling gaps
with speculative abstractions.

## Working Principles

- Read nearby code before editing. Follow existing local patterns unless they are
  clearly part of the old system being retired.
- Keep changes focused. Avoid opportunistic rewrites outside the task.
- Prefer removing bespoke or unused features over preserving compatibility with
  old internals.
- Keep public behavior explicit. If a capability is not wired end to end, document
  it as pending instead of implying it works.
- Add tests in proportion to risk, especially around auth, permissions, audit
  records, scheduling, migrations, and provider boundaries.
- Do not commit secrets, generated caches, local virtualenvs, local databases, or
  build outputs.

## Backend Standards

The backend lives in `apps/api` and uses Python 3.12, FastAPI, SQLAlchemy 2,
Alembic, Pydantic settings, and `uv`.

- Keep request handling async all the way through.
- Use SQLAlchemy models and migrations for schema changes. Do not rely on app
  startup to mutate database schema.
- Keep settings in `core/settings`; validate unsafe production combinations there.
- Keep route modules thin. Put reusable domain logic in `services`.
- Each API route operation must live in its own route file. Route package
  `__init__.py` files may only compose routers from those operation modules.
- Each service operation must live in its own service file. Service package
  `__init__.py` files may only re-export operation functions.
- Service-specific helpers belong in `utils.py` inside that service directory.
  Helpers that are not service-specific and could be reused belong in the
  top-level `apps/api/utils/` package.
- Keep API tests organized by intent under `apps/api/tests`: contract, routes,
  services, integration, middleware, factories, and support. Do not add random
  root-level `test_*.py` files. Test key behavior and high-risk flows rather
  than creating one test file per route or service operation by default.
- Preserve auditability for sensitive operations. Workspace, security, approval,
  notification, and schedule flows should leave enough context to debug later.
- Keep error handling structured through the existing exception layer.
- Maintain the middleware ordering notes in `apps/api/main.py` when adding or
  moving middleware.

Useful backend commands:

```bash
cd apps/api
uv sync
uv run ruff check .
uv run alembic check
uv run alembic upgrade heads
uv run uvicorn main:app --reload --port 8000
```

Add focused API tests when adding behavior, then run them with `uv run pytest`.

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

The frontend lives in `apps/web` and uses Vite, React, TypeScript, Tailwind, and `pnpm`. It is a single-page app with no server runtime: it talks to the FastAPI backend over REST and consumes agent turns over SSE.

- Follow the client-router and component conventions already present in the app.
- Build the real product interface, not marketing pages, unless the task
  explicitly asks for marketing content.
- Keep UI dense, practical, and clear. This is an operational tool for building
  and running agents.
- Prefer simple, accessible controls over custom widgets.
- Do not leave default scaffold copy, metadata, or assets in user-facing screens.
- Keep frontend environment values explicit with `VITE_*` only. Every such value is inlined into the browser bundle, so expose only values safe to make public.

Useful frontend commands:

```bash
cd apps/web
pnpm install
pnpm lint
pnpm build
pnpm dev
```

## Local Development

Docker Compose expects local env files under `.local/`. They are intentionally not
committed. See the root `README.md` for the current bootstrap flow.

When changing Docker behavior:

- Keep local services bound to `127.0.0.1` unless there is a deliberate reason not
  to.
- Keep production images small and non-root.
- Do not bake runtime secrets into images.

## Security And Product Constraints

- Treat workspace boundaries, approval workflows, audit trails, and session
  handling as high-risk areas.
- Never loosen CORS, cookie, CSRF, rate-limit, or provider validation just to make
  local development easier. Add explicit local configuration instead.
- Local-only providers such as console email and local filesystem storage should
  stay local-only.
- Agent actions that affect external systems should be permissioned, observable,
  and reversible where practical.

## Before Finishing Work

- Run the most relevant checks you can for the files changed.
- Update docs when setup steps, commands, routes, env vars, or architecture change.
- Call out any checks you could not run.
- Leave unrelated user changes untouched.
