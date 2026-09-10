# Database tenancy and migrations

Read this before changing database roles, tenant sessions, protected tables,
or migrations. Backend paths are relative to `apps/api/`.

## Tenant isolation

The following contracts apply in this area:

- Runtime API and tenant-owned worker sessions use `DATABASE_URL` and execute
  as the non-owner `praxis_app` role. Alembic, cross-workspace job claiming,
  and deliberate system work use `DATABASE_MAINTENANCE_URL`. The two URLs must
  identify distinct database roles outside local development; local Postgres
  may use the owner URL for both because runtime transactions immediately
  `SET LOCAL ROLE praxis_app`.
- In non-local deployments, provision the `praxis_app` login credential through
  the database administration layer before migrations. Startup verifies that
  `DATABASE_URL` authenticates directly as `praxis_app` and that the maintenance
  connection authenticates as a different, unassumed role.
- Workspace and user tenancy is carried in SQLAlchemy `session.info` and
  applied as transaction-local `app.current_workspace_id` and
  `app.current_user_id` GUCs. Request dependencies establish the context;
  tenant job handlers must establish it before reading protected rows. New
  background entrypoints must either set this context or deliberately use a
  maintenance session.
- New workspace-confidential tables must enable and force RLS in the same
  migration that creates them, retain explicit application-layer tenant
  predicates, and be added to `tests/security/test_workspace_rls.py`.
  Missing GUCs must continue to fail closed. Never grant the runtime role
  `BYPASSRLS`, ownership, or superuser privileges.
- Skills have exactly two immutable scopes. Workspace skills retain a required
  `workspace_id` and normal tenant ownership. Platform skills have
  `workspace_id = NULL`, are readable and assignable in every workspace, and
  are mutable only by configured super admins through a maintenance session;
  tenant RLS policies must remain select-only for those rows. Platform skills
  are text-only: do not add workspace document storage, copying, forking, or
  ownership transitions to their lifecycle.

## Content ownership and publication foundation

Knowledge documents and chunks, Files and revisions, and Artifacts and
revisions carry immutable `workspace` or `platform` ownership. Workspace rows
require a workspace ID and keep `is_published = false`. Platform rows have no
workspace owner and default to unpublished. Upload grants carry the same
ownership pair and bind their intended File and revision IDs.

Upload reservations and File/revision creation use `READ COMMITTED`, the
application's default transaction isolation. Database triggers serialise
checks for reserved IDs and reject conflicting ownership, including concurrent
reservations. These checks reject other isolation levels because their earlier
snapshots could hide a conflicting reservation after waiting for its lock.

Command-specific policies admit published platform content only for runtime
sessions with a workspace context. Tenant writes remain workspace-only.
Platform revisions additionally require their own publication marker and a
published, non-deleted parent. Knowledge chunks inherit document visibility.
File and Artifact current pointers identify draft revisions; separate
published pointers identify reviewed revisions. Publication markers on
revisions cannot be cleared. Withdrawal hides the parent and all its revisions.

Database checks enforce parent ownership, revision membership, and immutable
ownership. Platform knowledge excludes private, conversation, URL, and
integration sources. Platform Files have no folder, and platform Artifacts
have no workspace conversation, run, or agent provenance. References and
anonymous Artifact shares retain workspace ownership.

The migration preserves existing workspace rows. Its downgrade refuses while
any platform content or upload grant remains. Export required content and
explicitly remove platform rows through a maintenance procedure before
downgrading. The migration never deletes platform content for you.

Platform authoring, storage, retrieval, and operator interfaces are pending.
These database structures alone do not make platform content available
through the product.

## Connection capacity

The per-process connection and turn-concurrency settings are defined as
follows:

| Setting | Default | Purpose |
|---|---:|---|
| `AGENT_RUN_MAX_CONCURRENT_TURNS` | `11` | Maximum admitted interactive turns per API process. Keep this value at or below `DB_POOL_SIZE + DB_POOL_MAX_OVERFLOW - 4`. |
| `DB_MAINTENANCE_POOL_MAX_OVERFLOW` | `3` | Maximum overflow connections beyond the maintenance pool size per process. |
| `DB_MAINTENANCE_POOL_SIZE` | `3` | Persistent connections in the maintenance pool per process. |
| `WORKER_MAX_CONCURRENT_RUNS` | `4` | Maximum scheduled runs and generic job handlers active across one worker process. Keep this at or below the smaller runtime or maintenance pool capacity minus one so lease heartbeats retain a connection. |

## Create a migration

Alembic has separate `core` and `app` branch heads. Platform infrastructure
tables go on the `core` branch; the `app` branch is reserved for verticals.
Before creating a migration, complete the
[local database setup](local-development.md#backend-commands) so the database
is running and migrated. From the repository root, enter `apps/api/` and
export its local configuration in the same shell used for Alembic:

```bash
cd apps/api
set -a
. ./.env
set +a
```

Alembic uses `DATABASE_MAINTENANCE_URL`, falling back to `DATABASE_URL` when
the maintenance URL is unset. It does not load `.env` itself.

For a platform infrastructure change, create a migration on the `core` branch:

```bash
uv run alembic revision --autogenerate \
  --head core@head \
  --version-path alembic/versions/core \
  -m "describe core schema change"
```

For a vertical change, use the `app` branch instead:

```bash
uv run alembic revision --autogenerate \
  --head app@head \
  --version-path alembic/versions/app \
  -m "describe app schema change"
```
