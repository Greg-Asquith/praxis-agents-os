# Backend Standards (apps/api)

Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic settings, pydantic-ai
2.x, managed with `uv`. Ruff configuration lives in `apps/api/ruff.toml`.
Repo-wide expectations are in the root `AGENTS.md`.

## Structure

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

## Database Tenancy

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

## Agent Runtime And Providers

- The agent runtime lives in `services/agents/runtime/`: SSE streaming with a
  versioned event protocol, run persistence, approval state
  (`DeferredToolRequests`/`DeferredToolResults`), capabilities, cooperative
  cancellation, and agent-to-agent delegation under `runtime/delegation/`.
  Terminal lifecycle transitions stamp a separate six-value `outcome` and
  bounded `completion_json` at the shared agent-run transition choke point;
  the transition refreshes under a row lock so the first terminal verdict is
  authoritative. Do not widen the six run statuses to represent completion
  verdicts. Required schedule completion contracts are copied into server-owned
  run metadata, inject their bounded criteria as a dedicated runtime system-
  instruction block (never into the visible user prompt), and
  mount the non-configurable internal `report_completion` tool only for that
  run; its pass/fail/missing-report verdict is resolved during successful
  finalization. Once mounted, the tool is always available and auto-executed
  regardless of workspace tool settings, role write policy, or the run
  side-effect envelope. The first accepted report is authoritative; later
  report attempts fail without replacing its evidence.
  Optional schedule `max_requests` and `max_total_tokens` completion-contract
  budgets may only tighten the resolved model/platform `UsageLimits`; they
  never widen defaults. Approval continuations must restore the run's persisted
  cumulative Pydantic AI usage so those limits apply across the whole generic
  run, not once per resume segment. A tripped limit fails the run with outcome
  `budget_exhausted` and records only its allowlisted kind and limit in bounded
  completion evidence. Budget declarations remain within the largest integer
  that round-trips losslessly through JSON and the TypeScript schedule editor.
  Parked approvals expire through the generic jobs harness after
  `AGENT_RUN_APPROVAL_EXPIRY_DAYS` (default 7; 0 disables), which fails the run,
  clears durable approval state, and transactionally enqueues retryable staged
  write-content cleanup. Lease reaping also queues that cleanup before clearing
  a resumed run's approval state. Resume reserves the locked run as `running`
  before its SSE response begins. The conversation active-run read exposes the
  parked run's expiry deadline and always treats an existing active run as the
  latest run, so an older terminal outcome cannot replace a new stream.
- Direct conversation creation may include an `active_context` selection. It
  must be validated and persisted after the conversation is flushed but before
  its first run is created, so the initial turn resolves the selected context.
  Every active workspace member, including `read_only`, may select context;
  tool dispatch separately enforces whether that member may perform read or
  write effects.
- Context Group membership derives from `Workspace.is_personal`: shared
  workspace groups accept only connections owned by that workspace; personal
  workspace groups also accept the current actor's user-owned connections.
  Standalone resource selection deliberately retains actor-or-workspace
  visibility and must not reuse the narrower group-membership rule.
- Every agent tool flows through the tool registry and the single dispatch
  choke point (`runtime/dispatch.py`), which owns per-invocation audit,
  policy/approval enforcement, run envelopes, and bounded tool results. Do
  not execute tool logic around it.
- Opaque tool targets use the runtime entity-reference contract. Internal
  resolvers stay under `services/agents/runtime/entity_references`; concrete
  provider reference models and resolvers stay in their provider package and
  publish only through the generic integrations seam. Scoped provider tools
  must revalidate the referenced active-context resource and target only that
  resource, never fan an entity ID out across compatible accounts.
- Approval overrides are governed by the server-owned field declarations:
  locked values cannot change, and entity values must be structured references
  that are reauthorized immediately before resume.
- Provider packages keep each agent tool in its own module under a `tools/`
  tree. The tree may share schemas and provider-local helpers, while its
  `__init__.py` only composes exported definitions; do not accumulate a
  provider's catalog in one `tools.py` module.
- Provider packages keep each entity resolver in its own module under an
  `entity_resolvers/` tree, with one module per entity kind. The package
  `__init__.py` only composes exported resolver definitions so provider
  manifests stay concise as their catalogs grow.
- Packaged integrations are Gmail, Google Ads, Airtable, and BigQuery.
  BigQuery contributes service-account dataset discovery, a job-synchronized
  table-schema cache for enabled datasets (connection jobs fan out into
  independently retryable dataset jobs), two cache-backed schema tools, and a
  dry-run-gated SELECT query tool with active-dataset, routine, reference-count,
  byte, serialized-result, and row bounds. Query jobs bill through the service
  account's own project. BigQuery warehouse values are plain typed data under
  the operator-controlled database trust boundary.
