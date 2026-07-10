# Plan 037: Integration core models, credential service, and secret references

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md` and flip the governance cells listed in
> "Done criteria" in `docs/architecture/governance.md`.
>
> **Notes pre-flight (run before Step 1)**: this plan implements slices of
> three architecture notes — `docs/architecture/governance.md` (§1 role
> matrix, §3 credentials retention, §4 Retry-After retries, §5 secrets
> operating model), `docs/architecture/integration-packaging.md` (plugin
> contract, loader, import laws), and
> `docs/architecture/integration-events.md` (reserved event seams).
> Re-read those sections before coding; the notes win over this plan. If
> any cited default has changed since `63edba9`, reconcile before
> proceeding.
>
> **Drift check (run first)**:
> `git diff --stat 63edba9..HEAD -- apps/api/models/ apps/api/core/settings/ apps/api/core/exceptions/integration.py apps/api/utils/security.py apps/api/services/audit_events/enums.py apps/api/services/storage/ apps/api/services/jobs/ apps/api/alembic/versions/core/ apps/api/pyproject.toml apps/api/services/agents/runtime/tools/registry.py apps/api/services/agents/models/utils.py`
> If any in-scope file changed since this plan was consolidated, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Status**: DONE (2026-07-10)
- **Priority**: P1
- **Effort**: L (the largest of the three Phase 4a foundation plans)
- **Risk**: HIGH (credential storage, encryption, and the production secrets
  posture — mistakes here are security incidents, not bugs)
- **Depends on**: 029 (DONE — `docs/architecture/governance.md` exists),
  030 (DONE — the re-encryption sweep job registers on its harness). Soft:
  the `integration_discovery_runs` table is created now but only written by
  039. Does NOT depend on 031–036.
- **Category**: Phase 4a integrations, Gate G3 satisfied (roadmap
  `000_MASTER_ROADMAP.md` §4 Phase 4a row 037; donor `DONOR_PORT_ROADMAP.md`
  §4.2 / §6 row C1; decisions D3, D4, D5, D11)
- **Planned at**: commit `0cbbb39`, 2026-07-06. **Consolidated at**
  `63edba9`, 2026-07-10: the amendments from plans 061 (provider
  packaging), 068 (credential encryption posture), 077 (inbound event
  seams), 080 (readiness sweep), and roadmap decision D11 (no fake
  provider) are folded into the body below, and every code anchor was
  re-verified at `63edba9`. See "Superseded decisions" for what was ruled
  out; the full deliberation history lives in
  `docs/plans/complete/{061,068,077,080}-*.md` and the roadmap decision
  table.

## Completion notes

Plan 037 was implemented and verified on 2026-07-10. Three operator decisions
made during execution supersede narrower details later in this historical plan:

1. Integration enablement uses exactly one mechanism for every provider:
   `INTEGRATIONS_ENABLED_PROVIDERS`. The manifest has no `enabled_setting`,
   there is no `INTEGRATIONS_AIRTABLE_ENABLED`, and missing operational config
   must fail fast when the owning provider slice lands.
2. `SECRET_PROVIDER` supports local development plus all three production
   cloud backends: GCP Secret Manager, Azure Key Vault, and AWS Secrets
   Manager. Cloud SDK dependencies are bundled into one optional extra per
   cloud (`gcp`, `azure`, or `aws`) across storage and secrets, and each secret
   backend has provider-specific production validation.
3. Shipped provider manifests advertise discovery only when their real
   discovery callable lands. Airtable and Google Ads therefore remain
   `requires_discovery=False` until plan 041 wires those operations.

The migration was written by hand as `core_0013`, checked against SQLAlchemy
metadata, and downgrade/upgraded cleanly. The focused integration/secrets suite
passed 77 tests and the full DB-backed API suite passed 645 tests. Every root
gate component passed except the all-tree API format check, which still reports
pre-existing drift in `tests/routes/conversations/test_turn_streaming.py`; this
scoped plan did not modify that unrelated file, and every changed Python path is
Ruff-formatted.

## Decisions taken

1. **Full multi-connection per provider (roadmap D3).** There is NO
   one-active-per-provider-per-owner unique index anywhere in this schema —
   deliberately, against the donor design (`DONOR_PORT_ROADMAP.md` §4.2;
   D3 overrides it). Every connection carries a **required, non-empty,
   user-set `label`** (CHECK-enforced). Duplicate detection of the same
   external principal across connections is a **warning surface via the
   HMAC principal fingerprint, never a block**.
2. **Owner is user XOR workspace, CHECK-enforced.** `owner_user_id` XOR
   `owner_workspace_id` via `num_nonnulls(...) = 1`. User-owned connections
   (Gmail per D4) are personal and not pinned to one workspace; the acting
   workspace for RBAC and audit comes from the request context (038), and
   per-workspace resolution is plan 040's active-context job.
   Workspace-owned connections (Google Ads per D4) are shared per
   governance §1.
3. **Only OAuth tokens are stored in Postgres, encrypted at rest** — the
   `UserAuth` column/property shape (`models/user.py:352-389`):
   `*_encrypted` Text columns plus encrypt/decrypt property pairs.
   Everything non-OAuth is a secret **reference**
   `{provider, name, version}` resolved at call time (governance §5).
   **Revoke = crypto-shred**: null both token columns, stamp `revoked_at`,
   keep the metadata row (governance §3 credentials row); the 30-day hard
   delete is 039's sweep kind, recorded there.
4. **Dedicated credential root key, not `ENCRYPTION_KEY` (plan 068).**
   OAuth token columns are NOT encrypted with the app-wide
   `ENCRYPTION_KEY`, and the principal fingerprint is NOT keyed with
   `SECRET_KEY`:
   - Outside `ENVIRONMENT=local`, the root key material resolves at first
     use through `services/secrets` (reference name from the new setting
     `CREDENTIAL_MASTER_KEY_SECRET_NAME`, default `credential-master-key`,
     version `latest`). The new env setting `CREDENTIAL_MASTER_KEYS`
     (comma-separated Fernet keys, newest first — the secret value uses
     the same format) is a local-only fallback, rejected outside local by
     the Step 1 validator. Resolution is an async cached accessor — once
     per process, never at import time.
   - **HKDF purpose subkeys**: `derive_purpose_key(root: bytes,
     purpose: str) -> bytes` (HKDF-SHA256; `cryptography` is already a
     dep) in `utils/security.py`. Token columns encrypt/decrypt through a
     `MultiFernet` over keys derived with purpose
     `praxis:credential-tokens:v1` (one per root key, newest first; Fernet
     key = urlsafe-b64 of the 32-byte HKDF output).
     `compute_principal_fingerprint` keys its HMAC with the newest key
     derived with purpose `praxis:principal-fingerprint:v1`.
     `UserAuth`/TOTP stay on `ENCRYPTION_KEY` unchanged.
   - **`encryption_key_id` column**: the credentials table records the
     first 16 hex chars of SHA-256 over the root key string that encrypted
     the row (null when both token columns are null), kept accurate by
     `store_oauth_credential`, every refresh, and `crypto_shred`. Rotation
     progress is thereby a SQL query, not a guess.
   - **Re-encryption sweep job**: kind
     `integrations.rotate_credential_encryption` on the jobs harness — an
     explicit exception to this plan's "no job handlers" out-of-scope
     line. It walks live `external_credentials` rows whose
     `encryption_key_id` differs from the newest root key id, re-encrypts
     under the newest key with per-row `SELECT ... FOR UPDATE` (the
     `ensure_fresh_credential` lock discipline), and restamps the id.
     Enqueued manually (document the command); no schedule. One summary
     audit event (`UPDATE` on `INTEGRATION_CREDENTIAL`, count-only
     details). Fingerprints are NOT recomputed — the plaintext principal
     id is not stored; on root rotation, dedup detection degrades
     gracefully for pre-rotation rows and heals at reconnect.
   - Full envelope encryption (per-credential DEKs wrapped by a KMS KEK)
     is the recorded end-state with revisit triggers in plan 068 — do not
     build it here.
5. **Secrets provider abstraction mirrors storage.** New `services/secrets/`
   package with a `SecretsProvider` Protocol (shape of
   `services/storage/provider.py:17`), a factory singleton (shape of
   `services/storage/factory.py:22`), a **local provider** (env-var read
   plus a Fernet-encrypted `.local/` file store so the 038 api-key connect
   flow can write locally), plus **GCP Secret Manager, Azure Key Vault, and
   AWS Secrets Manager** behind optional extras. The existing, entirely unconsumed
   `SECRET_PROVIDER` setting (`core/settings/providers.py:16`; its only
   other mention is a docstring, `services/agents/models/utils.py:4-9`) is
   setting is narrowed to those four concrete values — the dead generic
   `"secret_manager"`/`"key_value"` values go away while nothing reads them.
6. **Production-safety validation per governance §5**: the `model_validator`
   in `core/settings/__init__.py:58` gains three rules mirroring the
   local_fs/console gating at lines 66-70: `SECRET_PROVIDER == "local"`
   only when `ENVIRONMENT == "local"`;
   each cloud provider requires its identifying setting (`GCP_PROJECT_ID`,
   `AZURE_KEY_VAULT_URL`, or `AWS_REGION`); `CREDENTIAL_MASTER_KEYS` is
   allowed only when `ENVIRONMENT == "local"`. Production therefore requires
   a concretely configured cloud secret manager by construction.
7. **Providers are packages behind a plugin contract and loader (plan
   061).** `services/integrations/manifest.py` is contract + registration
   only — **no hardcoded provider entries**. `services/integrations/
   plugin.py` defines `IntegrationProviderPlugin` (manifest +
   `discover_resources` + `tool_definitions`);
   `services/integrations/loader.py` imports `integrations.{key}` for each
   entry in the new `INTEGRATIONS_ENABLED_PROVIDERS: list[str] = []`
   setting, validates the packaging note's §4.3 invariants, fails fast at
   boot, and registers manifests and tools into the existing singular
   registries. The D4 providers ship as **three manifest-data-only
   packages** under `apps/api/integrations/` — `gmail/`, `google_ads/`,
   `airtable/` (empty `tool_definitions`; 041 fills them). Import laws per
   the note §4.6 are pinned by an AST-walking test; `build_runtime_tools`
   goes lenient on catalog-absent saved tool names per §4.7 (skip + log +
   run metadata, not `ModelConfigurationError`); write-time validation
   stays strict.
8. **No fake provider ships, in any form (roadmap D11).** The shipped
   provider set is exactly D4. The plugin contract and loader are
   exercised by a **suite-local test provider registered through the
   loader seam in test code only** (fixtures under the test tree, never
   product code), with provider HTTP (token/userinfo/discovery endpoints)
   mocked at the transport layer. Manual QA connects real dev credentials
   (Airtable's API key is the cheapest connect). The plugin contract stays
   `manifest + discover_resources + tool_definitions` — there is no
   `oauth_operations` escape hatch; the engine's generic manifest-driven
   OAuth flow (038) is the only token path.
9. **Locked proactive refresh.** `ensure_fresh_credential` refreshes when
   `token_expires_at - now < INTEGRATIONS_TOKEN_REFRESH_LEEWAY_SECONDS`
   (default 120, inside the donor's 60–180 s band), serialized per
   credential row with `SELECT ... FOR UPDATE` and a re-read after acquiring
   the lock (rotating refresh tokens die if double-refreshed — the invariant
   is pinned by a two-session test). A refresh-token failure (4xx from the
   token endpoint) flips the connection to `needs_reauth` and audits; the §6
   notification to the connecting user is deliberately deferred to 039
   (governance §6 names 039 as the emitting plan).
10. **Retry-After-aware bounded retries on `httpx2`** (governance §4 row
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
11. **Audit vocabulary grows four members**: `AuditResourceType` gains
    `INTEGRATION_CONNECTION`, `INTEGRATION_CREDENTIAL`,
    `INTEGRATION_RESOURCE`, `SECRET_REFERENCE`
    (`services/audit_events/enums.py:26-42` has none of these). Every token
    issuance, refresh, refresh failure, revoke, and secret-reference
    create/update/delete is audited; secret **resolve failures** are audited,
    successful resolves are not (too noisy), and no audit detail ever
    contains a secret value (governance §5).
12. **All four tables land in one core migration now**, including
    `integration_discovery_runs`, which only 039 writes — one migration
    beats three dribbles, and the table shape is fixed by the donor design.
    Discovery-run rows are **plain** (`Base + UUIDMixin + TimestampMixin`,
    the `models/rate_limiting.py:16` composition) — governance §3 lists them
    as "plain rows, 90 d"; soft-delete columns on an append-mostly log are
    dead weight. Credentials, connections, and resources use `BaseModel`
    (soft delete) because §3 gives them soft-then-hard lifecycles.
13. **Status-machine vocabulary and the transition guard live here**
    (`services/integrations/domain.py` + `transition_connection_status`
    service op) so 038 and 039 share one enforcement point; discovery-driven
    transitions (`needs_resource_selection` computed from enabled resources)
    are wired by 039.
14. **Inbound event seams are reserved, not implemented (plan 077).** Per
    `docs/architecture/integration-events.md`:
    - `IntegrationProviderManifest` gains `event_delivery:
      Literal["none", "webhook", "pubsub_push"] = "none"` (data only; the
      loader and plugin contract are unchanged). D4 entries: gmail
      `"pubsub_push"`, airtable `"webhook"`, google_ads `"none"`.
    - Per-webhook MAC secrets are `services/secrets` references named
      `integrations/{provider_key}/{connection_id}/webhook/{webhook_id}` —
      no new column, table, or encryption mechanism. Note this in the
      credential service's docstring so the implementing plan finds one
      seam, not two.
    - `integration_events` is a **reserved table decision, not scope**: the
      note §4 fixes its shape; the migration lands with the first event
      implementation plan, on the core branch. Do not create it here — but
      do not claim its name for anything else either.

## Superseded decisions

Recorded so nobody re-proposes them; full reasoning lives in the completed
plan docs and the roadmap decision table.

- **The `fake` integration provider** (original decision here, then
  repackaged by plan 061 and given an `oauth_operations` plugin seam by
  plan 080) — **removed entirely by roadmap D11 (2026-07-10)**. No fake
  package, manifest entry, `INTEGRATIONS_FAKE_PROVIDER_ENABLED` setting,
  or `"fake"`-in-enabled-list validator gate ships; decision 8 above is
  the replacement.
- **Optional `oauth_operations` plugin attribute** (plan 080 decision 1) —
  dropped with its only consumer (D11). Revisit only if a real provider
  cannot use the generic manifest-driven OAuth flow.
- **Token encryption under the app-wide `ENCRYPTION_KEY` and fingerprints
  keyed by `SECRET_KEY`** (the original posture, mirroring `UserAuth`) —
  replaced by the plan 068 posture in decision 4.
- **Donor's one-active-connection-per-provider partial unique index**
  (`DONOR_PORT_ROADMAP.md` §4.2) — rejected by D3 in favor of full
  multi-connection.
- **Full envelope encryption now** — deferred; plan 068 records the
  end-state and revisit triggers.

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

All anchors re-verified at `63edba9`. Nothing integration-shaped exists
beyond the exception layer; there is no `services/integrations/`, no
`services/secrets/`, no `apps/api/integrations/`, and no `integration_*` or
`external_credentials` table.

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
  103-158), `create_hmac_signature`/`verify_hmac_signature` (205-232),
  `hash_token` (69-81). There is no `derive_purpose_key` yet (Step 5 adds
  it). `ENCRYPTION_KEY` is validated as a Fernet key at settings load
  (`core/settings/security.py:85-94`); `SECRET_KEY` min length 32
  (`core/settings/security.py:16`).
- Encrypted-token model precedent: `apps/api/models/user.py` `UserAuth`
  (344-397): `access_token_encrypted`/`refresh_token_encrypted` Text columns
  (352-353) with encrypt/decrypt property pairs (361-389) and
  `is_token_expired` (392-397). The **column/property shape** is the
  precedent; the crypto seam differs per decision 4.
- Settings: mixins compose in `core/settings/__init__.py:30-56`; the
  production-safety `model_validator` is `validate_runtime_provider_config`
  at line 58 with the local-only gating precedent at 66-70 (`local_fs`,
  `console`).
  `SECRET_PROVIDER: Literal["local", "secret_manager", "key_value"]` exists,
  default `"local"`, at `core/settings/providers.py:16` — **zero code
  consumers** (the only other hit is the docstring at
  `services/agents/models/utils.py:4-9`), so narrowing it is safe.
  `GCP_PROJECT_ID` exists (`core/settings/gcp.py:10`);
  `LOCAL_STORAGE_ROOT` at `core/settings/providers.py:28`.
- Provider-ABC precedent: `services/storage/provider.py:17`
  (`@runtime_checkable` Protocol with `provider_key` + async ops);
  factory singleton with lock (`services/storage/factory.py:19-51`);
  optional extras per cloud provider (`pyproject.toml:27-30`: `azure`,
  `gcp`, `aws`).
- HTTP: `httpx2>=2.5.0` is the runtime dep (`pyproject.toml:14`);
  `cryptography>=49` (line 11), `pyjwt>=2.13` (line 20). The OAuth retry
  precedent is `core/auth/oauth_providers/retrying.py:51-135` (bounded
  attempts, exponential backoff, 4xx→typed auth error, 5xx/network→retry) —
  it does NOT honor `Retry-After`. The LLM transport
  (`services/agents/models/utils.py:41-65`) does, via pydantic-ai's
  `wait_retry_after`, but on plain `httpx` — see decision 10.
- Import-time registry invariants precedent:
  `services/agents/runtime/tools/registry.py` — the `runtime_tool`
  decorator (line 35) validates then raises `RuntimeError` on a duplicate
  name (line 95); provider modules are imported for side effects at the
  bottom of the module (line 268). `build_runtime_tools` (lines 102-155)
  is currently **strict** on catalog-absent names
  (`ModelConfigurationError` at 124-132) — decision 7 makes it lenient.
- Jobs harness (plan 030, DONE): handlers live in
  `services/jobs/handlers/`, registered via the decorator in
  `services/jobs/registry.py` (duplicate-kind guard at line 41);
  `enqueue_job.py` is the manual-enqueue path.
- Model conventions: `models/base.py` — `BaseModel` (130-138, soft delete),
  `UUIDMixin` (18-21), `TimestampMixin` (24-30), `CreatedAtMixin` (124-127);
  non-soft-delete composition precedent `models/rate_limiting.py:16`.
  CHECK-constraint + partial-index precedent: `models/agent.py:222-273`
  (status CHECK 223-229, partial unique indexes 255-272). New models must be
  imported in `models/__init__.py` (registry comment, lines 1-12).
- Migrations: core head is `core_0012`
  (`alembic/versions/core/0012_add_scratch_entries_table.py`). This plan
  calls its migration `core_00NN`; the number is fixed against the real
  `core@head` at execution (STOP condition below). D5: core branch.
- Audit: `services/audit_events/enums.py` — `AuditAction` (13-23),
  `AuditResourceType` (26-42, no integration members), `AuditActorType`
  (45+), `AuditStatus` below it. Audit FKs survive subject deletion
  (`models/audit_event.py:19,37,44`, per governance §3).
- Tests: `tests/support/settings.py::configure_test_environment` sets safe
  env defaults including a generated `ENCRYPTION_KEY`; DB-backed tests gate
  on `TEST_DATABASE_URL` via `conftest.py` fixtures and skip cleanly
  without it; factories live in `tests/factories/`.
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
| Loader smoke (default) | `uv run python -c "from services.integrations.loader import load_enabled_providers; from services.integrations.manifest import PROVIDER_MANIFESTS; load_enabled_providers(); print(sorted(PROVIDER_MANIFESTS))"` | `[]` |
| Loader smoke (all enabled) | same, with `INTEGRATIONS_ENABLED_PROVIDERS='["airtable","gmail","google_ads"]'` in the env | `['airtable', 'gmail', 'google_ads']` |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/integrations tests/services/secrets tests/integrations -q` | all pass |
| Full API tests | `TEST_DATABASE_URL=... uv run pytest -q` | all pass |

