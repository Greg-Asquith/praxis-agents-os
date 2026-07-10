# Plan 037: Integration core models, credential service, and secret references

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md` and flip the governance cells listed in
> "Done criteria" in `docs/architecture/governance.md`.
>
> **Governance pre-flight (run before Step 1)**: this plan implements slices
> of `docs/architecture/governance.md` (§1 role matrix, §3 credentials
> retention, §4 Retry-After retries, §5 secrets operating model). Re-read
> those sections before coding; the note wins over this plan. If any cited
> default has changed since `0cbbb39`, reconcile before proceeding.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/models/ apps/api/core/settings/ apps/api/core/exceptions/integration.py apps/api/utils/security.py apps/api/services/audit_events/enums.py apps/api/services/storage/ apps/api/alembic/versions/core/ apps/api/pyproject.toml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

> **Amendment (2026-07-07, plan 061 — provider packaging)**: this plan now
> also lands the packaging seams from
> `docs/architecture/integration-packaging.md` (the note wins over this
> plan where they diverge):
>
> 1. Engine scope gains `services/integrations/plugin.py`
>    (`IntegrationProviderPlugin`: manifest + `discover_resources` +
>    `tool_definitions`) and `services/integrations/loader.py`
>    (imports `integrations.{key}` for each entry in the new
>    `INTEGRATIONS_ENABLED_PROVIDERS: list[str] = []` setting, validates
>    the note's §4.3 invariants, fail-fast at boot, registers manifests
>    and tools into the existing singular registries).
> 2. `services/integrations/manifest.py` becomes contract + registration
>    only — **no hardcoded provider entries**. Decision 6's four entries
>    become packages under `apps/api/integrations/`: `fake/` (full, the
>    contract fake from decision 7 — `providers/fake.py` is superseded by
>    `integrations/fake/`), and `gmail/`, `google_ads/`, `airtable/` as
>    manifest-data-only packages (empty `tool_definitions`; 041 fills
>    them). The settings validator rejects `"fake"` in the enabled list
>    outside `ENVIRONMENT=local` (replaces
>    `INTEGRATIONS_FAKE_PROVIDER_ENABLED` — drop that setting).
> 3. The manifest smoke command becomes loader-driven and runs with all
>    four packages enabled locally; with the default empty list it prints
>    `[]` — both expectations get tests.
> 4. `build_runtime_tools` goes lenient on catalog-absent saved tool
>    names per the note §4.7 (skip + log + run metadata, not
>    `ModelConfigurationError`); write-time validation stays strict.
> 5. Import laws per note §4.6, pinned by a new AST-walking test
>    `tests/integrations/test_import_laws.py`; provider-package tests
>    live under `tests/integrations/<key>/`.

> **Amendment (2026-07-07, plan 068 — credential encryption posture)**:
> this amendment wins over decision 3's key sourcing, the Step 5
> fingerprint recipe, and the key-rotation maintenance note where they
> diverge:
>
> 1. **Dedicated credential root key, sourced through the secrets
>    provider.** OAuth token columns are NOT encrypted with the app-wide
>    `ENCRYPTION_KEY`. Outside `ENVIRONMENT=local`, the root key
>    material resolves at first use through `services/secrets`
>    (reference name from a new setting
>    `CREDENTIAL_MASTER_KEY_SECRET_NAME`, default
>    `credential-master-key`, version `latest`); the new env setting
>    `CREDENTIAL_MASTER_KEYS` (comma-separated Fernet keys, newest
>    first — the secret value uses the same format) is a local-only
>    fallback, rejected outside local by the Step 1 validator (same law
>    as `SECRET_PROVIDER=local`). Resolution is an async cached
>    accessor — once per process, never at import time.
> 2. **HKDF purpose subkeys.** Add `derive_purpose_key(root: bytes,
>    purpose: str) -> bytes` (HKDF-SHA256; `cryptography` is already a
>    dep) to `utils/security.py`. Token columns encrypt/decrypt through
>    a `MultiFernet` over keys derived with purpose
>    `praxis:credential-tokens:v1` (one per root key, newest first;
>    Fernet key = urlsafe-b64 of the 32-byte HKDF output).
>    `compute_principal_fingerprint` keys its HMAC with the newest key
>    derived with purpose `praxis:principal-fingerprint:v1` — NOT
>    `SECRET_KEY`. The encrypt/decrypt property pairs on
>    `ExternalCredential` route through this seam instead of
>    `encrypt_data`/`decrypt_data`; `UserAuth`/TOTP stay on
>    `ENCRYPTION_KEY` unchanged.
> 3. **`encryption_key_id` column.** Table 1 gains `encryption_key_id`
>    String(16) nullable — the first 16 hex chars of SHA-256 over the
>    root key string that encrypted the row; null when both token
>    columns are null. `store_oauth_credential`, every refresh, and
>    `crypto_shred` keep it accurate. Rotation progress is thereby a
>    SQL query, not a guess.
> 4. **Re-encryption sweep job.** Register job kind
>    `integrations.rotate_credential_encryption` on the plan-030 jobs
>    harness (DONE) — an explicit exception to this plan's "no job
>    handlers" out-of-scope line. It walks live `external_credentials`
>    rows whose `encryption_key_id` differs from the newest root key
>    id, re-encrypts under the newest key with per-row
>    `SELECT ... FOR UPDATE` (the `ensure_fresh_credential` lock
>    discipline), and restamps the id. Enqueued manually (document the
>    command); no schedule. One summary audit event (`UPDATE` on
>    `INTEGRATION_CREDENTIAL`, count-only details). Fingerprints are
>    NOT recomputed — the plaintext principal id is not stored; on root
>    rotation, dedup detection degrades gracefully for pre-rotation
>    rows and heals at reconnect. Replace the maintenance note's
>    `SECRET_KEY`-orphaning sentence with this posture.
> 5. **Tests and done criteria grow**: after a sweep, every live row
>    decrypts with ONLY the newest key (old keys droppable — proven
>    with a two-key fixture); fingerprints are unchanged by a
>    `SECRET_KEY` change; the local-only `CREDENTIAL_MASTER_KEYS`
>    fallback is rejected outside local. Add done criteria: "sweep
>    leaves no live row with a stale `encryption_key_id`" and "grep
>    confirms no code under `services/integrations/` or
>    `services/secrets/` reads `settings.ENCRYPTION_KEY` or signs with
>    raw `SECRET_KEY`".
> 6. Full envelope encryption (per-credential DEKs wrapped by a KMS
>    KEK) is the recorded end-state with revisit triggers in plan 068 —
>    do not build it here.

> **Amendment (2026-07-07, plan 077 — inbound integration events)**: per
> `docs/architecture/integration-events.md`, reserve the event seams —
> nothing here implements events:
>
> 1. **Manifest field.** `IntegrationProviderManifest` gains
>    `event_delivery: Literal["none", "webhook", "pubsub_push"] =
>    "none"` (data only; the loader and plugin contract are unchanged).
>    Decision 6's entries set gmail `"pubsub_push"`, airtable
>    `"webhook"`, google_ads `"none"`, fake `"none"` (041 flips fake to
>    a synthetic value when its test harness needs one).
> 2. **Webhook secrets ride the existing seams.** Per-webhook MAC
>    secrets are `services/secrets` references named
>    `integrations/{provider_key}/{connection_id}/webhook/{webhook_id}`
>    — no new column, table, or encryption mechanism (the plan-068
>    posture is unaffected). Note this in the credential service's
>    docstring so the implementing plan finds one seam, not two.
> 3. **`integration_events` is a reserved table decision, not scope.**
>    The note §4 fixes its shape (plain rows, dedup unique index,
>    bounded payload); the migration lands with the first event
>    implementation plan, on the core branch. Do not create it here —
>    but do not claim its name for anything else either.

## Status

- **Priority**: P1
- **Effort**: L (the largest of the three Phase 4a foundation plans)
- **Risk**: HIGH (credential storage, encryption, and the production secrets
  posture — mistakes here are security incidents, not bugs)
- **Depends on**: 029 (DONE — `docs/architecture/governance.md` exists).
  Soft: 030 (no code dependency here; the `integration_discovery_runs` table
  is created now but only written by 039, which rides the 030 harness).
  Does NOT depend on 031–036.
- **Category**: Phase 4a integrations, Gate G3 satisfied (roadmap
  `000_MASTER_ROADMAP.md` §4 Phase 4a row 037; donor `DONOR_PORT_ROADMAP.md`
  §4.2 / §6 row C1; decisions D3, D4, D5)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Full multi-connection per provider (roadmap D3).** There is NO
   one-active-per-provider-per-owner unique index anywhere in this schema —
   deliberately, against the donor design (`DONOR_PORT_ROADMAP.md` §4.2 says
   "one active connection per provider per owner via partial unique index";
   D3 overrides it). Every connection carries a **required, non-empty,
   user-set `label`** (CHECK-enforced). Duplicate detection of the same
   external principal across connections is a **warning surface via the
   HMAC principal fingerprint, never a block**.
2. **Owner is user XOR workspace, CHECK-enforced.** `owner_user_id` XOR
   `owner_workspace_id` via `num_nonnulls(...) = 1`. User-owned connections
   (Gmail per D4) are personal and not pinned to one workspace; the acting
   workspace for RBAC and audit comes from the request context (038), and
   per-workspace resolution is plan 040's active-context job. Workspace-owned
   connections (Google Ads per D4) are shared per governance §1.
3. **Only OAuth tokens are stored in Postgres, Fernet-encrypted** — the
   exact `UserAuth` precedent (`models/user.py:352-389`): `*_encrypted` Text
   columns plus encrypt/decrypt property pairs over
   `utils/security.py::encrypt_data/decrypt_data`. Everything non-OAuth is a
   secret **reference** `{provider, name, version}` resolved at call time
   (governance §5). **Revoke = crypto-shred**: null both token columns, stamp
   `revoked_at`, keep the metadata row (governance §3 credentials row); the
   30-day hard delete is 039's sweep kind, recorded there.
4. **Secrets provider abstraction mirrors storage.** New `services/secrets/`
   package with a `SecretsProvider` Protocol (shape of
   `services/storage/provider.py:13`), a factory singleton (shape of
   `services/storage/factory.py:22`), a **local provider** (env-var read
   plus a Fernet-encrypted `.local/` file store so the 038 api-key connect
   flow can write locally), and **GCP Secret Manager** as the first real
   provider behind a new optional extra. The existing, entirely unconsumed
   `SECRET_PROVIDER` setting (`core/settings/providers.py:16-19`; its only
   other mention is a docstring, `services/agents/models/utils.py:4-9`) is
   **narrowed** to `Literal["local", "gcp_secret_manager"]` — the dead
   `"secret_manager"`/`"key_value"` values go away while nothing reads them.
5. **Production-safety validation per governance §5**: the `model_validator`
   in `core/settings/__init__.py:51` gains two rules mirroring the
   local_fs/console gating at lines 60-64: `SECRET_PROVIDER == "local"` is
   only allowed when `ENVIRONMENT == "local"`, and
   `SECRET_PROVIDER == "gcp_secret_manager"` requires a non-empty
   `GCP_PROJECT_ID` (`core/settings/gcp.py:10`). Outside local there is no
   third option, so prod requires the real secret manager by construction.
6. **Declarative provider manifest with import-time invariant checks** —
   the plan 025 registry shape
   (`services/agents/runtime/tools/registry.py:33-91`, duplicate-name
   `RuntimeError` at 86-88). One frozen dataclass per provider: auth modes,
   owner scope, OAuth scopes, resource types, discovery flag, required form
   fields, capability flags, env gating. Ships **four entries**: `fake`
   (below), plus `gmail`, `google_ads`, `airtable` as **data only** per D4 —
   their operations, clients, and registry tools are plan 041's scope, and
   all three are env-gated off by default.
7. **A `fake` provider is part of the contract, not a test hack.** It backs
   the state machine end to end without real OAuth: in-process token
   issuance/refresh/revoke and configurable discovery results, enabled only
   via `INTEGRATIONS_FAKE_PROVIDER_ENABLED` which the settings validator
   rejects outside `ENVIRONMENT=local` (same law as local_fs storage). 038
   and 039 test against it; it never ships enabled in prod.
8. **Locked proactive refresh.** `ensure_fresh_credential` refreshes when
   `token_expires_at - now < INTEGRATIONS_TOKEN_REFRESH_LEEWAY_SECONDS`
   (default 120, inside the donor's 60–180 s band), serialized per
   credential row with `SELECT ... FOR UPDATE` and a re-read after acquiring
   the lock (rotating refresh tokens die if double-refreshed — the invariant
   is pinned by a two-session test). A refresh-token failure (4xx from the
   token endpoint) flips the connection to `needs_reauth` and audits; the §6
   notification to the connecting user is deliberately deferred to 039
   (governance §6 names 039 as the emitting plan).
9. **Retry-After-aware bounded retries on `httpx2`** (governance §4 row
   "Integration API retries — 037"). New `services/integrations/http.py`
   helper modeled on `OAuthProviderWithRetry._make_request`
   (`core/auth/oauth_providers/retrying.py:51-135`), extended to honor a
   `Retry-After` header (seconds and HTTP-date forms) capped by settings.
   We do NOT reuse `retrying_http_client()`
   (`services/agents/models/utils.py:41-65`): it is plain-`httpx` (a
   pydantic-ai transport), lru-cached process-wide, and tuned by LLM_*
   settings — the runtime HTTP dep for our own calls is `httpx2`
   (AGENTS.md; `pyproject.toml:14`). The seam divergence is documented in
   the module docstring.
10. **Audit vocabulary grows four members**: `AuditResourceType` gains
    `INTEGRATION_CONNECTION`, `INTEGRATION_CREDENTIAL`,
    `INTEGRATION_RESOURCE`, `SECRET_REFERENCE`
    (`services/audit_events/enums.py:25-41` has none of these). Every token
    issuance, refresh, refresh failure, revoke, and secret-reference
    create/update/delete is audited; secret **resolve failures** are audited,
    successful resolves are not (too noisy), and no audit detail ever
    contains a secret value (governance §5).
11. **All four tables land in one core migration now**, including
    `integration_discovery_runs`, which only 039 writes — one migration
    beats three dribbles, and the table shape is fixed by the donor design.
    Discovery-run rows are **plain** (`Base + UUIDMixin + TimestampMixin`,
    the `models/rate_limiting.py:16` composition) — governance §3 lists them
    as "plain rows, 90 d"; soft-delete columns on an append-mostly log are
    dead weight. Credentials, connections, and resources use `BaseModel`
    (soft delete) because §3 gives them soft-then-hard lifecycles.
12. **Status-machine vocabulary and the transition guard live here**
    (`services/integrations/domain.py` + `transition_connection_status`
    service op) so 038 and 039 share one enforcement point; discovery-driven
    transitions (`needs_resource_selection` computed from enabled resources)
    are wired by 039.

## Why this matters

Integrations are the platform's first credential-bearing subsystem and the
donor's strongest design (`DONOR_PORT_ROADMAP.md` §4.2). Everything after
this in Phase 4a stacks on these tables: 038's OAuth flows write
credentials and connections, 039's discovery writes resources and
discovery runs, 040 resolves active context across N connections (D3), 041
executes provider operations through the credential service, and 042 renders
it all. Getting the schema, encryption, and secrets posture right now is
cheap; retrofitting fingerprints, XOR ownership, or references-only secrets
after rows exist is a data migration with security implications. This plan
also lands the platform-wide secrets provider that governance §5 requires
before production carries any customer credential.

## Current state

All anchors verified at `0cbbb39`. Nothing integration-shaped exists beyond
the exception layer; there is no `services/integrations/`, no
`services/secrets/`, and no `integration_*` or `external_credentials` table.

- `apps/api/core/exceptions/integration.py` — the full RFC 7807 hierarchy
  already exists and is wired into the handlers
  (`core/exceptions/exception_handlers.py:30,53`). Build against it, do not
  extend it casually: `IntegrationError` base (lines 14-88) carrying
  `provider_key`/`connection_id`/`operation`/`original_error` context and
  `to_problem_details()` (63-88); subclasses `IntegrationConnectionError`
  (400, line 91), `IntegrationAuthError` (401, line 98),
  `IntegrationRateLimitError` (429, line 105), `IntegrationTimeoutError`
  (504, line 112), `IntegrationNotFoundError` (404, line 119),
  `IntegrationValidationError` (400, line 126),
  `IntegrationPermissionError` (403, line 133).
- Encryption precedent: `apps/api/utils/security.py` — Fernet
  `encrypt_data`/`decrypt_data` with a key-rotation list (lines 31-34,
  103-158), `create_hmac_signature`/`verify_hmac_signature` (204-231),
  `hash_token` (69-81). `ENCRYPTION_KEY` is validated as a Fernet key at
  settings load (`core/settings/security.py:85-94`); `SECRET_KEY` min length
  32 (`core/settings/security.py:16`).
- Encrypted-token model precedent: `apps/api/models/user.py` `UserAuth`
  (344-397): `access_token_encrypted`/`refresh_token_encrypted` Text columns
  (352-353) with encrypt/decrypt property pairs (361-389) and
  `is_token_expired` (392-397). TOTP secrets use the same seam
  (`models/user.py:73,167-179`).
- Settings: mixins compose in `core/settings/__init__.py:30-46`; the
  production-safety `model_validator` is lines 51-123 with the local-only
  gating precedent at 60-64 (`local_fs`, `console`).
  `SECRET_PROVIDER: Literal["local", "secret_manager", "key_value"]` exists,
  default `"local"`, at `core/settings/providers.py:16-19` — **zero code
  consumers** (the only other hit is the docstring at
  `services/agents/models/utils.py:4-9`), so narrowing it is safe.
  `GCP_PROJECT_ID` exists (`core/settings/gcp.py:10`).
- Provider-ABC precedent: `services/storage/provider.py:13-89`
  (`@runtime_checkable` Protocol with `provider_key` + async ops);
  factory singleton with double-checked lock
  (`services/storage/factory.py:22-51`); optional extras per cloud provider
  (`pyproject.toml:27-30`: `azure`, `gcs`, `s3`).
- HTTP: `httpx2>=2.5.0` is the runtime dep (`pyproject.toml:14`);
  `cryptography>=49` (line 11), `pyjwt>=2.13` (line 20). The OAuth retry
  precedent is `core/auth/oauth_providers/retrying.py:51-135` (bounded
  attempts, exponential backoff, 4xx→typed auth error, 5xx/network→retry) —
  it does NOT honor `Retry-After`. The LLM transport
  (`services/agents/models/utils.py:41-65`) does, via pydantic-ai's
  `wait_retry_after`, but on plain `httpx` — see decision 9.
- Import-time registry invariants precedent:
  `services/agents/runtime/tools/registry.py:33-91` (`validate_definition`
  then duplicate-name `RuntimeError` at 86-88; provider modules imported for
  side effects at 254-258).
- Model conventions: `models/base.py` — `BaseModel` (130-138, soft delete),
  `UUIDMixin` (18-21), `TimestampMixin` (24-30), `CreatedAtMixin` (124-127);
  non-soft-delete composition precedent `models/rate_limiting.py:16`.
  CHECK-constraint + partial-index precedent: `models/agent.py:222-273`
  (status CHECK 223-229, partial unique indexes 255-272). New models must be
  imported in `models/__init__.py` (registry comment, lines 1-12).
- Migrations: core head is `core_0008`
  (`alembic/versions/core/0008_add_conversation_todos.py:15`). Plans 030
  (jobs) and 031/032 (files) are ordered before this plan and will add core
  migrations; expect the real head at execution to be ≥ `core_0009` — this
  plan calls its migration `core_00NN` and the number is fixed at execution
  (STOP condition below). D5: core branch.
- Audit: `services/audit_events/enums.py` — `AuditAction` (13-22),
  `AuditResourceType` (25-41, no integration members), `AuditActorType`
  (43-49), `AuditStatus` (52-58). Audit FKs survive subject deletion
  (`models/audit_event.py:19,37,44`, per governance §3).
- Tests: `tests/support/settings.py::configure_test_environment` sets safe
  env defaults including a generated `ENCRYPTION_KEY` (lines 10-25);
  DB-backed tests gate on `TEST_DATABASE_URL` via `conftest.py` fixtures and
  skip cleanly without it; factories live in `tests/factories/` (users,
  workspaces, sessions, skills).
- Governance anchors this plan implements: §1 rows "View credential
  metadata (037/042)" and "Enter API keys / secret references (037)"
  (admin+); §3 credentials row ("revoke = soft; 30 d after revoke; tokens
  crypto-shredded at revoke; audit metadata only, never values"); §4 row
  "Integration API retries — Retry-After-aware, bounded attempts — 037";
  all of §5.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Settings smoke | `uv run python -c "from core.settings import settings; print(settings.SECRET_PROVIDER)"` | `local` |
| Migration sanity | `uv run alembic check` | no pending operations after Step 3 |
| Apply migration | `uv run alembic upgrade heads` | four tables created |
| Downgrade round-trip | `uv run alembic downgrade core@-1 && uv run alembic upgrade heads` | clean |
| Manifest smoke | `uv run python -c "from services.integrations.manifest import PROVIDER_MANIFESTS; print(sorted(PROVIDER_MANIFESTS))"` | `['airtable', 'fake', 'gmail', 'google_ads']` |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/integrations tests/services/secrets -q` | all pass |
| Full API tests | `TEST_DATABASE_URL=... uv run pytest -q` | all pass |

