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
- `ai_usage_events` is runtime append-only: `praxis_app` may select and insert,
  but may not update or delete. Its exact cardinality is one row per logical
  agent-run invocation (including each approval resume), helper invocation, or
  embedding API batch; `requests` sums provider requests within that row.
  Successful/suspended agent usage is transactional with the terminal or parked
  transition. Failure/cancellation fallback and helper/embedding usage are
  best-effort durable writes through the separate bounded runtime-role AI usage
  pool, so metering cannot consume the normal pool's overflow capacity. Usage
  details must remain bounded, and the ledger must not become a budget or
  admission-enforcement mechanism.
- Workspace usage reads use the ordinary tenant runtime session, retain an
  explicit workspace predicate, and price UTC-day buckets before wider folds.
  The `/usage` router is owner/admin-only. Costs are read-time estimates from
  effective-dated public rates; unknown models remain unpriced. Native image
  helpers retain known model/quality/size metadata so GPT Image 2 and Gemini
  3.1 Flash Image output estimates are added to, not substituted for, mainline
  helper-model token cost. Unavailable image-model input remains disclosed
  rather than guessed.
- Platform usage reads are confined to `services/ai_usage/platform_queries.py`,
  use the sanctioned maintenance session, and set each transaction read-only
  before its first query. The `/platform-usage` router is super-admin-only;
  it exposes aggregate usage and workspace/user/model/purpose attribution but
  never workspace content. RLS remains unchanged.

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
- Code-mode execution lives under `services/agents/runtime/code_mode/` and
  uses the dedicated `core/settings/code_mode.py` mixin. Its lazily created
  Monty subprocess pool must close in API, worker, and test lifecycles. The
  sandbox has no OS handler or mount; nested calls are serial and must use the
  parent's prepared `ToolManager` so validation, approval, hooks, dispatch,
  and audit remain the framework-owned path. Durable nested approvals persist
  a version-stamped Monty snapshot in workspace-confidential run metadata.
  Bound the pre-base64 snapshot with `AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES` and
  the complete serialized artifact with `AGENT_CODE_MODE_STATE_MAX_BYTES`;
  suspension-only presentation evidence is trimmed oldest-first before an
  oversized artifact fails closed. A decision authorizes only the matching
  nested call and validated effective arguments. Captured print
  output is persisted cumulatively across suspensions, and every resume uses
  only the remaining output budget. Keep script arguments, nested results,
  final values, and print output independently bounded. Generated
  stubs render faithful input signatures and declared `output_model` return
  shapes; tools without a declared output model remain explicitly `Any`.
  Completed-run nested traces retain each complete normalized nested result as
  application-only presentation evidence, with no additional UI sampling or
  truncation. Suspended artifacts may omit the oldest presentation values only
  to meet the aggregate state ceiling, while retaining their trace summaries
  and explicit truncation markers. When a nested tool supplies a governed
  `public_result`, that richer value is the presentation evidence while only
  `return_value` enters the sandbox. That evidence must never enter model context. The governed
  nested-value and provider product bounds remain authoritative. Keep the 
  workflow's model-facing final-result bound materially tighter than the
  nested value bound so a faulty reduction cannot flood every later request.
- Tools that need richer transcript evidence than the model should receive may
  return `ToolReturn` with the bounded, output-model-validated payload in
  `return_value` and an explicitly safe `public_result` in metadata. The
  metadata is persisted and streamed to the application but is never sent to
  the model. Such tools must declare `max_public_result_chars`; dispatch makes
  the public value JSON-safe, redacts sensitive-key values, applies the same
  output model, and enforces that serialized budget. Keep provider-side fields
  bounded by the tool's product limits and exclude credentials or other
  application-only metadata at the source.
- Opaque tool targets use the runtime entity-reference contract. Internal
  resolvers stay under `services/agents/runtime/entity_references`; concrete
  provider reference models and resolvers stay in their provider package and
  publish only through the generic integrations seam. Scoped provider tools
  expose provider-owned scope/entity IDs only, resolve the provider scope to
  the canonical compatible active-context resource at execution, and target
  only that resource. Never serialize integration-resource or connection UUIDs
  in a scoped reference, bypass active-context resolution, or fan an entity ID
  out across compatible accounts.
- Approval overrides are governed by the server-owned field declarations:
  locked values cannot change, and entity values must be structured references
  that are reauthorized immediately before resume.
  Editable `records` fields also enforce their declared minimum row count and
  required columns before resume, even when the operator approves without edits.
  A `code_eligible=True` write backed by a provider batch operation must expose
  that operation as one bounded list-shaped call with a faithful editable
  presentation. The complete reviewed row set is the consent boundary; do not
  replace it with sequential single-row calls or workflow-scoped grants.