Both loader-smoke expectations get tests (Step 7).

## Scope

**In scope:**

- `apps/api/models/integrations.py` (create — four models) +
  `apps/api/models/__init__.py` (register imports)
- `apps/api/alembic/versions/core/00NN_*.py` (create — core branch, D5)
- `apps/api/core/settings/integrations.py` (create —
  `IntegrationsSettingsMixin`), `core/settings/providers.py` (narrow
  `SECRET_PROVIDER` Literal), `core/settings/__init__.py` (compose mixin +
  extend the production-safety validator per decision 6)
- `apps/api/utils/security.py` (add `derive_purpose_key`)
- `apps/api/services/secrets/` (create): `__init__.py`, `domain.py`,
  `provider.py`, `factory.py`, `resolve_secret.py`, `write_secret.py`,
  `delete_secret.py`,
  `providers/__init__.py`, `providers/local.py`,
  `providers/gcp_secret_manager.py`, `providers/azure_key_vault.py`,
  `providers/aws_secrets_manager.py`, `utils.py`
- `apps/api/services/integrations/` (create): `__init__.py`, `domain.py`,
  `manifest.py`, `plugin.py`, `loader.py`, `http.py`, `utils.py`,
  `credentials/__init__.py`, `credentials/store_oauth_credential.py`,
  `credentials/ensure_fresh_credential.py`,
  `credentials/revoke_credential.py`,
  `credentials/store_secret_reference_credential.py`,
  `credentials/find_duplicate_principals.py`,
  `connections/__init__.py`, `connections/transition_connection_status.py`