## Scope

**In scope:**

- `apps/api/models/integrations.py` (create — four models) +
  `apps/api/models/__init__.py` (register imports)
- `apps/api/alembic/versions/core/00NN_*.py` (create — core branch, D5)
- `apps/api/core/settings/integrations.py` (create —
  `IntegrationsSettingsMixin`), `core/settings/providers.py` (narrow
  `SECRET_PROVIDER` Literal), `core/settings/__init__.py` (compose mixin +
  extend the production-safety validator per decision 5)
- `apps/api/services/secrets/` (create): `__init__.py`, `domain.py`,
  `provider.py`, `factory.py`, `resolve_secret.py`, `write_secret.py`,
  `providers/__init__.py`, `providers/local.py`,
  `providers/gcp_secret_manager.py`, `utils.py`
- `apps/api/services/integrations/` (create): `__init__.py`, `domain.py`,
  `manifest.py`, `http.py`, `utils.py`,
  `credentials/__init__.py`, `credentials/store_oauth_credential.py`,
  `credentials/ensure_fresh_credential.py`,
  `credentials/revoke_credential.py`,
  `credentials/store_secret_reference_credential.py`,
  `credentials/find_duplicate_principals.py`,
  `connections/__init__.py`, `connections/transition_connection_status.py`,
  `providers/__init__.py`, `providers/fake.py`