- Provider packages keep each agent tool in its own module under a `tools/`
  tree. The tree may share schemas and provider-local helpers, while its
  `__init__.py` only composes exported definitions; do not accumulate a
  provider's catalog in one `tools.py` module.
- Integration tools use the provider-neutral operation runtime under
  `services/integrations/`: context fan-out/targeting share one authorization
  and failure-isolation loop, `run_audited_integration_operation` derives
  external-write durability from the registered `RuntimeToolDefinition`, and
  `serialize_fan_out_results` owns the safe provider-key/scope outer envelope
  and never publishes internal resource or connection UUIDs. Providers
  return one `IntegrationAuditOutcome`, supply bounded pending detail for
  external writes, and subclass the shared result models only to narrow data.
  Every fixed integration tool declares an operation-specific output model;
  dynamic objects are limited to report/query rows and provider-defined record
  field values.
  Pending integration-operation evidence contains requested intent only;
  successful writes must return the one canonical terminal detail with exactly
  aligned intent outcomes and concrete provider effects. Intent and effect
  counts are validated independently. There is no schema-version compatibility
  layer. The runtime rejects caller-supplied tool names or context bindings
  that do not match the actually dispatched definition, and outcomes must be
  terminal. An unverified terminal outcome is persisted before the outer
  fan-out reports `unverified_mutation`.
  Do not add provider-local audit runners, durability booleans, denial
  callbacks, fan-out serializers, or copied outer result fields. A genuine
  one-request/many-context topology may retain a narrowly named adapter that
  delegates persistence to the shared runner.
- Every integration HTTP request declares its semantic transport policy as
  `read`, `idempotent_write`, or `mutation`; HTTP method and operation names
  never imply retry safety. Reads retain bounded retries. A mutation is never
  retried after an ambiguous attempt; only a received provider rejection, such
  as a 401 followed by credential refresh, can authorize a fresh attempt.
  Transport failures expose `not_dispatched`, `rejected`, or `ambiguous`
  disposition to the shared audit runner. Unknown mutation failures and
  in-flight cancellation are ambiguous, close correlated evidence as
  `unverified_mutation`, and must not be replayed automatically.
- Provider packages keep each entity resolver in its own module under an
  `entity_resolvers/` tree, with one module per entity kind. The package
  `__init__.py` only composes exported resolver definitions so provider
  manifests stay concise as their catalogs grow.