- LLM providers live in `services/agents/models/`. The catalog in
  `registry.py` is the single source of truth for available models;
  `factory.py` builds pydantic-ai models per provider. Resolve credentials
  only through the `provider_api_key` seam — never rely on implicit env
  pickup. All providers share the retrying HTTP client
  (`retrying_http_client()`).
- Native URL fetching uses the governed `fetch_url` helper-tool path for
  Anthropic and Google only. `NATIVE_WEB_FETCH_MAX_STEPS` bounds helper model
  requests, `NATIVE_WEB_FETCH_MAX_CONTENT_TOKENS` is passed to the provider,
  and comma-separated `NATIVE_WEB_FETCH_BLOCKED_DOMAINS` is enforced before
  dispatch as well as passed natively. Google is unavailable while that
  denylist is configured because URL Context cannot enforce domain filtering.
  Keep the full URL editable and visible under the default approval policy;
  never enable the local fetch fallback.
- Native image generation uses the governed `generate_image` helper-tool path
  for Google and OpenAI only. `NATIVE_IMAGE_GENERATION_MAX_STEPS` bounds the
  helper run. The tool generates exactly one image, preserves provider-returned
  PNG, WebP, or JPEG bytes in an audited workspace File, and defaults to
  approval. `edit_image` uses the current revision of a workspace image with
  OpenAI or Google and limits combined raw source bytes with
  `NATIVE_IMAGE_EDITING_MAX_INPUT_BYTES` (64 MiB by default);
  `generate_image_from_video` uses Google only and rejects inline videos larger
  than `NATIVE_VIDEO_TO_IMAGE_MAX_INPUT_BYTES` (18 MiB by default). Both
  input-media tools preserve the source file and revision ids in their result
  and generated-file audit evidence.
- Background work runs in the worker process (`python -m workers.main`),
  which supervises the scheduled-agent runner (croniter schedules, TTL leases
  with heartbeats, terminal failure states) and the generic jobs runner over
  the SKIP-LOCKED `jobs` table. `WORKER_MODE=forever` is the local/service
  default; `WORKER_MODE=drain` runs both queues to empty without polling sleeps
  and exits 0 when drained or when `WORKER_DRAIN_MAX_SECONDS` requests a clean
  stop. Drain passes claim one item at a time so shutdown cannot strand an
  unstarted batch, and the supervisor repeats both runners until they complete
  one jointly idle validation round. Each runner finishes or bounds its
  in-flight pass with its own shutdown grace setting. Generic jobs use mutually
  exclusive workspace or user
  concurrency ownership; authenticated work must use one of those buckets,
  while `NULL` ownership is reserved for system work. Queue new background work
  as jobs rather than inventing ad-hoc task mechanisms.
- Append-only `audit_events` and `security_events` are retained through
  independent system jobs. Their settings default to 400 days, production
  rejects values below 400, and staging may explicitly use a shorter positive
  window such as 90 days. The sweepers delete only rows strictly older than a
  cutoff computed once per run, work in bounded batches with immediate
  continuation when capped, and record deletion counts in the completed job
  payload without emitting replacement audit events.
- Application encryption uses a newest-first Fernet key ring loaded from
  `ENCRYPTION_KEYS` or the configured secret provider via
  `ENCRYPTION_KEYS_SECRET_NAME`. API and worker startup load the ring before
  serving work. Manual `security.converge_application_encryption` jobs rotate
  all durable user/TOTP/OAuth ciphertext in locked batches; a check pass must
  report zero stale and undecryptable values before an old key is removed, and
  both modes retain their count reports in the global audit log.
- Storage goes through the `services/storage` provider abstraction.
  `local_fs` is the local default; cloud providers (`gcs`, `s3`, `azure_blob`)
  must stay behind the `StorageProvider` contract, with their SDKs as
  optional extras (`gcp`, `aws`, `azure`). Public assets stay in one shared
  public bucket; managed avatar/icon keys retain their existing `users/...`
  and `workspaces/...` roots, so deployment URLs and public-access policies
  must not insert an extra prefix. Every private key must use
  `workspaces/{workspace_id}/...`
  and resolves unconditionally to that workspace's dedicated bucket/container.
  GCS bucket creation must pass the configured immutable
  `GCS_WORKSPACE_BUCKET_LOCATION`; provisioned GCS workspace buckets retain
  object versioning and a 30-day soft-delete policy alongside uniform access
  and public-access prevention. Their signed-upload CORS policy is converged
  from the explicit `ALLOWED_CORS_ORIGINS` allowlist; GCP bootstrap applies the
  same policy to the shared public-assets bucket. GCS client ADC must explicitly
  request the `cloud-platform` OAuth scope so metadata-server credentials can
  call IAM `signBlob`; the runtime service account must also retain Service
  Account Token Creator on itself. S3 workspace buckets use the
  account-regional
  namespace and derive their physical name from the configured prefix, compact
  workspace UUID, `AWS_ACCOUNT_ID`, and `AWS_REGION`; retain ownership controls,
  versioning, HTTPS-only policy, blocked public access, and the encryption
  baseline when changing S3 provisioning.
  Workspace creation enqueues `storage.provision_workspace_bucket`, while
  first writes and signed uploads retain an idempotent provisioning backstop.
  Cloud identities must be able to inspect, create, harden, and read/write
  bucket tags or labels without discarding provider- or operator-owned values.
  Direct-upload grants target unique temporary keys only; confirmation
  validates and conditionally promotes bytes to a distinct create-only durable
  key. Upload capabilities bind the exact client-declared byte length; Azure
  uploads use the bounded signed API relay because Blob SAS cannot constrain
  request size. Managed asset and skill-document grants persist consumption
  state so confirmation is replay-safe and crash-idempotent, and the storage
  sweeper deletes expired unconfirmed objects and grant rows. For a clean local reset
  from the repository root, remove `apps/api/.local/storage` and re-upload
  development files; there is deliberately no compatibility read path.