- `apps/api/services/audit_events/enums.py` (add four
  `AuditResourceType` members)
- `apps/api/pyproject.toml` (add optional extra
  `gcp-secrets = ["google-cloud-secret-manager>=2.20"]`)
- `apps/api/tests/services/integrations/` and
  `apps/api/tests/services/secrets/` (create),
  `apps/api/tests/factories/integrations.py` (create)

**Out of scope (do NOT touch):**

- HTTP routes of any kind — 038 owns `routes/integrations/`. This plan has
  **no public surface**; per AGENTS.md, that is documented here as pending.
- Discovery execution, job handlers, sweeps, and notifications — 039
  (governance §6 explicitly names 039 for `needs_reauth`/discovery-failure
  notifications; this plan only sets status + audit).
- Active context and `RuntimeDeps` injection — 040.
- Real provider operations, API clients beyond the fake provider, and
  registry tools — 041 (Gate G1 applies there, not here).
- UI — 042.
- Swapping the LLM `provider_api_key` seam
  (`services/agents/models/utils.py:68-83`) onto the secrets provider — its
  docstring anticipates this; do it in a later hardening pass, not here.
- `services/auth/**` and `core/auth/oauth_providers/**` — the login OAuth
  stack is untouched; 038 reuses its *patterns*, not its code.