- `apps/api/integrations/` (create): `gmail/`, `google_ads/`, `airtable/`
  manifest-data-only provider packages (decision 7)
- `apps/api/services/jobs/handlers/rotate_credential_encryption.py`
  (create — the decision 4 sweep, the one job-handler exception)
- `apps/api/services/agents/runtime/tools/registry.py`
  (`build_runtime_tools` lenient per packaging note §4.7)
- `apps/api/services/audit_events/enums.py` (add four
  `AuditResourceType` members)
- `apps/api/pyproject.toml` (add optional extras for GCP Secret Manager,
  Azure Key Vault, and AWS Secrets Manager)
- `apps/api/tests/services/integrations/`, `apps/api/tests/services/secrets/`,
  and `apps/api/tests/integrations/` (create),
  `apps/api/tests/factories/integrations.py` (create)

**Out of scope (do NOT touch):**

- HTTP routes of any kind — 038 owns `routes/integrations/`. This plan has
  **no public surface**; per AGENTS.md, that is documented here as pending.
- Discovery execution, sweeps, and notifications — 039 (governance §6
  explicitly names 039 for `needs_reauth`/discovery-failure notifications;
  this plan only sets status + audit). Job handlers generally, EXCEPT the
  decision 4 re-encryption sweep.
- The `integration_events` table — reserved, lands with the first event
  implementation plan (decision 14).
