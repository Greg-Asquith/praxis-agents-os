# Repository guidelines

Praxis Agents OS is the open source platform behind
[Praxis Agents](https://www.praxis-agents.ai/) for creating, operating, and
governing AI agents. Optimise for a small, maintainable foundation and a
non-technical operator. Put complexity behind defaults and progressive
disclosure. Prefer removing bespoke internals over preserving compatibility.

## Read before changing files

Read the instructions and references that apply to the task:

- For all writing, read and follow the
  [technical language guide](TECHNICAL_LANGUAGE_GUIDE.md), including comments
  and docstrings.
- For backend changes, read [backend guidelines](apps/api/AGENTS.md).
- For frontend changes, read [frontend guidelines](apps/web/AGENTS.md).
- For reviews and final self-review, use the [review checklist](REVIEW.md).
- For implementation details, use the [documentation index](docs/README.md).
  Read the relevant domain and provider references before editing that area.

Read app instructions explicitly even when starting from the repository root.
Linked implementation documents are task-specific references, not startup
imports. For the instruction layout and its rationale, see the
[agent instruction guide](docs/guides/agent-instructions.md).

## Working rules

Apply these rules throughout the task:

- Do not create Git commits without explicit human approval. A request to
  implement, fix, or change code does not authorise `git commit`.
- Read nearby code before editing. Complete the requested scope, make routine
  implementation choices, and keep changes focused. Report unrelated findings
  instead of adding refactors, abstractions, or features to the change.
- Keep functions easy to follow. Use cyclomatic complexity as design feedback
  and extract focused helpers when that makes control flow clearer.
- Use GitHub issues for public tracking and `docs/architecture/` for durable
  design decisions. Keep scratch plans and private implementation notes local.
- Before proposing broad capabilities, check architecture notes and recent
  history for prior decisions and rejected approaches.
- When behaviour, routes, settings, or setup changes, update the owning docs in
  the same change. Update AGENTS.md when guidelines or navigation change; keep
  provider inventories and implementation details in focused references.
- Describe public capabilities as implemented only when wired end to end.
  Mark incomplete capabilities as pending.
- Keep secrets, generated caches, virtual environments, local databases, and
  build outputs out of Git.
- You are working as a swarm of agents collaborating to reach the same goals. 
  There is a private message board available to you and all other agents at
  `docs/message-board/`. You may create or update any files in this dir to 
  help communicate your progress with other agents and ensure you are collaborating
  in the best way to reach the goals without clashing or competing.

## Security and product boundaries

Preserve these boundaries in every change:

- Treat workspace isolation, approvals, delegation, credentials, audit, and
  sessions as high-risk areas. Add tests in proportion to risk.
- Keep CORS, cookies, CSRF, rate limits, and provider validation strict. Use
  explicit local configuration instead of weakening production behaviour.
- Keep console email and local filesystem storage local-only, with settings
  validation rejecting them elsewhere.
- Keep agent actions on external systems permissioned, observable, and
  reversible where practical.
- For Docker changes, keep local services bound to `127.0.0.1`, production
  images small and non-root, and runtime secrets outside images.
- For GCP bootstrap and deployment, use an explicit `ENV_FILE` and preserve
  the bootstrap's typed approval gate. Read `deploy/gcp/README.md` first.

## Repository and verification

`apps/api` contains the FastAPI backend and separate Python worker.
`apps/web` contains the Vite and React frontend. The root Makefile wraps local
development; Docker Compose provides Postgres and optional application services.

Use the relevant checks and report anything you could not run:

- `make bootstrap` prepares local configuration and dependencies; `make dev`
  starts the local development stack. See
  [local development](docs/implementation/local-development.md) for details.
- `make check` runs backend lint and format checks, Alembic drift checks,
  database-backed pytest, and the complete frontend `pnpm check`.
- Run the most relevant checks for changed files before finishing. Keep test
  scope proportional to the change and use each app's documented commands.
- Production dependency audits match CI and require registry access:
  `python3 .github/scripts/dependency_audit.py api` and
  `python3 .github/scripts/dependency_audit.py web`.