## Git workflow

- Branch: `advisor/037-integration-core-models-credentials`
- Commit style: `API - Integration Core Models & Credentials`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

Create `core/settings/integrations.py` with `IntegrationsSettingsMixin`
(shape of `AgentRunSettingsMixin`, `core/settings/agents.py`):

```python
INTEGRATIONS_TOKEN_REFRESH_LEEWAY_SECONDS: int = 120   # proactive refresh window (60-180 band, decision 8)
INTEGRATIONS_HTTP_TIMEOUT_SECONDS: float = 30.0        # per-request timeout
INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS: int = 3          # bounded attempts (governance §4)
INTEGRATIONS_HTTP_RETRY_BACKOFF_FACTOR: float = 0.5    # fallback exponential backoff
INTEGRATIONS_HTTP_RETRY_AFTER_CAP_SECONDS: int = 60    # Retry-After honored up to this cap
INTEGRATIONS_FAKE_PROVIDER_ENABLED: bool = False       # decision 7; local-only (validator)
INTEGRATIONS_AIRTABLE_ENABLED: bool = False            # manifest env gate (D4; ops are 041)
```

All numeric fields `Field(..., gt=0, description=...)`. In
`core/settings/providers.py` narrow the Literal:
`SECRET_PROVIDER: Literal["local", "gcp_secret_manager"]`, default
`"local"` (decision 4 — verified zero consumers). Compose the mixin into
`Settings` in `core/settings/__init__.py` and extend
`validate_runtime_provider_config` (lines 51-123), mirroring the
local_fs/console pattern at 60-64:

```python
if self.SECRET_PROVIDER == "local" and self.ENVIRONMENT != "local":
    raise ValueError("SECRET_PROVIDER=local is only allowed when ENVIRONMENT=local")
if self.SECRET_PROVIDER == "gcp_secret_manager" and not (self.GCP_PROJECT_ID or "").strip():
    raise ValueError("SECRET_PROVIDER=gcp_secret_manager requires GCP_PROJECT_ID")
if self.INTEGRATIONS_FAKE_PROVIDER_ENABLED and self.ENVIRONMENT != "local":
    raise ValueError("INTEGRATIONS_FAKE_PROVIDER_ENABLED is only allowed when ENVIRONMENT=local")
```

Add `SECRET_PROVIDER=local` awareness to
`tests/support/settings.py::configure_test_environment` only if the default
does not already satisfy tests (it should — default is `local` and tests set
`ENVIRONMENT=local`).

**Verify**:
`uv run python -c "from core.settings import settings; print(settings.INTEGRATIONS_TOKEN_REFRESH_LEEWAY_SECONDS)"`
→ `120`; a non-DB unit test (Step 7) pins the three new validator rejections;
`uv run ruff check .` → exit 0.

### Step 2: Secrets provider abstraction (`services/secrets/`)