- Non-OAuth integration credentials remain secret references. Admins replace
  API keys and service-account keys in place through
  `PUT /integrations/connections/{connection_id}/credential`; discovery
  validates the new version asynchronously. The local-only encrypted secret
  store uses `LOCAL_SECRET_STORE_PATH`, anchored to the API root and separate
  from `LOCAL_STORAGE_ROOT`. Application-managed secrets and externally
  provisioned references use the `workspaces/{workspace_id}/` namespace;
  unnamespaced legacy references may only be reused by the workspace of an
  existing connection. Production runtime identities must be able to create
  application-managed secret resources and manage their versions while
  remaining scoped to the provider's physical Praxis secret namespace.
- The runtime HTTP dependency is `httpx2`; plain `httpx` is dev-only.

## Auth And Request Handling

- Auth accepts the `session` cookie first, then `Authorization: Bearer`;
  internal HS256 JWTs authenticate scheduled runs and are pinned to their
  workspace.
- The active workspace resolves from the `X-Workspace` header via membership
  lookup; RBAC uses the `require_role`/`require_owner`/`require_editor`/
  `require_read` dependencies.
- CSRF is enforced when a session cookie is present (Origin check plus
  HMAC-signed `X-CSRF-Token`); rate limiting is Postgres-backed and
  fail-closed for auth flows. Do not widen exempt lists casually.
- OAuth login state is bound to the initiating browser with a short-lived,
  HttpOnly, host-only cookie. Keep that check at the API callback boundary.
- When `ARTIFACT_ORIGIN` is set, `ArtifactHostMiddleware` partitions routes by
  host: the artifact host serves only `/artifacts/view/*` and
  `/artifacts/shared/*`, and every other host refuses those paths.
- Preserve auditability for sensitive operations. Workspace, security,
  approval, credential, notification, and schedule flows should leave enough
  context to debug later.

## Tests

- Keep API tests organized by intent under `apps/api/tests`: `contract`,
  `routes`, `services`, `integration`, `integrations`, `middleware`,
  `scenarios`, and `utils`, with shared helpers in `factories/` and `support/`.
  Runtime behavior changes should add or update a deterministic
  `tests/scenarios/` case through the shared scenario helper. Do not add
  random root-level `test_*.py` files. Test key behavior and high-risk flows
  rather than creating one test file per route or service operation by
  default.
- Pytest is configured in `apps/api/pyproject.toml` with
  `asyncio_mode = "auto"`, so async test functions run without per-module
  markers.
- Database-backed tests run against a real Postgres and skip cleanly unless
  `TEST_DATABASE_URL` is set; `make api-test` provisions the local test
  database and sets that variable automatically. Use the fixtures in
  `conftest.py` and the helpers in `tests/factories/` and `tests/support/`
  instead of hand-rolling setup. Live LLM calls are blocked in tests.
- The shared database fixture runs ordinary test sessions under `praxis_app`.
  Multi-workspace fixtures must switch tenant context explicitly; use a
  maintenance session only when the behavior under test is intentionally
  cross-workspace or system-owned.
- Live-model behavior evaluations live outside pytest under `apps/api/evals`
  and run only through the explicit `make evals` target with `EVALS_MODEL`
  and matching provider credentials. The same command first runs live memory
  dedup calibration through the configured embedding provider, so its
  credential must also be available. These evals must never enter `make check`.

## Commands

```bash
cd apps/api
uv sync
uv run ruff check .
uv run ruff format --check .
uv run alembic check
uv run alembic upgrade heads
uv run pytest
# From the repository root, opt-in only:
EVALS_MODEL=openai:gpt-5.6-luna make evals
uv run uvicorn main:app --reload --port 8000 --no-access-log
```

`make api-test` (from the repo root) is the reliable way to run the full
database-backed suite locally.

## Migrations

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
