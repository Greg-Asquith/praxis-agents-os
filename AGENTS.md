# AGENTS.md

Guidance for coding agents working in this repository. This root file holds
repo-wide expectations; backend standards live in `apps/api/AGENTS.md` and
frontend standards in `apps/web/AGENTS.md` — read the one for the app you are
changing. `REVIEW.md` is the code-review checklist.

## Project Intent

Praxis Agents OS is the open source codebase behind
[Praxis Agents](https://www.praxis-agents.ai/): a platform for creating,
operating, and governing AI agents — workspaces, conversations with tool calls
and approvals, schedules, files, skills, integrations, and audit trails that a
small team can run and maintain.

Optimize for a small, clean, high-quality foundation. Add capability only when
it is clear, general, maintainable, and aligned with the product direction.
Prefer removing bespoke or unused features over preserving compatibility with
internals. The product targets a non-technical operator: complexity belongs
behind good defaults and progressive disclosure, not in their face.

## Current Shape

- `apps/api` is the FastAPI backend. Background work runs in a separate worker
  process (`python -m workers.main`) that supervises two loops: the
  scheduled-agent runner and the generic jobs runner.
- `apps/web` is the Vite + React single-page frontend (TanStack Router +
  TanStack Query). It talks to the API over REST and consumes agent turns over
  SSE.
- `docker-compose.yml` defines local Postgres (pgvector image), the API, the
  worker, and the web app. The root `Makefile` wraps the local dev flow
  (`make bootstrap`, `make dev`, `make check`).
- `docs/plans/` holds the numbered implementation plans and the master roadmap.

Domains wired end to end (service + route + UI): auth (password, OAuth, TOTP,
sessions), users, workspaces (memberships, invitations), agents, conversations
(SSE chat with tool calls and approvals), agent runs (approval resume), the
LLM model catalog, files and storage (signed uploads, revisions, background
markdown extraction), skills, schedules, integrations (OAuth and API-key
connections), the tool catalog, and the audit/security event viewers.

Backend-only for now: notifications (service exists, no routes or UI).
pgvector is provisioned by migrations but no vector columns exist yet. Keep
public behavior explicit — if a capability is not wired end to end, document
it as pending instead of implying it works.

## Plans And Roadmap

- `docs/plans/000_MASTER_ROADMAP.md` is the authoritative ordering document;
  the table in `docs/plans/000_README.md` tracks per-plan status.
- The next major verticals are integration resource discovery/context and the
  first providers (Gmail, Google Ads, Airtable), the knowledge base, agent
  memory, artifacts, harness hardening with behavior evals, and public launch
  readiness.
- Before executing a numbered plan, read it fully, honor its STOP conditions,
  and update its status row when done. Plans record decisions taken and
  findings rejected — check both before re-proposing something the roadmap
  already ruled out.
- Do not reference numbered plan docs from implementation code, comments, or
  docstrings. Plans guide the work; code should describe runtime behavior and
  durable design decisions without citing plan numbers or roadmap files.

## Working Principles

- Read nearby code before editing and follow existing local patterns. Keep
  changes focused; do the simplest thing that works well and avoid
  refactors, new abstractions, or features beyond what the task requires.
- Add tests in proportion to risk, especially around auth, permissions, audit
  records, scheduling, migrations, approvals, and provider boundaries.
- Do not commit secrets, generated caches, local virtualenvs, local databases,
  or build outputs.
- Update docs — including the relevant AGENTS.md — in the same change that
  alters setup steps, commands, routes, env vars, or architecture.

## Verification

- `make check` runs the full gate: backend ruff lint + format check, Alembic
  migration-drift check, database-backed pytest (it provisions the local test
  database automatically), and the complete frontend `pnpm check`.
- Per-app commands are listed in each app's AGENTS.md. Before finishing, run
  the most relevant checks for the files you changed and call out any you
  could not run.

## Security And Product Constraints

- Treat workspace boundaries, approval workflows, delegation, credential
  handling, audit trails, and session handling as high-risk areas.
- Never loosen CORS, cookie, CSRF, rate-limit, or provider validation just to
  make local development easier. Add explicit local configuration instead.
- Local-only providers such as console email and local filesystem storage stay
  local-only; settings validation must keep rejecting them outside local
  environments.
- Agent actions that affect external systems should be permissioned,
  observable, and reversible where practical.

## Local Development

Docker Compose expects local env files under `.local/`; they are intentionally
not committed. `make bootstrap` creates them and installs dependencies;
`make dev` starts Postgres, migrates, and runs the API, worker, and web dev
servers. When changing Docker behavior: keep local services bound to
`127.0.0.1`, keep production images small and non-root, and do not bake
runtime secrets into images.
