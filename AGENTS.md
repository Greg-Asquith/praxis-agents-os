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
- `apps/web` is the Next.js frontend.
- `docker-compose.yml` defines local Postgres with pgvector, the API, and the web
  app.

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

No API test suite is committed yet. Add focused tests when adding behavior, then
run them with `uv run pytest`.

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

The frontend lives in `apps/web` and uses Next.js, React, TypeScript, Tailwind,
and `pnpm`.

- Use the App Router conventions already present in the app.
- Build the real product interface, not marketing pages, unless the task
  explicitly asks for marketing content.
- Keep UI dense, practical, and clear. This is an operational tool for building
  and running agents.
- Prefer simple, accessible controls over custom widgets.
- Do not leave default scaffold copy, metadata, or assets in user-facing screens.
- Keep frontend environment values explicit with `NEXT_PUBLIC_*` only where the
  value is safe to expose to browsers.

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