- Active context and `RuntimeDeps` injection — 040.
- Real provider operations, API clients, and registry tools — 041 (Gate G1
  applies there, not here).
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
INTEGRATIONS_ENABLED_PROVIDERS: list[str] = []          # provider packages the loader imports (decision 7)
INTEGRATIONS_TOKEN_REFRESH_LEEWAY_SECONDS: int = 120    # proactive refresh window (60-180 band, decision 9)
INTEGRATIONS_HTTP_TIMEOUT_SECONDS: float = 30.0         # per-request timeout
INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS: int = 3           # bounded attempts (governance §4)
INTEGRATIONS_HTTP_RETRY_BACKOFF_FACTOR: float = 0.5     # fallback exponential backoff
INTEGRATIONS_HTTP_RETRY_AFTER_CAP_SECONDS: int = 60     # Retry-After honored up to this cap
CREDENTIAL_MASTER_KEY_SECRET_NAME: str = "credential-master-key"  # secrets-provider reference (decision 4)
CREDENTIAL_MASTER_KEYS: str | None = None               # local-only fallback: comma-separated Fernet keys, newest first
```

All numeric fields `Field(..., gt=0, description=...)`. In
`core/settings/providers.py` narrow the Literal:
`SECRET_PROVIDER` accepts `local`, `gcp_secret_manager`, `azure_key_vault`,
or `aws_secrets_manager`, defaulting to `local`. Compose the mixin into
`Settings` in `core/settings/__init__.py` and extend
`validate_runtime_provider_config` (line 58), mirroring the
local_fs/console pattern at 66-70:

```python
if self.SECRET_PROVIDER == "local" and self.ENVIRONMENT != "local":
    raise ValueError("SECRET_PROVIDER=local is only allowed when ENVIRONMENT=local")
