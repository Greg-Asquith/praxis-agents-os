# Contributing to Praxis Agents OS

Thank you for helping improve Praxis Agents OS. The project favors focused,
maintainable changes that strengthen a clean foundation for small teams.

## Development setup

Install Python 3.12, `uv`, Node.js 24, `pnpm`, and Docker. Then run:

```bash
make bootstrap
make dev
```

The default development flow runs Postgres in Docker and the API, worker, and
web app locally with reload. Before opening a pull request, run:

```bash
make check
```

Focused commands and architecture expectations are documented in
[AGENTS.md](AGENTS.md), [apps/api/AGENTS.md](apps/api/AGENTS.md), and
[apps/web/AGENTS.md](apps/web/AGENTS.md). The
[review checklist](REVIEW.md) describes what maintainers scrutinize.

## Plan-driven workflow

The [implementation-plan index](docs/plans/000_README.md) tracks planned and
completed work, while the
[master roadmap](docs/plans/000_MASTER_ROADMAP.md) is authoritative for
ordering. Before implementing a numbered plan, read it fully and honor its
STOP conditions. Update its status and roadmap bookkeeping in the same
change when the plan is complete.

For work that is not already planned, open an issue describing the problem
and intended outcome before investing in a large implementation.

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

Link the relevant issue or plan and call out migration, security, tenancy,
approval, provider, or user-facing risks explicitly.

## Versioning

Praxis Agents OS follows semantic versioning with a `0.x` pre-1.0 posture.
While the major version is zero, breaking API, schema, and configuration
changes may ship in a minor release. Patch releases are reserved for
backward-compatible fixes.

By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
