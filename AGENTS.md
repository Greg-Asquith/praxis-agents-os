# AGENTS.md

@TECHNICAL_LANGUAGE_GUIDE.md

Guidance for coding agents working in this repository. This root file holds
repo-wide expectations; backend standards live in `apps/api/AGENTS.md` and
frontend standards in `apps/web/AGENTS.md` — read the one for the app you are
changing. `REVIEW.md` is the code-review checklist.
`TECHNICAL_LANGUAGE_GUIDE.md` (imported above) governs all writing: user-facing
copy, public documentation, and code comments and docstrings.

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
  scheduled-agent runner and the generic jobs runner. It polls continuously by
  default; `WORKER_MODE=drain` processes available work until both queues are
  empty or the drain budget expires, then exits for run-to-completion platforms.
  Terminal agent runs retain their existing lifecycle status and separately
  record a structured outcome plus bounded completion evidence. Terminal
  transitions serialize on the generic run row so the first verdict remains
  authoritative under cancellation/finalization races. Schedules may also
  require a bounded completion report against operator-authored criteria;
  pass, fail, and missing-report verdicts remain separate from lifecycle status.
  AI usage is recorded in a forced-RLS, runtime-append-only ledger with one row
  per logical agent, helper, or embedding invocation, not per provider request.
  Successful and suspended agent invocations record atomically with their run
  transition; failure/cancellation and helper/embedding paths use best-effort
  durable recording through a distinct bounded runtime-role connection pool.
  Owner/admin usage routes apply effective-dated public prices to UTC daily
  buckets and expose estimated workspace cost, trends (one zero-filled point
  per UTC day in the requested range), attribution breakdowns, and explicit
  pricing coverage. Super admins can use a separately gated,
  database-read-only maintenance view to see the same measures across all
  workspaces, including workspace and cross-workspace user attribution.
  Image-generation events retain known output
  metadata so GPT Image 2 and Gemini 3.1 Flash Image estimates are added
  separately from the mainline helper model. This ledger is observability only:
  it does not enforce budgets or admission.
- `apps/web` is the Vite + React single-page frontend (TanStack Router +
  TanStack Query). It talks to the API over REST and consumes agent turns over
  SSE.
- `docker-compose.yml` defines local Postgres (pgvector image), the API, the
  worker, and the web app. The root `Makefile` wraps the local dev flow
  (`make bootstrap`, `make dev`, `make check`).
- `deploy/gcp/` contains the customer-independent GCP bootstrap, Cloud Run
  service/job templates, and the build/migrate/deploy path. Real environment
  files stay outside git (or under `.local/`); the GCP bootstrap and deploy
  Make targets require an explicit `ENV_FILE`, and bootstrap keeps
  API/IAM/billable mutations behind a typed interactive approval gate. It
  generates initial Cloud SQL credentials and core Secret Manager payloads in
  memory, redacts them from previews, and seeds them without writing them to
  disk. Deployments run manually from an authenticated operator machine; the
  bootstrap does not provision GitHub Actions deployment identity federation.

Domains wired end to end (service + route + UI): auth (password, OAuth, TOTP,
sessions), users, workspaces (memberships, invitations), agents, conversations
(SSE chat with tool calls and approvals), agent runs (durable approval resume,
configurable approval expiry, and staged-input cleanup), the
LLM model catalog, AI usage and estimated public-rate costs, files and storage
(signed uploads, revisions, background
markdown extraction), skills, knowledge base, agent memories, the context hub,
schedules, integrations (OAuth, API-key, and service-account connections),
artifacts (dedicated immutable revisions, approval-gated agent
tools, agent list/read/update across conversations, workspace management UI,
append-only edit/restore flows, and
version-pinned anonymous share links with CSP-locked serving), the tool
catalog, provider-native isolated code execution for computation, new document
generation, and append-only editing of existing workspace documents, and the
audit/security event viewers.

Backend-only for now: notifications (service exists, no routes or UI).
Knowledge Base chunks and agent memories use `HALFVEC` embeddings with HNSW
indexes provisioned by migrations. Keep
public behavior explicit — if a capability is not wired end to end, document
it as pending instead of implying it works.

## Planning And Scope

- Use GitHub issues for public work tracking and the stable documents under
  `docs/architecture/` for durable design decisions.
- Keep implementation notes and scratch plans local. Code, comments, and
  docstrings should describe runtime behavior and durable design decisions,
  not private planning artifacts.
- Before proposing a broad capability, check the architecture notes and recent
  history for prior decisions or rejected approaches.

## Working Principles

- Do not create Git commits without explicit human approval. A request to
  implement, fix, or change code does not by itself authorize a commit; obtain
  clear approval before running `git commit`.
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
- `python3 .github/scripts/dependency_audit.py api` and `python3
  .github/scripts/dependency_audit.py web` run the same blocking,
  production-only dependency audits as CI; both require registry access.
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
not committed. The Compose `init` service creates them for Docker-only use;
`make bootstrap` invokes the same initializer and installs dependencies;
the initializer enables anonymous artifact sharing for local development while
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
behavior: keep local services bound to
`127.0.0.1`, keep production images small and non-root, and do not bake
runtime secrets into images.