if self.SECRET_PROVIDER == "gcp_secret_manager" and not (self.GCP_PROJECT_ID or "").strip():
    raise ValueError("SECRET_PROVIDER=gcp_secret_manager requires GCP_PROJECT_ID")
if self.SECRET_PROVIDER == "azure_key_vault" and not (self.AZURE_KEY_VAULT_URL or "").strip():
    raise ValueError("SECRET_PROVIDER=azure_key_vault requires AZURE_KEY_VAULT_URL")
if self.SECRET_PROVIDER == "aws_secrets_manager" and not self.AWS_REGION.strip():
    raise ValueError("SECRET_PROVIDER=aws_secrets_manager requires AWS_REGION")
if self.CREDENTIAL_MASTER_KEYS and self.ENVIRONMENT != "local":
    raise ValueError("CREDENTIAL_MASTER_KEYS is only allowed when ENVIRONMENT=local")
```

Add `SECRET_PROVIDER=local` awareness to
`tests/support/settings.py::configure_test_environment` only if the default
does not already satisfy tests (it should — default is `local` and tests set
`ENVIRONMENT=local`); tests DO need a generated `CREDENTIAL_MASTER_KEYS`
value there, alongside the existing generated `ENCRYPTION_KEY`.

**Verify**:
`uv run python -c "from core.settings import settings; print(settings.INTEGRATIONS_TOKEN_REFRESH_LEEWAY_SECONDS)"`
→ `120`; non-DB unit tests pin the local-only and cloud-provider validator rejections;
`uv run ruff check .` → exit 0.

### Step 2: Secrets provider abstraction (`services/secrets/`)

`domain.py`: frozen dataclass `SecretReference(provider: str, name: str,
version: str)` with `def render(self) -> str` returning
`"{provider}:{name}#{version}"` for audit details (reference identity only,
never values), and a `SECRET_NAME_PATTERN = ^[a-zA-Z0-9_\-]{1,255}$`
validation helper. Names are caller-namespaced; the 038 api-key flow will
use `integrations/{provider_key}/{connection_id}` normalized to this
pattern, and future webhook MAC secrets use
`integrations/{provider_key}/{connection_id}/webhook/{webhook_id}`
(decision 14).

`provider.py`: `@runtime_checkable` Protocol `SecretsProvider` (mirror
`services/storage/provider.py:17`):

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

The cloud providers are `GcpSecretManagerProvider`, `AzureKeyVaultProvider`,
and `AwsSecretsManagerProvider`. Each imports its SDK lazily behind its own
optional extra and implements resolve/write/delete through the shared contract.
For GCP, `providers/gcp_secret_manager.py`
defines `GcpSecretManagerProvider`
(`provider_key = "gcp_secret_manager"`), imports
`google.cloud.secretmanager` lazily inside methods (optional-extra pattern —
check how `services/storage/providers/gcs.py` guards its import and copy
that shape). `resolve_secret` → `access_secret_version` on
`projects/{GCP_PROJECT_ID}/secrets/{name}/versions/{version}` (`"latest"`
allowed); `write_secret` → create-secret-if-missing + `add_secret_version`,
returning the new version id. Vault identifiers use a bounded SHA-256 mapping
of the caller-facing reference name so slash-namespaced references remain
collision-resistant on providers whose native names cannot contain slashes.

`factory.py`: `get_secrets_provider()` singleton with the storage factory's
locked-singleton shape (`services/storage/factory.py:19-51`), keyed on
`settings.SECRET_PROVIDER`.

`resolve_secret.py` / `write_secret.py` / `delete_secret.py` (service ops,
one per file): thin
wrappers that call the provider and write audit rows per governance §5 —
`write_secret` audits `AuditAction.CREATE` on
`AuditResourceType.SECRET_REFERENCE` with `details={"reference": ref.render()}`;
`resolve_secret` audits ONLY on failure (`AuditStatus.FAILURE`, never the
value, never on success); delete audits the reference identity. `__init__.py`
re-exports the three ops only
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
- OAuth payload (encrypted at rest, decisions 3 and 4):
  `access_token_encrypted` Text nullable, `refresh_token_encrypted` Text
  nullable, `token_expires_at` DateTime(tz) nullable, `token_type`
  String(32) nullable, `granted_scopes` JSONB nullable (038 writes it
  already filtered to requested scopes)
- `encryption_key_id` String(16) nullable — first 16 hex chars of SHA-256
  over the root key string that encrypted the row; null when both token
  columns are null (decision 4)
- Secret reference (non-OAuth modes, §5): `secret_provider` String(32)
  nullable, `secret_name` String(255) nullable, `secret_version` String(64)
  nullable
- `principal_fingerprint` String(64) not null, **indexed non-unique**
  (D3 — dedup is detection, not constraint): HMAC-SHA256 hex over
  `"{provider_key}:{external_principal_id}"` keyed with the newest
  `praxis:principal-fingerprint:v1` purpose key (decision 4, via the
  Step 5 `compute_principal_fingerprint`)
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
- Encrypt/decrypt property pairs `access_token`/`refresh_token` in the
  `models/user.py:361-389` shape, but routed through the decision 4
  credential-token `MultiFernet` seam (Step 5) — NOT
  `encrypt_data`/`decrypt_data`. Plus `def crypto_shred(self)` nulling both
  encrypted columns and `encryption_key_id` and stamping `revoked_at`.

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
  `google_ads_account`, `airtable_base`)
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
(plain rows, decision 12), `__tablename__ = "integration_discovery_runs"`:

- `connection_id` UUID FK `integration_connections.id`
  `ondelete="CASCADE"` not null, indexed
- `job_id` UUID nullable (no FK — keeps the discovery log independent of
  the jobs table's retention; documented column comment)
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

### Step 4: Domain, manifest contract, plugin, loader, provider packages

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

`services/integrations/manifest.py` — **contract + registration only, no
provider entries** (decision 7): frozen dataclass
`IntegrationProviderManifest` with fields `provider_key: str`,
`display_name: str`, `auth_modes: tuple[str, ...]`,
`owner_scope: Literal["user", "workspace"]`,
`oauth_scopes: tuple[str, ...]`, `resource_types: tuple[str, ...]`,
`requires_discovery: bool`, `required_form_fields: tuple[str, ...]`
(api-key modes), `capability_flags: frozenset[str]`,
`event_delivery: Literal["none", "webhook", "pubsub_push"] = "none"`
(decision 14, data only). Module-level
`PROVIDER_MANIFESTS: dict[str, IntegrationProviderManifest]` built by a
`_register(manifest)` helper that runs registration-time invariant checks
(the `runtime_tool` shape, `registry.py:95`): duplicate `provider_key` →
`RuntimeError`; every `auth_mode` in the model CHECK vocabulary; oauth mode
⇒ non-empty `oauth_scopes`; api_key mode ⇒ non-empty
`required_form_fields`; `requires_discovery` ⇒ non-empty `resource_types`;
`provider_key` matches `^[a-z][a-z0-9_]*$`. Provider enablement is solely the
loader's shared allowlist, not a manifest field.

`services/integrations/plugin.py`: the `IntegrationProviderPlugin`
contract — `manifest` + `discover_resources` + `tool_definitions`, exactly
as `docs/architecture/integration-packaging.md` specifies. No other
attributes (decision 8: no `oauth_operations`).

`services/integrations/loader.py`: `load_enabled_providers()` imports
`integrations.{key}` for each entry in
`settings.INTEGRATIONS_ENABLED_PROVIDERS`, validates the packaging note's
§4.3 invariants, fails fast at boot on an unknown key or invalid package,
and registers each plugin's manifest (and, later, tools) into the singular
registries. Import laws per the note §4.6: engine code never imports
`integrations.*` directly except through the loader.

The three provider packages under `apps/api/integrations/` (D4;
manifest data only — operations, clients, and registry tools are 041's
scope):

- `gmail/` — auth_modes `("oauth",)`, owner_scope `"user"`,
  requires_discovery False (the mailbox is the principal), oauth_scopes =
  the Gmail readonly+send scopes (041 finalizes), event_delivery
  `"pubsub_push"`.
- `google_ads/` — `("oauth",)`, `"workspace"`, requires_discovery True
  (MCC→account hierarchy), resource_types `("google_ads_account",)`,
  event_delivery `"none"`.
- `airtable/` — `("api_key",)`, `"workspace"`, requires_discovery True,
  resource_types `("airtable_base",)`, required_form_fields `("api_key",)`,
  event_delivery `"webhook"`.

In `services/agents/runtime/tools/registry.py`, make `build_runtime_tools`
**lenient** on catalog-absent saved tool names (packaging note §4.7): skip
the tool, log, and record it in run metadata instead of raising
`ModelConfigurationError` (currently lines 124-132). Write-time validation
stays strict.

**Verify**: both loader smoke commands from the table (`[]` default;
`['airtable', 'gmail', 'google_ads']` with the three packages enabled); a
duplicate `_register` in a test raises `RuntimeError`; ruff exit 0.

### Step 5: Credential service + HTTP helper

Crypto seam (decision 4): add `derive_purpose_key(root: bytes,
purpose: str) -> bytes` (HKDF-SHA256) to `utils/security.py`. In
`services/integrations/utils.py`:

- an async cached accessor for the credential root keys — outside local,
  resolve the secret named `settings.CREDENTIAL_MASTER_KEY_SECRET_NAME`
  (version `latest`) through `services/secrets` once per process, never at
  import time; in local, fall back to `settings.CREDENTIAL_MASTER_KEYS`.
  Both yield a comma-separated list of Fernet keys, newest first.
- a `MultiFernet` builder over `praxis:credential-tokens:v1` purpose keys
  (one per root key, newest first; Fernet key = urlsafe-b64 of the 32-byte
  HKDF output) — the seam the `ExternalCredential` property pairs use —
  plus the `encryption_key_id` stamp helper (first 16 hex chars of SHA-256
  over the encrypting root key string).
- `compute_principal_fingerprint(provider_key, external_principal_id)` →
  HMAC-SHA256 hex over `f"{provider_key}:{external_principal_id}"` (via
  `utils/security.py::create_hmac_signature`, line 205) keyed with the
  newest `praxis:principal-fingerprint:v1` purpose key — NOT `SECRET_KEY`.

`services/integrations/http.py` (decision 10): `request_with_retries(
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
is a separate seam from `retrying_http_client()` (decision 10).

Credential ops (one per file, AGENTS.md). The package docstring notes the
decision 14 webhook-secret naming convention so the events plan finds one
seam, not two.

- `credentials/store_oauth_credential.py` —
  `store_oauth_credential(db, *, provider_key, token_payload,
  external_principal_id, external_principal_label, granted_scopes) ->
  ExternalCredential`: computes fingerprint, encrypts tokens via the
  property setters, stamps `token_expires_at` (the
  `services/auth/oauth/utils.py:305-312` expires_in pattern) and
  `encryption_key_id`, audits `CREATE` on `INTEGRATION_CREDENTIAL`
  (details: provider_key, fingerprint, scopes — never token values).
- `credentials/store_secret_reference_credential.py` — the api_key path:
  takes a `SecretReference` (already written by 038 via
  `services/secrets.write_secret`), persists reference columns only, CHECK
  guarantees no token columns. Fingerprint input for api-key mode is the
  provider-reported principal (Airtable whoami id — 041) or, until then,
  the secret name.
- `credentials/ensure_fresh_credential.py` — the locked proactive refresh
  (decision 9):

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

  then perform the token refresh through the generic manifest-driven
  token-endpoint call via `http.py` (038 wires the real provider OAuth
  client settings; this plan's tests exercise the path with the
  suite-local test provider and transport-mocked HTTP, decision 8), store
  the rotated tokens, restamp `encryption_key_id`, stamp
  `last_refreshed_at`, audit `UPDATE` (status SUCCESS). On refresh
  failure: increment `refresh_failure_count`, stamp
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
  (decision 13): validates the move against the domain transition map
  (invalid → `IntegrationConnectionError`), stamps
  `status`/`status_reason`/`status_changed_at`, audits `UPDATE` on
  `INTEGRATION_CONNECTION` with `{"from": ..., "to": ..., "reason": ...}`,
  and is a no-op (no audit spam) when the status is unchanged.

`services/jobs/handlers/rotate_credential_encryption.py` — the decision 4
sweep, registered as kind `integrations.rotate_credential_encryption` via
the `services/jobs/registry.py` decorator (follow the existing
`sweep_*` handler shape). Enqueued manually via `enqueue_job` (document
the command in the module docstring); no schedule.

`services/integrations/__init__.py` re-exports the ops only.

**Verify**: ruff exit 0;
`uv run python -c "from services.integrations import ensure_fresh_credential, transition_connection_status"`
imports; Step 7 tests pin the lock behavior and the rotation sweep.

### Step 6: Audit enum additions

Add to `AuditResourceType` (`services/audit_events/enums.py:26-42`):
`INTEGRATION_CONNECTION = "integration_connection"`,
`INTEGRATION_CREDENTIAL = "integration_credential"`,
`INTEGRATION_RESOURCE = "integration_resource"`,
`SECRET_REFERENCE = "secret_reference"`. No `AuditAction` additions —
CREATE/UPDATE/DELETE/EXECUTE cover every flow above.

**Verify**: `uv run pytest tests/services -q -k audit` (existing audit
tests still green); ruff exit 0.

### Step 7: Tests

`tests/factories/integrations.py`: `create_external_credential(...)`,
`create_integration_connection(...)` (defaults: the suite-local test
provider, oauth mode, workspace owner, label "Test connection"),
`create_integration_resource(...)` — the `tests/factories/` style, DB rows
via the shared session fixture.

The suite-local test provider (decision 8) lives under the test tree and
registers through the loader seam in fixtures only; provider HTTP
(token/userinfo/discovery endpoints) is mocked at the transport layer.

New modules (DB-backed ones skip cleanly without `TEST_DATABASE_URL`):

- `tests/integrations/test_import_laws.py` (no DB): the AST-walking §4.6
  import-law check from the packaging note. Provider-package tests live
  under `tests/integrations/<key>/`.
- `tests/services/integrations/test_manifest.py` (no DB): contract
  invariants — duplicate key raises `RuntimeError`; oauth-without-scopes
  and api_key-without-form-fields rejected; `is_provider_enabled` honors
  the gate.
- `tests/services/integrations/test_loader.py` (no DB): default empty
  `INTEGRATIONS_ENABLED_PROVIDERS` → empty registry; the three packages
  enabled → exactly `['airtable', 'gmail', 'google_ads']`; unknown key →
  fail-fast; the suite-local test provider registers through the seam.
- `tests/services/integrations/test_models.py` (DB): owner XOR CHECK
  (both/neither owner → IntegrityError); blank label rejected; status CHECK
  rejects unknown status; mode-payload CHECK (oauth row with secret_name
  fails; api_key row with token columns fails); **two live connections,
  same provider, same owner, different labels, both insert cleanly — the
  pinned D3 invariant with a comment saying a uniqueness "fix" is a
  regression**.
- `tests/services/integrations/test_credential_service.py` (DB): token
  encrypt/decrypt round-trip and ciphertext-at-rest (raw column value is
  not the plaintext); `encryption_key_id` stamped on store/refresh and
  nulled by shred; fingerprint is deterministic and equal across two
  connections of the same principal (`find_duplicate_principals` returns
  the sibling — cross-connection dedup, D3); refresh failure flips the
  connection to `needs_reauth`, increments `refresh_failure_count`, writes
  a FAILURE audit row, and **creates no notification row** (that is 039);
  `revoke_credential` crypto-shreds (both encrypted columns NULL,
  `revoked_at` set, connection `revoked`, audit row has no token material).
- `tests/services/integrations/test_encryption_rotation.py` (DB): with a
  two-key `CREDENTIAL_MASTER_KEYS` fixture, rows encrypted under the old
  key still decrypt; the sweep job re-encrypts every live row under the
  newest key and restamps `encryption_key_id` (afterwards every live row
  decrypts with ONLY the newest key — old keys droppable); fingerprints
  are unchanged by a `SECRET_KEY` change.
- `tests/services/integrations/test_refresh_locking.py` (DB): **the
  double-refresh serialization invariant** — two concurrent sessions call
  `ensure_fresh_credential` on the same expiring credential; assert the
  transport-mocked refresh endpoint is hit exactly once and both callers
  see the same rotated token (second session re-checks after the FOR
  UPDATE lock).
- `tests/services/integrations/test_status_transitions.py` (DB or unit on
  the map): every row of the Step 4 table allowed; `revoked → *` and other
  illegal moves raise `IntegrationConnectionError`; same-status call is a
  no-op with no audit row.
- `tests/services/integrations/test_http_retries.py` (no DB, mock
  transport): 429 with `Retry-After: 2` sleeps ~2 s not the backoff value
  (freeze/patch sleep); `Retry-After` above the cap is capped; attempts
  bounded at `INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS`; 401 maps to
  `IntegrationAuthError` without retry.
- `tests/services/secrets/test_local_secrets_provider.py`: env-var resolution;
  write→resolve round-trip through the encrypted file; file content on disk
  is not plaintext; missing secret raises `IntegrationAuthError` and writes
  a FAILURE audit row whose details contain the reference and **no value**.
- `tests/services/secrets/test_settings_gating.py` (no DB): building
  `Settings` with `SECRET_PROVIDER=local, ENVIRONMENT=production` raises;
  each cloud provider without its required project/vault/region setting raises;
  `CREDENTIAL_MASTER_KEYS` set outside local raises (construct Settings
  objects directly with overrides — the existing settings-validation test
  pattern).

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/integrations tests/services/secrets tests/integrations -q`
→ all pass; without the env var the DB modules skip, not fail;
`TEST_DATABASE_URL=... uv run pytest -q` → full suite green.

## Test plan

Covered by Step 7 (~30–36 tests). The pinned invariants: **no
double-refresh** (FOR UPDATE + re-check; exactly one refresh call under
concurrency), **fingerprint dedup detects and never blocks** (D3),
**crypto-shred at revoke** (ciphertext gone, metadata kept, audit clean of
values), **no per-provider uniqueness** (two labeled connections insert),
**owner XOR and non-blank label at the database layer**, **local secrets
and the local key fallback cannot leave local** (settings validator),
**rotation sweep converges** (after a sweep, every live row decrypts with
only the newest key), and **Retry-After honored, capped, and bounded**
(governance §4).

## Done criteria

- [x] `uv run ruff check .` exits 0
- [x] `uv run alembic check` reports no pending operations; the migration
      is on the **core** branch (D5) and downgrade round-trips
- [x] `TEST_DATABASE_URL=... uv run pytest -q` exits 0 (full suite)
- [x] Loader smoke prints `[]` with the default empty list and
      `['airtable', 'gmail', 'google_ads']` with the three packages
      enabled — both pinned by tests
- [x] Grep confirms NO unique index or constraint on
      `(owner_*, provider_key)` in `models/integrations.py` (D3)
- [x] Grep confirms no raw token/secret value appears in any audit
      `details` construction under `services/integrations/` or
      `services/secrets/`
- [x] Grep confirms no code under `services/integrations/` or
      `services/secrets/` reads `settings.ENCRYPTION_KEY` or signs with
      raw `SECRET_KEY` (decision 4)
- [x] The rotation sweep leaves no live row with a stale
      `encryption_key_id` (pinned by the two-key fixture test)
- [x] No `routes/integrations/` package exists (038's surface; this plan is
      backend-only and documented as pending)
- [x] `docs/architecture/governance.md` updated: §4 row "Integration API
      retries" → `[implemented: plan 037]`; §5 bullets for provider
      requirement, references-only storage, OAuth-tokens-encrypted, and
      resolve-failure auditing → `[implemented: plan 037]` (leave the §5
      rotation bullet and api-key connect exception marked for 038; §1 and
      §3 credential cells flip in 038/039 as their plans complete)
- [x] `git status` reviewed: concurrent rewrites of the next-plan docs 038/039
      appeared during verification and were left untouched; all other changes
      are plan-037 implementation, support, tests, or roadmap bookkeeping
- [x] `docs/plans/000_README.md` status row updated (add the 037 row if
      absent)

## STOP conditions

Stop and report back (do not improvise) if:

- Any table named `external_credentials`, `integration_connections`,
  `integration_resources`, or `integration_events` already exists, or
  `services/integrations/`, `services/secrets/`, or `apps/api/integrations/`
  already exist (someone started Phase 4a first).
- The core migration head has moved past `core_0012` — renumber against
  the real `core@head` and re-verify no landed migration claimed a
  conflicting table or index name.
- `utils/security.py` no longer provides
  `encrypt_data`/`decrypt_data`/`create_hmac_signature` with the cited
  signatures, or the `UserAuth` encrypted-property precedent has been
  refactored — reconcile the seam first.
- `SECRET_PROVIDER` has gained a code consumer since `63edba9`
  (`grep -rn "settings.SECRET_PROVIDER"` beyond `services/secrets/`) — the
  Literal narrowing in Step 1 is no longer free.
- `docs/architecture/governance.md` §3/§4/§5,
  `docs/architecture/integration-packaging.md`, or
  `docs/architecture/integration-events.md` defaults have changed from the
  values cited here — the notes win; reconcile before coding.
- The `num_nonnulls` CHECK or the expression CHECKs cannot be expressed in
  the installed SQLAlchemy/Alembic without raw DDL beyond
  `op.execute`/`sa.text` — report rather than silently dropping a
  constraint.
- You feel the need to add HTTP routes, job handlers beyond the decision 4
  sweep, notifications, or a real provider HTTP client — that is
  038/039/041 scope leaking in.

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
  duplicate-principal warnings), and a later inbound-events plan
  (`event_delivery`, webhook secret references, the reserved
  `integration_events` table — decision 14).
- **Root key rotation** (decision 4): prepend the new key to the
  credential-master-key secret (newest first), then enqueue
  `integrations.rotate_credential_encryption`; `encryption_key_id` makes
  progress a SQL query, and after a clean sweep the old keys are
  droppable. Fingerprints are NOT recomputed on rotation — dedup detection
  degrades gracefully for pre-rotation rows and heals at reconnect.
  `UserAuth`/TOTP remain on `ENCRYPTION_KEY` and its existing
  `_encryption_keys` rotation path — unrelated to this seam.
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
  that no test or fixture ever writes a real provider credential, and that
  the suite-local test provider never leaks into product code (import-law
  test).