`domain.py`: frozen dataclass `SecretReference(provider: str, name: str,
version: str)` with `def render(self) -> str` returning
`"{provider}:{name}#{version}"` for audit details (reference identity only,
never values), and a `SECRET_NAME_PATTERN = ^[a-zA-Z0-9_\-]{1,255}$`
validation helper. Names are caller-namespaced; the 038 api-key flow will
use `integrations/{provider_key}/{connection_id}` normalized to this
pattern.

`provider.py`: `@runtime_checkable` Protocol `SecretsProvider` (mirror
`services/storage/provider.py:13-89`):

```python
class SecretsProvider(Protocol):
    provider_key: str
    async def resolve_secret(self, ref: SecretReference) -> str: ...
    async def write_secret(self, name: str, value: str) -> SecretReference: ...  # new version each call (rotation, §5)
    async def delete_secret(self, ref: SecretReference) -> bool: ...
```

`providers/local.py` — `LocalSecretsProvider` (`provider_key = "local"`),
LOCAL-ONLY (gated in Step 1's validator):

- `resolve_secret`: if `name` matches an environment variable
  `SECRET_{NAME_UPPERCASED}` return it (version `"env"`); otherwise read the
  Fernet-encrypted JSON store at `{LOCAL_STORAGE_ROOT}/../secrets.enc.json`
  (i.e. a sibling of the `local_fs` root, reusing
  `settings.LOCAL_STORAGE_ROOT`, `core/settings/providers.py:28`), decrypted
  with `utils/security.py::decrypt_data`.
- `write_secret`: append `{name: {version_n: value}}` into that encrypted
  file (version = zero-padded counter), return the reference. This exists so
  the 038 api-key connect flow works in local dev without GCP.
- Missing secret → raise `IntegrationAuthError` from `core/exceptions/
  integration.py` with `operation="resolve_secret"` — typed, RFC 7807, and
  the audit hook (below) records the failure.

`providers/gcp_secret_manager.py` — `GcpSecretManagerProvider`
(`provider_key = "gcp_secret_manager"`), imports
`google.cloud.secretmanager` lazily inside methods (optional-extra pattern —
check how `services/storage/providers/gcs.py` guards its import and copy
that shape). `resolve_secret` → `access_secret_version` on
`projects/{GCP_PROJECT_ID}/secrets/{name}/versions/{version}` (`"latest"`
allowed); `write_secret` → create-secret-if-missing + `add_secret_version`,
returning the new version id. Add the `gcp-secrets` optional extra to
`pyproject.toml` next to `gcs` (line 29).

`factory.py`: `get_secrets_provider()` singleton with the storage factory's
double-checked-lock shape (`services/storage/factory.py:22-51`), keyed on
`settings.SECRET_PROVIDER`.

`resolve_secret.py` / `write_secret.py` (service ops, one per file): thin
wrappers that call the provider and write audit rows per governance §5 —
`write_secret` audits `AuditAction.CREATE` on
`AuditResourceType.SECRET_REFERENCE` with `details={"reference": ref.render()}`;
`resolve_secret` audits ONLY on failure (`AuditStatus.FAILURE`, never the
value, never on success). `__init__.py` re-exports the two ops only
(AGENTS.md service-package rule).

**Verify**: `uv run ruff check .` → exit 0; the package imports without the
GCP extra installed
(`uv run python -c "from services.secrets import resolve_secret"` → no
ImportError); Step 7 tests pin env-var resolution, file write/read
round-trip, and the missing-secret failure audit.

### Step 3: Models + core migration

Create `models/integrations.py`. Table 1 — `ExternalCredential(BaseModel)`,
`__tablename__ = "external_credentials"`:

- `provider_key` String(64) not null, indexed
- `auth_mode` String(32) not null, CHECK in
  `('oauth', 'api_key', 'service_account', 'system_token')` (manifest modes;
  v1 uses the first two, D4)
- OAuth payload (encrypted at rest, decision 3):
  `access_token_encrypted` Text nullable, `refresh_token_encrypted` Text
  nullable, `token_expires_at` DateTime(tz) nullable, `token_type`
  String(32) nullable, `granted_scopes` JSONB nullable (038 writes it
  already filtered to requested scopes)
- Secret reference (non-OAuth modes, §5): `secret_provider` String(32)
  nullable, `secret_name` String(255) nullable, `secret_version` String(64)
  nullable
- `principal_fingerprint` String(64) not null, **indexed non-unique**
  (D3 — dedup is detection, not constraint): HMAC-SHA256 hex over
  `"{provider_key}:{external_principal_id}"` keyed with `SECRET_KEY`
  (via `utils/security.py::create_hmac_signature`, line 204)
- `external_principal_label` String(255) nullable (display identity — email
  address, MCC name; never a secret)
- Refresh bookkeeping: `last_refreshed_at` DateTime(tz) nullable,
  `refresh_failure_count` Integer not null server_default `0`,
  `last_refresh_error_code` String(64) nullable
- `revoked_at` DateTime(tz) nullable
- CHECK `ck_external_credentials_mode_payload`:
  `(auth_mode = 'oauth' AND secret_name IS NULL) OR (auth_mode <> 'oauth'
  AND access_token_encrypted IS NULL AND refresh_token_encrypted IS NULL
  AND secret_name IS NOT NULL AND secret_provider IS NOT NULL)`
- Encrypt/decrypt property pairs `access_token`/`refresh_token` exactly as
  `models/user.py:361-389`, plus `def crypto_shred(self)` nulling both
  encrypted columns and stamping `revoked_at`.

Table 2 — `IntegrationConnection(BaseModel)`,
`__tablename__ = "integration_connections"`:

- `provider_key` String(64) not null, indexed
- `label` String(120) not null, CHECK
  `char_length(btrim(label)) > 0` named
  `ck_integration_connections_label_not_blank` (D3 required label)
- `owner_user_id` UUID FK `users.id` nullable; `owner_workspace_id` UUID FK
  `workspaces.id` nullable; CHECK
  `num_nonnulls(owner_user_id, owner_workspace_id) = 1` named
  `ck_integration_connections_owner_xor` (decision 2)
- `credential_id` UUID FK `external_credentials.id` not null; partial unique
  index `uq_integration_connections_credential` on `(credential_id)
  WHERE deleted = false` (one live connection per credential row; reconnect
  swaps in a fresh credential)
- `status` String(32) not null server_default `'auth_pending'`, CHECK in
  `('auth_pending', 'discovery_pending', 'needs_resource_selection',
  'active', 'degraded', 'error', 'revoked', 'needs_reauth')`
- `status_reason` Text nullable; `status_changed_at` DateTime(tz) nullable
- `connected_by_user_id` UUID FK `users.id` not null (the §6 notification
  recipient, consumed by 039)
- `provider_metadata` JSONB not null server_default `'{}'::jsonb`
  (non-secret provider context only)
- Indexes (style of `models/agent.py:236-272`):
  `ix_integration_connections_workspace_provider` on
  `(owner_workspace_id, provider_key)` partial `WHERE deleted = false`;
  `ix_integration_connections_user_provider` on
  `(owner_user_id, provider_key)` partial `WHERE deleted = false`.
  **Deliberately NO unique index on (owner, provider_key)** — D3; leave a
  one-line comment saying so, citing D3, so a future reviewer does not
  "fix" it.

Table 3 — `IntegrationResource(BaseModel)`,
`__tablename__ = "integration_resources"`:

- `connection_id` UUID FK `integration_connections.id`
  `ondelete="CASCADE"` not null, indexed
- `resource_type` String(64) not null (manifest vocabulary: `gmail_mailbox`,
  `google_ads_account`, `airtable_base`, `fake_resource`)
- `external_id` String(255) not null; `display_name` String(255) not null;
  `parent_external_id` String(255) nullable (MCC→account hierarchy, D4)
- `enabled` Boolean not null server_default `false` (admin/member selection,
  039)
- `availability` String(16) not null server_default `'available'`, CHECK in
  `('available', 'unavailable', 'removed')`
- `writable` Boolean not null server_default `false` +
  `permissions_metadata` JSONB not null server_default `'{}'::jsonb`
  (write-permission gating data for 040/041)
- `first_seen_at`/`last_seen_at` DateTime(tz) not null; `removed_at`
  DateTime(tz) nullable
- `UniqueConstraint("connection_id", "resource_type", "external_id",
  name="uq_integration_resources_connection_external")`
- Index `ix_integration_resources_connection_enabled` on
  `(connection_id, enabled)` partial `WHERE deleted = false`

Table 4 — `IntegrationDiscoveryRun(Base, UUIDMixin, TimestampMixin)`
(plain rows, decision 11), `__tablename__ = "integration_discovery_runs"`:

- `connection_id` UUID FK `integration_connections.id`
  `ondelete="CASCADE"` not null, indexed
- `job_id` UUID nullable (no FK — the `jobs` table is plan 030's and may
  not exist when this migration runs; documented column comment)
- `status` String(16) not null server_default `'running'`, CHECK in
  `('running', 'succeeded', 'failed')`
- Counters, Integer not null server_default `0`: `resources_found`,
  `resources_added`, `resources_removed`, `resources_unchanged`
- `error_code` String(64) nullable, `error_message` Text nullable
- `started_at` DateTime(tz) not null server_default `now()`, `finished_at`
  DateTime(tz) nullable
- Index `ix_integration_discovery_runs_connection_created` on
  `(connection_id, created_at)`

Import all four in `models/__init__.py`. Generate the migration on the
core branch (D5) against the REAL head at execution:
`uv run alembic revision --autogenerate --head core@head --version-path
alembic/versions/core -m "add integration core tables"`, then hand-check
that every CHECK constraint, partial index, and the `num_nonnulls`
expression made it in (autogenerate misses expression CHECKs — add them
with `op.create_check_constraint`/`sa.text` and matching `downgrade`).

**Verify**: `uv run alembic upgrade heads` applies cleanly;
`uv run alembic check` → no pending operations; downgrade round-trip
(`uv run alembic downgrade core@-1 && uv run alembic upgrade heads`);
`psql` (or a throwaway script) confirms inserting a connection with both
owners set, or an all-whitespace label, fails the CHECKs.

### Step 4: Domain + provider manifest

`services/integrations/domain.py`: status constants
(`CONNECTION_STATUS_AUTH_PENDING = "auth_pending"`, …), the frozensets
`CONNECTION_STATUSES` and `TERMINAL_CONNECTION_STATUSES = {"revoked"}`, and
the transition map (dict of status → allowed next statuses) implementing:

| From | Allowed to |
|------|------------|
| auth_pending | discovery_pending, active, error, revoked |
| discovery_pending | needs_resource_selection, active, degraded, error, needs_reauth, revoked |
| needs_resource_selection | active, discovery_pending, needs_reauth, error, revoked |
| active | degraded, needs_reauth, discovery_pending, needs_resource_selection, error, revoked |
| degraded | active, discovery_pending, needs_reauth, error, revoked |
| error | discovery_pending, active, needs_reauth, revoked |
| needs_reauth | discovery_pending, active, revoked |
| revoked | (terminal) |

`services/integrations/manifest.py`: frozen dataclass
`IntegrationProviderManifest` with fields `provider_key: str`,
`display_name: str`, `auth_modes: tuple[str, ...]`,
`owner_scope: Literal["user", "workspace"]`,
`oauth_scopes: tuple[str, ...]`, `resource_types: tuple[str, ...]`,
`requires_discovery: bool`, `required_form_fields: tuple[str, ...]`
(api-key modes), `capability_flags: frozenset[str]`,
`enabled_setting: str | None` (settings attribute name gating the provider;
`None` = always available). Module-level
`PROVIDER_MANIFESTS: dict[str, IntegrationProviderManifest]` built by a
`_register(manifest)` helper that runs import-time invariant checks (plan
025 shape, `registry.py:86-88`): duplicate `provider_key` →
`RuntimeError`; every `auth_mode` in the model CHECK vocabulary; oauth mode
⇒ non-empty `oauth_scopes`; api_key mode ⇒ non-empty
`required_form_fields`; `requires_discovery` ⇒ non-empty `resource_types`;
`provider_key` matches `^[a-z][a-z0-9_]*$`. Plus
`is_provider_enabled(manifest) -> bool` reading
`getattr(settings, manifest.enabled_setting)` when set.

The four entries (decision 6; D4):

- `fake` — auth_modes `("oauth", "api_key")`, owner_scope `"user"`,
  requires_discovery True, resource_types `("fake_resource",)`,
  enabled_setting `"INTEGRATIONS_FAKE_PROVIDER_ENABLED"`.
- `gmail` — `("oauth",)`, `"user"`, requires_discovery False (the mailbox
  is the principal), oauth_scopes = the Gmail readonly+send scopes (041
  finalizes; placeholders here are fine because the provider is gated),
  enabled_setting `"INTEGRATIONS_GOOGLE_CLIENT_ID"`-style gate added by 038
  (until then leave `enabled_setting` pointing at a setting that is empty by
  default, so the provider reads as disabled).
- `google_ads` — `("oauth",)`, `"workspace"`, requires_discovery True
  (MCC→account hierarchy), resource_types `("google_ads_account",)`, gated
  the same way.
- `airtable` — `("api_key",)`, `"workspace"`, requires_discovery True,
  resource_types `("airtable_base",)`, required_form_fields `("api_key",)`,
  enabled_setting `"INTEGRATIONS_AIRTABLE_ENABLED"`.

`services/integrations/providers/fake.py`: the in-process fake (decision
7): `issue_tokens()` (returns deterministic access/refresh tokens with a
short expiry), `refresh(refresh_token)` (fails when the token carries a
`poison-` prefix — the needs_reauth test hook), `revoke()`,
`discover_resources()` (returns a module-level configurable list; tests
monkeypatch it). No HTTP anywhere.

**Verify**: manifest smoke command from the table →
`['airtable', 'fake', 'gmail', 'google_ads']`; a duplicate `_register` in a
test raises `RuntimeError`; ruff exit 0.

### Step 5: Credential service + HTTP helper

`services/integrations/utils.py`: `compute_principal_fingerprint(
provider_key, external_principal_id)` → `create_hmac_signature(
f"{provider_key}:{external_principal_id}",
settings.SECRET_KEY.get_secret_value())` (`utils/security.py:204`).

`services/integrations/http.py` (decision 9): `request_with_retries(
method, url, *, operation, provider_key, **kwargs) -> httpx2.Response` —
clone the `core/auth/oauth_providers/retrying.py:51-135` control flow onto
the integrations settings, adding: on 429/503 read `Retry-After` (integer
seconds or HTTP-date), sleep `min(retry_after,
INTEGRATIONS_HTTP_RETRY_AFTER_CAP_SECONDS)` instead of the backoff formula;
map exhaustion → `IntegrationRateLimitError`/`IntegrationTimeoutError`,
4xx → `IntegrationAuthError`/`IntegrationPermissionError`/
`IntegrationValidationError` per status, all with
`provider_key`/`operation` context (the hierarchy exists —
`core/exceptions/integration.py:91-137`). Module docstring records why this
is a separate seam from `retrying_http_client()` (decision 9).

Credential ops (one per file, AGENTS.md):

- `credentials/store_oauth_credential.py` —
  `store_oauth_credential(db, *, provider_key, token_payload,
  external_principal_id, external_principal_label, granted_scopes) ->
  ExternalCredential`: computes fingerprint, encrypts tokens via the
  property setters, stamps `token_expires_at` (the
  `services/auth/oauth/utils.py:305-312` expires_in pattern), audits
  `CREATE` on `INTEGRATION_CREDENTIAL` (details: provider_key, fingerprint,
  scopes — never token values).
- `credentials/store_secret_reference_credential.py` — the api_key path:
  takes a `SecretReference` (already written by 038 via
  `services/secrets.write_secret`), persists reference columns only, CHECK
  guarantees no token columns. Fingerprint input for api-key mode is the
  provider-reported principal (Airtable whoami id — 041) or, until then,
  the secret name.
- `credentials/ensure_fresh_credential.py` — the locked proactive refresh
  (decision 8):

  ```python
  credential = (await db.execute(
      select(ExternalCredential)
      .where(ExternalCredential.id == credential_id)
      .with_for_update()
  )).scalar_one()
  # re-check expiry AFTER the lock: a concurrent caller may have refreshed
  if not _needs_refresh(credential, leeway):
      return credential
  ```

  then call the provider refresh (fake provider in this plan; 038 adds the
  real OAuth token endpoint call through `http.py`), store the rotated
  tokens, stamp `last_refreshed_at`, audit `UPDATE` (status SUCCESS).
  On refresh failure: increment `refresh_failure_count`, stamp
  `last_refresh_error_code`, audit FAILURE, and call
  `transition_connection_status(..., "needs_reauth", reason=...)` for the
  owning connection. Raise `IntegrationAuthError`. No notification here
  (039, governance §6).
- `credentials/revoke_credential.py` — crypto-shred (decision 3):
  `credential.crypto_shred()`, connection → `revoked` via the transition
  op, audit `DELETE` on `INTEGRATION_CREDENTIAL` with metadata only.
  Provider-side token revocation is best-effort and belongs to 038 (it has
  the provider endpoints); this op is the local shred.
- `credentials/find_duplicate_principals.py` —
  `find_duplicate_principals(db, *, provider_key, principal_fingerprint,
  exclude_credential_id=None) -> list[uuid.UUID]` returning other live
  connection ids sharing the fingerprint (D3 dedup surface for 038/042 —
  warn, never block).
- `connections/transition_connection_status.py` — the single guard
  (decision 12): validates the move against the domain transition map
  (invalid → `IntegrationConnectionError`), stamps
  `status`/`status_reason`/`status_changed_at`, audits `UPDATE` on
  `INTEGRATION_CONNECTION` with `{"from": ..., "to": ..., "reason": ...}`,
  and is a no-op (no audit spam) when the status is unchanged.

`services/integrations/__init__.py` re-exports the ops only.

**Verify**: ruff exit 0;
`uv run python -c "from services.integrations import ensure_fresh_credential, transition_connection_status"`
imports; Step 7 tests pin the lock behavior.

### Step 6: Audit enum additions

Add to `AuditResourceType` (`services/audit_events/enums.py:25-41`):
`INTEGRATION_CONNECTION = "integration_connection"`,
`INTEGRATION_CREDENTIAL = "integration_credential"`,
`INTEGRATION_RESOURCE = "integration_resource"`,
`SECRET_REFERENCE = "secret_reference"`. No `AuditAction` additions —
CREATE/UPDATE/DELETE/EXECUTE cover every flow above.

**Verify**: `uv run pytest tests/services -q -k audit` (existing audit
tests still green); ruff exit 0.

### Step 7: Tests

`tests/factories/integrations.py`: `create_external_credential(...)`,
`create_integration_connection(...)` (defaults: fake provider, oauth mode,
workspace owner, label "Test connection"), `create_integration_resource(...)`
— the `tests/factories/` style, DB rows via the shared session fixture.

New modules (all set `pytestmark = pytest.mark.asyncio`; DB-backed ones
skip cleanly without `TEST_DATABASE_URL`):

- `tests/services/integrations/test_manifest.py` (no DB): four entries
  registered; duplicate key raises `RuntimeError`; oauth-without-scopes and
  api_key-without-form-fields rejected; `is_provider_enabled` honors the
  gate; fake provider disabled by default.
- `tests/services/integrations/test_models.py` (DB): owner XOR CHECK
  (both/neither owner → IntegrityError); blank label rejected; status CHECK
  rejects unknown status; mode-payload CHECK (oauth row with secret_name
  fails; api_key row with token columns fails); **two live connections,
  same provider, same owner, different labels, both insert cleanly — the
  pinned D3 invariant with a comment saying a uniqueness "fix" is a
  regression**.
- `tests/services/integrations/test_credential_service.py` (DB): token
  encrypt/decrypt round-trip and ciphertext-at-rest (raw column value is
  not the plaintext); fingerprint is deterministic and equal across two
  connections of the same principal (`find_duplicate_principals` returns
  the sibling — cross-connection dedup, D3); refresh failure flips the
  connection to `needs_reauth`, increments `refresh_failure_count`, writes
  a FAILURE audit row, and **creates no notification row** (that is 039);
  `revoke_credential` crypto-shreds (both encrypted columns NULL,
  `revoked_at` set, connection `revoked`, audit row has no token material).
- `tests/services/integrations/test_refresh_locking.py` (DB): **the
  double-refresh serialization invariant** — two concurrent sessions call
  `ensure_fresh_credential` on the same expiring credential; assert the
  fake provider's refresh call-count is exactly 1 and both callers see the
  same rotated token (second session re-checks after the FOR UPDATE lock).
- `tests/services/integrations/test_status_transitions.py` (DB or unit on
  the map): every row of the Step 4 table allowed; `revoked → *` and other
  illegal moves raise `IntegrationConnectionError`; same-status call is a
  no-op with no audit row.
- `tests/services/integrations/test_http_retries.py` (no DB, mock
  transport): 429 with `Retry-After: 2` sleeps ~2 s not the backoff value
  (freeze/patch sleep); `Retry-After` above the cap is capped; attempts
  bounded at `INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS`; 401 maps to
  `IntegrationAuthError` without retry.
- `tests/services/secrets/test_local_provider.py`: env-var resolution;
  write→resolve round-trip through the encrypted file; file content on disk
  is not plaintext; missing secret raises `IntegrationAuthError` and writes
  a FAILURE audit row whose details contain the reference and **no value**.
- `tests/services/secrets/test_settings_gating.py` (no DB): building
  `Settings` with `SECRET_PROVIDER=local, ENVIRONMENT=production` raises;
  `gcp_secret_manager` without `GCP_PROJECT_ID` raises; fake provider
  enabled outside local raises (construct Settings objects directly with
  overrides — the existing settings-validation test pattern).

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/integrations tests/services/secrets -q`
→ all pass; without the env var the DB modules skip, not fail;
`TEST_DATABASE_URL=... uv run pytest -q` → full suite green.

## Test plan

Covered by Step 7 (~28–34 tests). The pinned invariants: **no
double-refresh** (FOR UPDATE + re-check; exactly one provider refresh call
under concurrency), **fingerprint dedup detects and never blocks** (D3),
**crypto-shred at revoke** (ciphertext gone, metadata kept, audit clean of
values), **no per-provider uniqueness** (two labeled connections insert),
**owner XOR and non-blank label at the database layer**, **local secrets
and the fake provider cannot leave local** (settings validator), and
**Retry-After honored, capped, and bounded** (governance §4).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no pending operations; the migration
      is on the **core** branch (D5) and downgrade round-trips
- [ ] `TEST_DATABASE_URL=... uv run pytest -q` exits 0 (full suite)
- [ ] Manifest smoke prints `['airtable', 'fake', 'gmail', 'google_ads']`
- [ ] Grep confirms NO unique index or constraint on
      `(owner_*, provider_key)` in `models/integrations.py` (D3)
- [ ] Grep confirms no raw token/secret value appears in any audit
      `details` construction under `services/integrations/` or
      `services/secrets/`
- [ ] No `routes/integrations/` package exists (038's surface; this plan is
      backend-only and documented as pending)
- [ ] `docs/architecture/governance.md` updated: §4 row "Integration API
      retries" → `[implemented: plan 037]`; §5 bullets for provider
      requirement, references-only storage, OAuth-tokens-encrypted, and
      resolve-failure auditing → `[implemented: plan 037]` (leave the §5
      rotation bullet and api-key connect exception marked for 038; §1 and
      §3 credential cells flip in 038/039 as their plans complete)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated (add the 037 row if
      absent)

## STOP conditions

Stop and report back (do not improvise) if:

- Any table named `external_credentials`, `integration_connections`,
  `integration_resources`, or `integration_discovery_runs` already exists,
  or `services/integrations/`/`services/secrets/` already exist (someone
  started Phase 4a first).
- The core migration head is not what you expect from the landed 030–036
  work — renumber against the real `core@head` and re-verify no landed
  migration claimed a conflicting table or index name. (At `0cbbb39` the
  head is `core_0008`; plans 030–032 add heads before this plan runs.)
- `utils/security.py` no longer provides `encrypt_data`/`decrypt_data`/
  `create_hmac_signature` with the Step 5 signatures, or the `UserAuth`
  encrypted-property precedent has been refactored — reconcile the seam
  first.
- `SECRET_PROVIDER` has gained a code consumer since `0cbbb39`
  (`grep -rn "settings.SECRET_PROVIDER"` beyond `services/secrets/`) — the
  Literal narrowing in Step 1 is no longer free.
- `docs/architecture/governance.md` §3/§4/§5 defaults have changed from the
  values cited here — the note wins; reconcile before coding.
- The `num_nonnulls` CHECK or the expression CHECKs cannot be expressed in
  the installed SQLAlchemy/Alembic without raw DDL beyond
  `op.execute`/`sa.text` — report rather than silently dropping a
  constraint.
- You feel the need to add HTTP routes, job handlers, notifications, or a
  real provider HTTP client — that is 038/039/041 scope leaking in.

## Maintenance notes

- **Consumers**: 038 (OAuth/api-key connect flows write credentials +
  connections and add integration OAuth client settings; provider-side
  revoke), 039 (discovery job kind writes `integration_resources` +
  `integration_discovery_runs`, drives data-computed status, emits §6
  notifications, registers the `integrations.sweep_stale` retention kind —
  including the 30 d post-revoke credential hard-delete from §3), 040
  (active-context resolution across N connections per D3 — the
  `find_duplicate_principals` fingerprint surface and `enabled` resources
  are its inputs), 041 (Gmail/Google Ads/Airtable operations + registry
  tools through the 026 choke point; Google Ads spend mutations are
  `approval` with `supports_auto=False` per governance §2 — Gate G1), 042
  (UI: provider cards, multiple labeled connections per provider,
  duplicate-principal warnings).
- **Key rotation**: token encryption rides `utils/security.py`'s
  `_encryption_keys` list (line 34) — rotating `ENCRYPTION_KEY` requires
  the multi-key decrypt path there, not anything integration-specific. The
  principal fingerprint is keyed by `SECRET_KEY`: rotating `SECRET_KEY`
  orphans existing fingerprints (dedup detection degrades gracefully; rows
  stay valid). Record any SECRET_KEY rotation as requiring a fingerprint
  backfill script.
- **Secret rotation** (§5): `write_secret` always creates a new version and
  the old version stays readable until the connection re-test (038)
  confirms the new one — the provider contract enforces the first half;
  038's test route completes the loop.
- **The LLM credential seam** (`provider_api_key`,
  `services/agents/models/utils.py:68-83`) still reads env settings by
  design; its docstring names `SECRET_PROVIDER` as the future path. When
  that migration happens, it goes through `services/secrets` — one seam,
  no second resolver.
- Reviewers should scrutinize: the mode-payload CHECK (an api_key row must
  be physically unable to carry tokens), the FOR UPDATE re-check ordering
  in `ensure_fresh_credential`, that `transition_connection_status` is the
  ONLY writer of `IntegrationConnection.status` (grep before approving),
  and that no test or fixture ever writes a real provider credential.