- Packaged integrations are Gmail, Google Ads, Airtable, BigQuery, and Google Analytics.
  BigQuery contributes service-account dataset discovery, a job-synchronized
  table-schema cache for enabled datasets (connection jobs fan out into
  independently retryable dataset jobs), two cache-backed schema tools, and a
  dry-run-gated SELECT query tool with active-dataset, routine, reference-count,
  byte, serialized-result, and row bounds. Query jobs bill through the service
  account's own project. BigQuery warehouse values are plain typed data under
  the operator-controlled database trust boundary.
  Google Analytics contributes workspace OAuth and service-account connection,
  a bearer-only Data/Admin REST client, and bounded Admin API discovery of
  read-only GA4 properties. Its five code-eligible read tools discover bounded
  standard/custom report fields, check which candidate fields can be added to a
  compatible standard report, and run structured standard or realtime reports
  with local request validation, header-typed metric values, and the shared
  report row bound, and list the Google Ads accounts linked to each selected
  property without exposing link creator email addresses. Standard reports also
  expose access-restriction and sampling metadata. Accounts remain property
  metadata, and discovery must not add per-property enrichment calls. Its OAuth
  settings stay in the provider package
  and use a Google Cloud client isolated from every other Google service.
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
- Provider-native `run_code` is a separate helper-model tool for heavy
  computation, create-from-text document generation, and declared append-only
  edits of existing workspace documents. It is an internal
  write, defaults to approval, never nests with `run_workflow`, and is offered
  only for configured OpenAI, Anthropic, or Google providers. Anthropic and
  OpenAI receive bounded current-revision bytes through the provider file
  bridge; Google receives bounded framed text or AnyDoc-derived Markdown.
  Generated text artifacts and governed Files persist directly. Retained File
  outputs land in one lazily created folder per conversation unless the tool
  names a folder explicitly; artifact-only runs create no folder. New Files
  receive a conversation reference, while declared edits retain the source
  file's existing folder and references. The dated provider-isolation
  probe record and re-probe policy live in `docs/architecture/governance.md`,
  not in the runtime module.
  Inner sandbox executions are audited even when the helper run fails
  (calls without a return part audit as incomplete failures), provider
  downloads stream into a buffer bounded by `NATIVE_RUN_CODE_MAX_OUTPUT_FILES`
  and `NATIVE_RUN_CODE_MAX_OUTPUT_BYTES`, provider-named outputs win hash
  dedup over synthetic inline names, and `NATIVE_RUN_CODE_TIMEOUT_SECONDS`
  bounds the whole invocation.
  Keep registry/orchestration in `native/run_code.py`, workspace-input transport
  and provider-file lifecycle in `native/run_code_file_bridge.py`, and bounded
  capture plus durable output persistence in `native/run_code_outputs.py`.
  Anthropic/OpenAI inputs upload once per invocation under deterministic,
  collision-free sandbox aliases (duplicate or normalized-colliding names get a
  ` (n)` suffix; the edit instruction names the exact alias) and delete
  best-effort in `finally`; provider ids and deletion outcomes persist only in
  one file-scoped audit event per upload, deliberately outside the tool-call
  roll-up so a failed deletion is never masked by the terminal tool event.
  Exclude mounted inputs
  from OpenAI container outputs by provider id before budgeting and by source
  hash as a defensive fallback. Declared edits append an agent-attributed
  revision only when capture yields exactly one output compatible with the
  source file format; the scripting model chooses its descriptive filename.
  Multiple compatible outputs fail closed as ambiguous. Retain the resolved
  input revision as the optimistic-concurrency boundary. Google stays on the
  bounded framed text/AnyDoc-Markdown read-only path. Contain helper `ModelAPIError`
  and direct Anthropic/OpenAI SDK `APIError` failures (the file bridge calls the
  SDKs outside Pydantic AI's wrapper) as safe tool failures after native-call
  auditing, provider-file cleanup, and usage recording so a provider outage
  cannot fail the parent agent run.
- User-facing workspace File links use the stable Markdown target
  `/files?fileId=<uuid>`. Runtime instructions require agents to use that target
  when a tool returns a File reference and forbid bare download labels.
- Native batch classification uses the code-eligible `classify` helper-tool
  path for OpenAI, Anthropic, and Google. It always uses a configured cheap
  helper independently from the calling agent, accepts up to 500 items per
  tool call, and processes them sequentially in batches of at most 100. It
  meters one ledger row per helper invocation, frames items as untrusted data,
  and accepts only ordered labels from the caller's closed set. Public results
  pair each label with the exact server-copied input `value`; the helper never
  authors that free-text field. Keep its public item, label, instruction, and
  helper-step bounds settings-owned; the internal 100-item batch size stays a
  runtime constant. Adding helper-authored rationale or confidence output
  reopens the trust decision.
- Workspace classifiers are the first producer of generic workspace-defined
  runtime tools. Active rows are loaded for each run and synthesized as
  `classifier_{name}(items)` definitions without mutating the process-global
  registry; the ad-hoc `classify(items, labels, instructions, ...)` tool remains
  available independently. A future family adds its own table/CRUD surface and
  producer, reserves a unique prefix in `workspace_tools.py`, and contributes
  one call to the aggregation loader. Workspace-defined names are unavailable
  through the static tool-availability route, accept no per-call override of
  stored configuration, and row changes take effect when the next run loads
  definitions.
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
- Audit roll-up correlation is materialized in trigger-owned
  `audit_rollup_run_id` and `audit_rollup_tool_call_id` columns. The trigger
  derives the run ID from `details`, uses `resource_id` for tool calls and
  `details.tool_call_id` for integration-resource events, and leaves incomplete
  or unrelated identities outside the partial composite index. Writers must not
  treat those columns as inputs or weaken the `(workspace_id, run_id,
  tool_call_id)` lookup contract.
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
  sweeper deletes expired unconfirmed objects and grant rows. File-folder
  deletion remains synchronous only for at most 100 live files; reject larger
  folders before locking their files, and keep the folder-level audit's file ID
  sample bounded while per-file deletion events retain the complete audit trail.
  For a clean local reset from the repository root, remove
  `apps/api/.local/storage` and re-upload development files; there is deliberately
  no compatibility read path.
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
  HMAC-signed `X-CSRF-Token`). Rate limiting is Postgres-backed and
  fail-closed for auth flows: general requests consume minute and hour
  budgets; login failures consume a client-IP-and-account budget while
  successful logins don't; pre-account TOTP and OAuth failures use separate
  per-flow IP buckets that don't block requests with a resolved account;
  registration and password reset remain per IP.
  Trust forwarded client IPs only from `TRUSTED_PROXY_CIDRS`. Keep Argon2
  work on the async `User` helpers so it runs outside the event loop. Do not
  widen exempt lists casually.
- OAuth login state is bound to the initiating browser with a short-lived,
  HttpOnly, host-only cookie. Keep that check at the API callback boundary.
- Workspace invitations are delivered only through the operator-shared link;
  neither email nor in-app notification delivery exists yet. A pending,
  unexpired invitation permits account creation while `ALLOW_SIGNUP=false`:
  OAuth matches a provider-verified email (Google, GitHub's verified-email
  result, or Microsoft UPN), while password registration requires the raw
  invitation token. Full OAuth sign-in auto-accepts matching invitations.
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
