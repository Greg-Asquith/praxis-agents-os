# Backend guidelines

Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic AI 2.x, and `uv`.
Follow the [repository guidelines](../../AGENTS.md). Paths below are relative
to `apps/api/` unless stated otherwise. Ruff configuration lives in `ruff.toml`.

## Structure

Follow these backend conventions:

- Keep request handling async all the way through.
- Use SQLAlchemy models and migrations for schema changes. Do not rely on app
  startup to mutate database schema.
- Keep settings in `core/settings`; it is composed from per-concern mixins,
  and the `model_validator` in `core/settings/__init__.py` must keep rejecting
  unsafe production combinations.
- Keep route modules thin. Put reusable domain logic in `services`.
- Each API route operation must live in its own route file. Route package
  `__init__.py` files may only compose routers from those operation modules.
- Each service operation must live in its own service file. Service package
  `__init__.py` files may only re-export operation functions.
- Service-specific helpers belong in `utils.py` inside that service directory.
  Helpers that are not service-specific belong in the top-level
  `apps/api/utils/` package.
- Keep error handling structured through the existing exception layer:
  `core/exceptions` maps typed exceptions to RFC 7807 problem+json. Raise
  those exception types instead of ad-hoc `HTTPException`.
- Maintain the middleware ordering notes in `apps/api/main.py` when adding or
  moving middleware. The comment there is authoritative.
- The runtime HTTP dependency is `httpx2`; plain `httpx` is dev-only.

## Security and execution boundaries

Preserve these boundaries in every backend change:

- Scope tenant queries explicitly and run them as `praxis_app` with workspace
  and user context. New confidential tables require forced row-level security
  in their creating migration and coverage in `tests/security/test_workspace_rls.py`.
- Keep maintenance access explicit. Never grant runtime ownership, superuser,
  or `BYPASSRLS` privileges.
- Route every agent tool through the registry and `runtime/dispatch.py` for
  authorisation, approval, audit, and bounded results.
- Resolve credentials through the existing provider and secret-reference
  contracts. Keep provider packages behind the shared integration interfaces.
- Queue background work through the generic jobs system. Preserve owner-bound
  leases, tenant context, cancellation, and idempotent external effects.
- Preserve typed request errors, role checks, and audit evidence for sensitive
  operations. Keep settings validation strict outside local development.

## Read for your task

Before editing a domain, read its implementation reference and the linked
architecture decisions. Paths in this table are relative to this file:

| Change area | Required reference |
| --- | --- |
| Database roles, tenancy, or migrations | [Database](../../docs/implementation/database.md) |
| Authentication, invitations, encryption, or audit | [Security](../../docs/implementation/security.md) |
| Runs, schedules, active context, or streaming | [Agent runs](../../docs/implementation/agent-runs.md) |
| Tools, startup catalogues, results, or approval fields | [Tool dispatch](../../docs/implementation/tool-dispatch.md) |
| Code Mode or nested approvals | [Code Mode](../../docs/implementation/code-mode.md) |
| Third-party connections, discovery, or integration tools | [Integration guide and provider references](../../docs/implementation/integrations/README.md) |
| Outlook mail tools, approvals, attachments, or previews | [Microsoft Graph](../../docs/implementation/integrations/microsoft-graph.md) |
| Model catalogue, Vertex, or model HTTP clients | [Model providers](../../docs/implementation/model-providers.md) |
| Native fetch, code, classifiers, or image tools | [Native helper tools](../../docs/implementation/native-tools.md) |
| Worker admission, leases, or shutdown | [Workers](../../docs/implementation/workers.md) |
| Usage ledger, pricing, or usage routes | [AI usage](../../docs/implementation/ai-usage.md) |
| Storage, uploads, file revisions, or attachments | [Storage and files](../../docs/implementation/storage-and-files.md) |
| Knowledge Base import or source refresh | [Knowledge sources](../../docs/implementation/knowledge-sources.md) |

## Verification

Use checks that exercise the changed behaviour:

- From the repository root, `make api-test` runs the database-backed suite.
  Direct pytest can skip database tests unless `TEST_DATABASE_URL` is set.
- From `apps/api/`, run `uv run ruff check .` and
  `uv run ruff format --check .`; schema changes also require
  `make api-migrations-check` from the repository root against a migrated
  local database. This target exports the API environment before Alembic runs.
- For streaming contract changes, update the client first and run
  `make stream-protocol-export` and `make stream-protocol-check` from the root.
- Keep tests under `tests/<intent>/`, using the shared fixtures, factories,
  and support helpers. Runtime changes need a deterministic scenario case.
  Keep live model calls out of pytest and `make check`.

For fixture rules, local commands, and opt-in live evaluations, read
[local development and verification](../../docs/implementation/local-development.md).
