# Contributing to Praxis Agents OS

Thank you for helping improve Praxis Agents OS. The project favors focused,
maintainable changes that strengthen a clean foundation for small teams.

## Development setup

Install Python 3.12, `uv`, Node.js 24, `pnpm`, and Docker. Then prepare the
local environment and start the development services:

```bash
make bootstrap
make dev
```

The default development flow runs Postgres in Docker. It runs the API, worker,
and web app locally with automatic reload. Before opening a pull request, run
the full quality gate:

```bash
make check
```

Focused commands and architecture expectations are documented in
[AGENTS.md](AGENTS.md), [apps/api/AGENTS.md](apps/api/AGENTS.md), and
[apps/web/AGENTS.md](apps/web/AGENTS.md). The
[review checklist](REVIEW.md) describes the maintainers' review criteria.

## Issue-driven workflow

Use GitHub issues for public work tracking. Before investing in a large
implementation, open an issue describing the operator problem, intended
outcome, scope, risks, and relevant architecture decisions. Durable design
decisions belong under `docs/architecture/`; private implementation notes do
not need to be committed.

## Pull requests

- Keep the change focused and avoid unrelated refactors.
- Follow nearby code and existing service, route, data-fetching, and UI
  patterns.
- Add tests in proportion to risk, especially for authentication,
  permissions, approvals, scheduling, migrations, audit records, and provider
  boundaries.
- Update setup, command, route, environment, and architecture documentation
  in the same change.
- Run `make check` and list any additional focused checks in the pull request.
- Use a concise imperative commit subject with an area prefix when useful,
  such as `API - Reject placeholder production secrets`.

Link the relevant issue and call out migration, security, tenancy,
approval, provider, or user-facing risks explicitly.

## Versioning

Praxis Agents OS follows semantic versioning with a `0.x` pre-1.0 posture.
While the major version is zero, breaking API, schema, and configuration
changes may ship in a minor release. Patch releases are reserved for
backward-compatible fixes.

By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
