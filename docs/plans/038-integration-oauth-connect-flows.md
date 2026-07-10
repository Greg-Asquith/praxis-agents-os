# Plan 038: Integration OAuth connect flows and connection routes

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md` and flip the governance cells listed in
> "Done criteria" in `docs/architecture/governance.md`.
>
> **Notes pre-flight (run before Step 1)**: this plan implements slices of
> `docs/architecture/governance.md` §1 (connect/revoke role rows, API-key
> entry) and §5 (api-key connect exception, rotation re-test). Re-read
> those sections; the notes win over this plan.
>
> **Drift check (run first)**:
> `git diff --stat edc3abc..HEAD -- apps/api/routes/ apps/api/services/integrations/ apps/api/services/secrets/ apps/api/integrations/ apps/api/services/auth/oauth/ apps/api/core/auth/oauth_providers/ apps/api/middleware/csrf.py apps/api/core/rate_limiting.py apps/api/core/settings/ apps/api/core/dependencies.py apps/api/utils/security.py`
> The commit landing the 037 implementation is EXPECTED to appear
> (`services/integrations/`, `services/secrets/`, `integrations/`,
> `core/settings/integrations.py`, `utils/security.py`,
> `models/integrations.py`). Verify those files against the "Current
> state" excerpts below — they were re-verified with the 037
> implementation in the tree on 2026-07-10. Any OTHER in-scope change is
> a compare-before-proceeding event; on a mismatch with the excerpts,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH (a browser-facing OAuth surface plus an api-key intake
  path; state forgery, secret leakage, and RBAC mistakes are all
  security-grade failures)
- **Depends on**: 037 (hard, **DONE** — models, manifest + loader,
  credential service, secrets provider, status guard). Does NOT depend on
  030/031–036 (discovery enqueue is 039's).
- **Category**: Phase 4a integrations (roadmap `000_MASTER_ROADMAP.md` §4
  Phase 4a row 038; decisions D3, D4, D11)
- **Planned at**: commit `0cbbb39`, 2026-07-06. **Consolidated** at
  2026-07-10: plans 067 (PKCE + single-use state), 074 (rename route),
  080 (callback contract, verifier key purpose), and roadmap decision D11
  (no fake provider) folded into the body; anchors re-verified against
  the tree with the 037 implementation present (post-`edc3abc`).

## Decisions taken

1. **Signed single-value OAuth state.** ONE HS256 JWT carried entirely in
   the OAuth `state` parameter. Payload: `type="integration_oauth_state"`,
   `connection_id`, `provider_key`, `owner_scope`, `workspace_id` (acting
   workspace), `user_id`, validated relative `next_path`, `jti`, `iat`,
   `exp` (TTL 10 minutes). This is the mechanism the login flow already
   uses (`services/auth/oauth/utils.py:139` signs with `SECRET_KEY`,
   `verify_oauth_state` at 212 pins the `type` claim) — clone the pattern
   into `services/integrations/oauth/utils.py` with the
   integrations-specific `type` claim so login states and connect states
   can never be replayed across flows. Do NOT import from `services/auth`
   (cross-service imports are against local convention; the helper is
   ~40 lines).
2. **PKCE S256 on every authorization-code connect** (RFC 9700 / OAuth
   2.1). `start_oauth_connect` generates a `code_verifier` per RFC 7636
   (43–128 chars from a CSPRNG) and sends
   `code_challenge=BASE64URL(SHA256(verifier))` +
   `code_challenge_method=S256` on the authorization URL;
   `exchange_authorization_code` sends the `code_verifier` in the token
   POST. Any future OAuth-mode provider (e.g. Airtable, whose OAuth
   requires PKCE) inherits this unconditionally.
3. **Server-side pending-OAuth-state row, single-use.** New table
   `integration_oauth_states`: `jti` (PK, from the state JWT),
   `connection_id`, `code_verifier_encrypted`, `created_at`, `expires_at`
   (same TTL as the JWT). Created in `start_oauth_connect`'s transaction;
   consumed in `complete_oauth_callback` by one atomic
   `DELETE ... WHERE jti = :jti RETURNING ...` BEFORE the token exchange.
   No row (expired, swept, or replayed) → the invalid-state path:
   `IntegrationAuthError` + `INTEGRATION_OAUTH_STATE_INVALID` security
   event + error redirect. The signed JWT stays (authenticity, claims,
   cross-flow `type` pinning); its `jti` is the row key. The verifier is
   encrypted at rest under a dedicated HKDF purpose string
   `praxis:oauth-pkce-verifier:v1`, derived with `derive_purpose_key`
   (`utils/security.py:100`) over the credential root keys loaded by
   `ensure_credential_keys_loaded` (`services/integrations/utils.py`) —
   NEVER the credential-token purpose `praxis:credential-tokens:v1`. The
   verifier never rides the JWT: the state transits the browser signed
   but not encrypted, and a stolen state+code must not include the
   verifier.
4. **The callback is an API-side browser-redirected GET** —
   `GET /api/v1/integrations/oauth/callback` — unlike the login flow,
   where the SPA receives the redirect and POSTs the code back. Rationale:
   the connection row, credential write, scope filtering, and status
   transition are one server-side transaction, and a single registered
   provider redirect URI on the API keeps console configuration
   SPA-independent. Both outcomes are 302s to the frontend, never JSON:
   success redirects to `FRONTEND_URL + next_path` with
   `connection_id=<uuid>` and `status=<post-callback status>` query
   params appended; failure redirects with `integration_error=<code>`.
   042's OAuth-return alert consumes exactly these params — this is a
   pinned contract.
5. **CSRF posture — no exempt-list change.** `CSRFMiddleware` only
   enforces `POST/PUT/PATCH/DELETE` (`middleware/csrf.py:64-69`
   `_should_enforce_csrf`), so the GET callback is structurally outside
   CSRF enforcement and needs no entry in `exempt_paths` (`csrf.py:43-58`).
   Its anti-forgery guarantee is the signed state blob plus the
   single-use row — the OAuth `state` parameter is precisely a CSRF token
   for this flow. Every mutating integration route is an ordinary SPA
   `fetch` carrying `X-CSRF-Token` and stays fully enforced. A reviewer
   seeing `exempt_paths` touched should reject the PR.
6. **Rate limiting fail-closed on the browser-facing pair.** OAuth start
   (per user) and callback (per client IP via `get_client_ip`) go through
   the Postgres-backed limiter (`core/rate_limiting.py:68
   check_rate_limit`; wiring precedent at its caller, line 448) with
   integration-specific keys. Reuse existing auth-flow limit settings if
   a generic knob exists; otherwise conservative constants (e.g. 10/min
   start, 20/min callback) — record the choice in the PR description.
   The session-authenticated JSON routes rely on auth + RBAC as elsewhere.
7. **RBAC per governance §1**: user-scoped connect/revoke = member+
   (`require_editor`, `core/dependencies.py:268`); workspace-scoped
   connect/revoke and ALL api-key entry = admin+ (`require_owner`,
   line 267 — MANAGER_ROLES is owner+admin). Additionally, a user-owned
   connection may only be mutated by its `owner_user_id` (or a workspace
   admin acting where it was connected) — ownership check in the service
   op (`require_connection_mutation_allowed` helper), role check in the
   route dependency.
8. **The connection row is created at initiate time** in `auth_pending`,
   with its required `label` (D3) captured up front. `credential_id` is
   NOT NULL with a unique-per-live-connection index
   (`models/integrations.py:107-109,135-140`), so the start op creates
   the connection AND a stub `ExternalCredential`
   (`auth_mode='oauth'`, all token columns null — valid under the
   mode-payload CHECK — fingerprint `f"pending:{connection_id}"`) in one
   transaction; the callback replaces the stub atomically. A callback
   that never arrives leaves an inert `auth_pending` row; 039's sweep
   ages those out.
9. **api-key connect never persists or logs the raw value** (governance
   §5): request schema takes `api_key: SecretStr`; the service
   immediately calls `services/secrets.write_secret`, builds the
   credential via `store_secret_reference_credential` (reference columns
   only — the mode-payload CHECK makes token columns impossible), and
   the response/audit carry `reference.render()` only. The route also
   accepts a pre-existing `secret_reference` instead of a raw value
   (references-only API, §5) — exactly one of the two (model_validator
   XOR). A raw secret in any other request field is a validation error.
10. **Google-specific hard-won details**: auth URLs carry
    `include_granted_scopes=false`, `access_type=offline`,
    `prompt=consent` (the login provider already sets the latter two,
    `core/auth/oauth_providers/google.py:33-43`); persisted
    `granted_scopes` are the **intersection** of the token response
    `scope` field with the manifest's requested scopes — never whatever
    extra the user granted.
11. **Separate OAuth clients for integrations.** New settings
    `INTEGRATIONS_GOOGLE_CLIENT_ID` / `INTEGRATIONS_GOOGLE_CLIENT_SECRET`
    / `INTEGRATIONS_OAUTH_REDIRECT_URI` — NOT the login client
    (`GOOGLE_OAUTH_CLIENT_ID`, `core/settings/auth.py:27-32`). Login and
    integration consent screens have different scopes, brand verification
    requirements, and blast radius; local dev may set both to the same
    values. `INTEGRATIONS_OAUTH_REDIRECT_URI` must be `https` outside
    `ENVIRONMENT=local` — enforced in the production-safety
    `model_validator` (`core/settings/__init__.py:58`, the
    `local_fs`/`console` pattern at 66-70); empty remains allowed
    (provider unconfigured).
12. **Enablement vs configuration are two separate gates.** As delivered
    by 037, a provider EXISTS only if its package is named in
    `INTEGRATIONS_ENABLED_PROVIDERS` (the loader,
    `services/integrations/loader.py:12`, runs at tools-registry import —
    `registry.py:279-286`; the manifest carries no per-provider enable
    flag). This plan adds the CONFIGURED dimension: `list_providers`
    reports each loaded manifest with a `configured` boolean derived from
    settings (Google-family → `INTEGRATIONS_GOOGLE_CLIENT_ID` and
    `INTEGRATIONS_OAUTH_REDIRECT_URI` non-empty; api-key providers are
    always configured), and `start_oauth_connect` rejects an
    unconfigured provider with `IntegrationValidationError`. 042 renders
    unconfigured providers muted; 041 extends the same idea to tool
    availability.
13. **Post-callback status**: providers with
    `manifest.requires_discovery=True` transition to `discovery_pending`;
    039 wires the job enqueue at a named seam
    (`# discovery enqueue seam — plan 039` comment in the callback
    service op). Until 039 lands, such connections honestly sit in
    `discovery_pending`. Providers without discovery go straight to
    `active`. All transitions flow through `transition_connection_status`
    (037's single guard).
14. **Revoke is best-effort remote, guaranteed local**: call the
    provider's revoke endpoint through
    `services/integrations/http.py::request_with_retries` and ignore
    failures (the login precedent logs-and-continues,
    `core/auth/oauth_providers/google.py:88-99`), then ALWAYS
    `revoke_credential` (crypto-shred) and transition to `revoked`.
15. **Duplicate-principal warning, never a block** (D3): the callback
    result and the connection detail payload include
    `duplicate_of_connection_ids` from `find_duplicate_principals` so
    042 can warn; connecting the same Gmail account twice under two
    labels is a supported flow.
16. **Rename is a first-class route** (D3 label editing):
    `PATCH /integrations/connections/{connection_id}` with body
    `{label}` (non-empty, same schema rule as connect), auth
    `require_editor` + `require_connection_mutation_allowed` (label
    surgery is not credential surgery). Audits one UPDATE with old/new
    label; no status transition, no credential access.
17. **Tests prove the flow against a suite-local test provider** (D11):
    the OAuth service ops are purely generic manifest-driven — no
    provider-specific dispatch arms beyond URL/endpoint constants for
    the Google family. Test fixtures register a test provider manifest
    through the registry seam (the `test_manifest_loader.py` pattern)
    and mock its authorize/token/userinfo endpoints at the transport
    layer (`httpx2.MockTransport`). No test-only code ships in product
    modules.

## Superseded decisions

Recorded so they are not re-proposed; full history in
`docs/plans/complete/{067,074,080}-*.md` and roadmap decision D11.

- **Fake provider arms** (original decisions 1/9 wording, fake-consent
  redirect, in-process token short-circuits, `oauth_operations` plugin
  seam) — removed by D11; the generic manifest-driven flow is the only
  token path, proven against the suite-local test provider.
- **"No server-side state row"** (original decision 1) — superseded by
  plan 067: the signed JWT stays, but single-use consumption and the
  PKCE verifier require the `integration_oauth_states` row.
- **"No migration in this plan"** — superseded by plan 067: exactly one
  migration (`integration_oauth_states`) is allowed. Anything beyond it
  remains a STOP.
- **Manifest `enabled_setting` gate** (original Step 1 "flip
  gmail/google_ads `enabled_setting`") — the delivered 037 manifest has
  no such field and no `is_provider_enabled`; enablement is the loader
  allowlist alone. Decision 12 defines the replacement `configured`
  surface.
- **Nine routes** — superseded by plan 074/080: ten routes including
  rename (decision 16).

## Why this matters

037 built the vault; nothing can get into it yet. This plan is the write
path: the browser OAuth dance and the api-key intake, plus the
test/refresh/revoke/rename lifecycle routes the UI (042) and ops flows
need. It is the platform's second browser-redirected surface after login
OAuth, and the first that accepts customer secrets — the reason the state
blob, PKCE, CSRF posture, scope filtering, and never-store-raw-keys
invariants are pinned by tests here rather than reviewed by hope.
Everything downstream (039 discovery, 040 context, 041 operations)
assumes connections created through these flows are correctly labeled,
scoped, deduplicated-by-warning, and auditable.

## Current state

Anchors verified 2026-07-10 against the tree with the 037 implementation
present.

- **037 delivered** (consume, don't rebuild):
  - `models/integrations.py` — `ExternalCredential` (encrypted token
    properties, `crypto_shred()` at 90, mode-payload CHECK at 53-59,
    `granted_scopes`, `principal_fingerprint`), `IntegrationConnection`
    (label CHECK, owner XOR CHECK, status CHECK, unique live credential
    index — 120-154), `IntegrationResource`, `IntegrationDiscoveryRun`.
  - `services/integrations/` — `manifest.py` (`PROVIDER_MANIFESTS`,
    `register_provider_manifest`, frozen dataclass with `auth_modes`,
    `owner_scope`, `oauth_scopes`, `resource_types`,
    `requires_discovery`, `required_form_fields`, `event_delivery`);
    `loader.py:12 load_enabled_providers` (allowlist import, invoked at
    `tools/registry.py:279-286`); `domain.py` status vocabulary +
    transition map; `http.py::request_with_retries(method, url, *,
    operation, provider_key, **kwargs)` (Retry-After aware, typed
    errors); `utils.py` (`ensure_credential_keys_loaded`,
    `encrypt_credential_token`/`decrypt_credential_token`,
    `compute_principal_fingerprint`, `record_integration_audit`,
    purposes `praxis:credential-tokens:v1` /
    `praxis:principal-fingerprint:v1`);
    `connections/transition_connection_status.py` —
    `transition_connection_status(db, connection, status, *,
    reason=None)`, same-status no-op; `credentials/` ops:
    `store_oauth_credential(db, *, provider_key, token_payload,
    external_principal_id, external_principal_label, granted_scopes)`,
    `store_secret_reference_credential`, `ensure_fresh_credential(db, *,
    credential_id, refresh_token: RefreshTokenFn | None = None)` (row
    lock + post-lock re-check; THIS plan supplies the manifest-driven
    refresh callable per its docstring), `revoke_credential`,
    `find_duplicate_principals`.
  - `services/secrets/` — `write_secret`, `resolve_secret`,
    `delete_secret`; `domain.py::SecretReference(provider, name,
    version)` with `.render()` → `"provider:name#version"`.
  - `integrations/{gmail,google_ads,airtable}/__init__.py` — data-only
    `PROVIDER: IntegrationProviderPlugin` packages (manifests only;
    `discover_resources=None`). gmail: oauth/user-scope/2 scopes;
    google_ads: oauth/workspace/adwords scope/`requires_discovery`;
    airtable: api_key/workspace/`required_form_fields=("api_key",)`.
  - Settings: `core/settings/integrations.py` —
    `INTEGRATIONS_ENABLED_PROVIDERS: list[str] = []`, token-refresh
    leeway, HTTP timeout/retry knobs, `CREDENTIAL_MASTER_KEY_SECRET_NAME`,
    `CREDENTIAL_MASTER_KEYS` (local-only). `utils/security.py:100
    derive_purpose_key`.
  - Audit resource types exist: `INTEGRATION_CONNECTION`,
    `INTEGRATION_CREDENTIAL`, `INTEGRATION_RESOURCE`,
    `SECRET_REFERENCE` (`services/audit_events/enums.py`).
  - Core migration head: `core_0013`
    (`alembic/versions/core/0013_add_integration_core_tables.py`) —
    this plan's migration is `core_0014`.
- **Login OAuth precedents** (clone, don't import):
  `services/auth/oauth/utils.py` — `create_oauth_state` (139; HS256 over
  `SECRET_KEY`, `jti`, 10-minute TTL const at 32), `verify_oauth_state`
  (212; decode, expiry/invalid → `OAuthAuthenticationError`, `type`
  claim pinned, completeness check), `resolve_provider_redirect_uri`
  (243: supplied URI must equal the configured one), `safe_next_path`
  (262: relative-path-only). Route/service split precedent:
  `routes/auth/create_oauth_authorization_url.py` (thin) →
  `services/auth/oauth/create_oauth_authorization_url.py`.
- **Google endpoints**: `core/auth/oauth_providers/google.py` — auth URL
  params (33-43), token exchange (45-58), refresh (74-86), revoke
  (88-99). Integration flows re-declare the endpoint URLs locally and
  call them through `services/integrations/http.py` — never instantiate
  the login-registry classes.
- **CSRF**: `middleware/csrf.py` — `_should_enforce_csrf` (64-69: GET
  never enforced), exempt list (43-58: login OAuth POSTs are pre-auth
  exemptions; integration routes are post-auth and need none),
  `_record_rejection` (119: dedicated committed session, never turns a
  rejection into a 500), dispatch (146).
- **Rate limiting**: `core/rate_limiting.py:68 check_rate_limit`
  (Postgres-backed), `get_client_ip` (imported by the CSRF middleware,
  `csrf.py:15`), caller precedent at line 448.
- **RBAC**: `require_role` (`core/dependencies.py:243`), `require_owner`
  (267, MANAGER_ROLES), `require_editor` (268), `require_read` (269);
  workspace resolution via `X-Workspace`.
- **Router composition**: `routes/__init__.py:8-37` — feature routers
  imported and included alphabetically; `integrations` slots between
  `files` and `models`. A new `routes/integrations/__init__.py` composes
  operation-module routers only.
- **Security events**: `services/security/enums.py:13` —
  `SecurityEventType` (AUTH_OAUTH_* at 20-22; nothing
  integration-specific yet).
- **Exceptions**: `core/exceptions/integration.py` —
  `IntegrationConnectionError` (91), `IntegrationAuthError` (98, → 401),
  `IntegrationValidationError` (126), etc. Raise these, never ad-hoc.
- **Notifications**: none emitted here (governance §6 assigns
  integration notifications to 039).
- **Tests**: `tests/support/settings.py:25` already seeds
  `CREDENTIAL_MASTER_KEYS`; suite-local provider registration pattern in
  `tests/services/integrations/test_manifest_loader.py`; factories in
  `tests/factories/integrations.py` (`build_external_credential`,
  `build_integration_connection`, `build_integration_resource`).
- Frontend contract note: the SPA calls via `src/lib/api/client.ts`
  (credentials + CSRF + `X-Workspace`); 042 builds the UI. No web
  changes in this plan.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | clean after Step 1 (exactly one new migration: `integration_oauth_states`) |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/routes/integrations tests/services/integrations -q` | all pass |
| Full API tests | `TEST_DATABASE_URL=... uv run pytest -q` | all pass |
| Route smoke | `uv run python -c "from routes import api_router; print(sorted({r.path for r in api_router.routes if '/integrations' in r.path}))"` | the ten Step 5 paths |

## Scope

**In scope:**

- `apps/api/alembic/versions/core/0014_*.py` (create —
  `integration_oauth_states`, decision 3) + `models/integrations.py`
  (add the model) + `models/__init__.py`
- `apps/api/core/settings/integrations.py` (extend — decision 11
  settings: `INTEGRATIONS_GOOGLE_CLIENT_ID: str = ""`,
  `INTEGRATIONS_GOOGLE_CLIENT_SECRET: SecretStr = SecretStr("")`,
  `INTEGRATIONS_OAUTH_REDIRECT_URI: str = ""`,
  `INTEGRATIONS_OAUTH_STATE_TTL_MINUTES: int = 10`) +
  `core/settings/__init__.py` (decision 11 validator clause)
- `apps/api/services/integrations/oauth/` (create): `__init__.py`,
  `utils.py` (state mint/verify, verifier encrypt/decrypt),
  `build_authorization_url.py`, `exchange_authorization_code.py`,
  `fetch_external_principal.py`
- `apps/api/services/integrations/connections/` (extend, one op per
  file): `start_oauth_connect.py`, `complete_oauth_callback.py`,
  `connect_api_key.py`, `list_connections.py`, `get_connection.py`,
  `rename_connection.py`, `test_connection.py`, `refresh_connection.py`,
  `revoke_connection.py`, `utils.py` (ownership helpers), `schemas.py`
- `apps/api/services/integrations/providers_view.py` or equivalent op
  backing `list_providers` (manifest + `configured`, decision 12)
- `apps/api/routes/integrations/` (create, route-per-file): the ten
  Step 5 operations + `__init__.py` + registration in
  `routes/__init__.py`
- `apps/api/services/security/enums.py` (add
  `INTEGRATION_OAUTH_STATE_INVALID = "integration_oauth_state_invalid"`)
- `apps/api/tests/routes/integrations/` (create),
  `apps/api/tests/services/integrations/test_oauth_state.py` (create)

**Out of scope (do NOT touch):**

- Any migration beyond `integration_oauth_states` — needing another
  column is a STOP.
- Discovery job enqueue/handlers, sweeps, notifications, resource
  selection routes — 039 (leave only the named seam comment,
  decision 13).
- Active context — 040. Real provider operations and data-plane clients
  (Gmail messages, Ads services, Airtable records) — 041; this plan
  touches only auth-protocol endpoints
  (authorize/token/revoke/whoami-class identity lookups).
- UI — 042.
- `middleware/csrf.py` `exempt_paths` (decision 5 — MUST remain
  untouched), `services/auth/**`, `core/auth/oauth_providers/**`.

## Git workflow

- Branch: `advisor/038-integration-oauth-connect-flows`
- Commit style: `API - Integration OAuth Connect Flows`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `integration_oauth_states` migration

Add the model (decision 3) to `models/integrations.py`: `jti`
String(64) PK, `connection_id` UUID FK
`integration_connections.id ondelete="CASCADE"` not null indexed,
`code_verifier_encrypted` Text not null, `created_at`/`expires_at`
timestamptz not null. Generate on the core branch
(`--head core@head --version-path alembic/versions/core`), numbered
`core_0014`.

**Verify**: `uv run alembic upgrade heads` applies; `uv run alembic
check` clean; downgrade/upgrade round-trips.

### Step 2: Settings + validator + configured flag

Add the decision 11 fields to `IntegrationsSettingsMixin`. Extend the
production-safety `model_validator` (`core/settings/__init__.py:58`,
following the local-only pattern at 66-70): non-local +
`INTEGRATIONS_OAUTH_REDIRECT_URI` set + not `https://` → raise. Add the
decision 12 `configured` helper where the manifest view op can reach it
(service-level `utils.py`, driven by settings + `auth_modes` — no
manifest schema change).

**Verify**: settings import prints defaults; validator test — non-local
env + `http://` redirect URI raises; ruff exit 0.

### Step 3: State blob + verifier utilities

`services/integrations/oauth/utils.py`, cloning the
`services/auth/oauth/utils.py:139,212,262` shapes:

```python
def create_integration_oauth_state(*, connection_id, provider_key, owner_scope,
                                   workspace_id, user_id, next_path) -> str: ...
def verify_integration_oauth_state(state: str) -> dict[str, Any]: ...
def safe_next_path(next_path: str | None) -> str | None:  # auth's relative-only rule
async def encrypt_code_verifier(db, verifier: str) -> str: ...
async def decrypt_code_verifier(db, ciphertext: str) -> str: ...
```

- HS256 over `settings.SECRET_KEY`, `type="integration_oauth_state"`
  pinned on verify, `exp` from `INTEGRATIONS_OAUTH_STATE_TTL_MINUTES`,
  `jti` keys the pending row (decision 3).
- Verifier crypto: `derive_purpose_key(root,
  "praxis:oauth-pkce-verifier:v1")` per root key from
  `ensure_credential_keys_loaded`, MultiFernet newest-first — the exact
  shape of `encrypt_credential_token`/`decrypt_credential_token` with a
  different purpose.
- Verification failures raise `IntegrationAuthError`
  (`core/exceptions/integration.py:98`) with `operation="oauth_state"`;
  the caller records `INTEGRATION_OAUTH_STATE_INVALID` before
  re-raising (Step 6). Required claims checked explicitly — missing →
  invalid.

**Verify**: `tests/services/integrations/test_oauth_state.py` (Step 8)
round-trips, expires, tamper-rejects; a verifier ciphertext does NOT
decrypt under the credential-token subkey (purpose separation pinned);
ruff exit 0.

### Step 4: OAuth protocol ops + connect services

`services/integrations/oauth/` protocol ops (one per file), purely
generic manifest-driven; `gmail`/`google_ads` share the Google endpoints
(URL constants re-declared locally from
`core/auth/oauth_providers/google.py:28-31`); `airtable` has no OAuth
mode in v1:

- `build_authorization_url.py` — Google family:
  `client_id=INTEGRATIONS_GOOGLE_CLIENT_ID`,
  `redirect_uri=INTEGRATIONS_OAUTH_REDIRECT_URI`, `response_type=code`,
  `scope=" ".join(manifest.oauth_scopes)`, `state=<blob>`,
  `code_challenge` + `code_challenge_method=S256` (decision 2),
  `access_type=offline`, `prompt=consent`,
  **`include_granted_scopes=false`** (decision 10).
- `exchange_authorization_code.py` — token POST (with `code_verifier`)
  via `request_with_retries`; validates the payload the way
  `_parse_token_payload` does
  (`core/auth/oauth_providers/retrying.py:28-49`: 200-with-error and
  missing access_token are failures).
- `fetch_external_principal.py` — stable external principal id + label
  for fingerprinting: Google userinfo `sub`/`email` for gmail; for
  google_ads, the authenticating Google identity at connect time (the
  MCC/account hierarchy is discovery data, 039/041).

Connection service ops (`services/integrations/connections/`, one per
file):

- `start_oauth_connect.py` — validate the manifest (provider loaded,
  configured per decision 12, `oauth` in `auth_modes`, owner_scope
  matches the request; workspace-scoped additionally admin+ per
  decision 7), validate the non-empty label; create the connection in
  `auth_pending` + the stub credential (decision 8) + the
  `integration_oauth_states` row (jti, encrypted verifier) in one
  transaction. Returns `{authorization_url, state, connection_id}`.
  Accepts an optional existing `connection_id` for re-auth of a
  `needs_reauth` connection (042's re-authenticate CTA). Audits CREATE
  on `INTEGRATION_CONNECTION`.
- `complete_oauth_callback.py` — verify state (Step 3); atomically
  consume the pending row by `jti` (no row → invalid-state path,
  decision 3); load the `auth_pending` connection from the
  `connection_id` claim (missing/not-pending →
  `IntegrationConnectionError`); exchange the code with the decrypted
  verifier; fetch the principal; **filter granted scopes** to the
  manifest set (decision 10); write the real credential via
  `store_oauth_credential` and swap `credential_id` (delete the stub);
  compute `duplicate_of_connection_ids`; transition per decision 13
  with the `# discovery enqueue seam — plan 039` comment; audit UPDATE
  with scopes + fingerprint (no tokens). On provider `error` query
  param or exchange failure: audit FAILURE, record the security event,
  leave `auth_pending`, redirect with `integration_error=<code>`.
- `connect_api_key.py` (decision 9) — admin+ only; schema with `label`,
  `provider_key`, and exactly one of `api_key: SecretStr | None` /
  `secret_reference` (XOR). Raw path:
  `write_secret(name=f"integrations-{provider_key}-{uuid4().hex}", ...)`
  then `store_secret_reference_credential`; reference path: store as
  given (resolution proves it at test time). Creates the connection
  directly in `discovery_pending`/`active` (no auth_pending leg).
  Response and audit contain `reference.render()` only.
- `list_connections.py` / `get_connection.py` — workspace-owned rows for
  the acting workspace + user-owned rows for the requesting user; detail
  includes the credential **metadata** block for admin+ only (expiry,
  scopes, fingerprint, last refresh — never values or resolved
  references; member view omits the block); includes
  `duplicate_of_connection_ids`.
- `rename_connection.py` — decision 16.
- `test_connection.py` — resolves a working credential
  (`ensure_fresh_credential` with the manifest-driven refresh callable
  for oauth; `resolve_secret` for references — §5 rotation re-test lives
  here) and performs the manifest's cheap identity call (Google:
  userinfo). Success → audit; auth failure → transition `needs_reauth`,
  typed error.
- `refresh_connection.py` — forces `ensure_fresh_credential` regardless
  of leeway; surfaces the refreshed expiry.
- `revoke_connection.py` — decision 14. Ownership rules per decision 7
  (`utils.py::require_connection_mutation_allowed(connection, user,
  membership)`).

**Verify**: ruff exit 0; service-level tests (Step 8) pass against the
suite-local test provider with transport-mocked provider HTTP.

### Step 5: Routes

`routes/integrations/` (route-per-file; `__init__.py` composes only),
prefix `/integrations`, registered in `routes/__init__.py` between
`files` and `models`:

| File | Operation | Auth |
|------|-----------|------|
| `list_providers.py` | `GET /integrations/providers` — loaded manifests + `configured` (decision 12) | `require_read` |
| `list_connections.py` | `GET /integrations/connections` | `require_read` |
| `get_connection.py` | `GET /integrations/connections/{connection_id}` | `require_read` (credential metadata admin+ only) |
| `start_oauth_connect.py` | `POST /integrations/connections/oauth/start` | `require_editor`; workspace-scoped providers additionally admin+ (service check) |
| `oauth_callback.py` | `GET /integrations/oauth/callback?code&state[&error]` | **no session dependency** — identity from the signed state; rate-limited; returns `RedirectResponse` |
| `connect_api_key.py` | `POST /integrations/connections/api-key` | `require_owner` (admin+) |
| `rename_connection.py` | `PATCH /integrations/connections/{connection_id}` | `require_editor` + ownership rule |
| `test_connection.py` | `POST /integrations/connections/{connection_id}/test` | `require_editor` + ownership rule |
| `refresh_connection.py` | `POST /integrations/connections/{connection_id}/refresh` | `require_editor` + ownership rule |
| `revoke_connection.py` | `POST /integrations/connections/{connection_id}/revoke` | `require_editor` + ownership rule (user-scoped own; workspace-scoped admin+) |

Route modules stay thin: parse, call the service op, return the schema.
The callback route wraps the service in the redirect contract
(decision 4): success and failure BOTH end in a 302.

**Verify**: route smoke lists all ten paths; existing route tests still
green (`uv run pytest tests/routes -q`).

### Step 6: Security events + rate limiting

- Add `INTEGRATION_OAUTH_STATE_INVALID` to `SecurityEventType` and
  record it (with `jti` when decodable, IP, endpoint) on every state
  verification failure AND every pending-row-miss (replay/expiry) — the
  CSRF middleware's `_record_rejection` pattern (`csrf.py:119`).
- Wire `check_rate_limit` into `start_oauth_connect` (per user) and
  `oauth_callback` (per client IP), fail-closed (decision 6).

**Verify**: a tampered-state request produces exactly one
`security_events` row with the new type; repeated callbacks past the
limit → 429 problem+json.

### Step 7: Audit sweep

Confirm every mutating op writes exactly one audit row (CREATE on start
and api-key connect; UPDATE on callback complete, rename, test, refresh;
DELETE on revoke — resource `INTEGRATION_CONNECTION`, with credential
events from 037's ops beneath). Confirm no audit `details`, log call, or
exception message interpolates a token, api key, or resolved secret —
grep for `api_key`, `access_token`, `refresh_token`, `get_secret_value`
in `details=` and log format args under `services/integrations/`.

**Verify**: `TEST_DATABASE_URL=... uv run pytest
tests/routes/integrations -q` green; the Step 8 never-stored test passes.

### Step 8: Tests

`tests/services/integrations/test_oauth_state.py` (no DB): mint→verify
round-trip preserves claims; expired state rejected; **tamper
rejection** — flip one character → `IntegrationAuthError`; a login-flow
state (`type="oauth_state"`) is rejected by the integrations verifier
(cross-flow replay pinned); `safe_next_path` rejects absolute URLs and
schemes; verifier purpose separation (Step 3 verify).

`tests/routes/integrations/` (DB-backed; suite-local test provider
registered in fixtures via the manifest-registry seam; its
authorize/token/userinfo endpoints mocked with `httpx2.MockTransport`):

- `test_oauth_connect_flow.py`: start (member) → connection
  `auth_pending` with label + pending state row; callback with valid
  state → credential stored encrypted, scopes filtered to the manifest
  set (mocked token response grants a superset; assert intersection
  persisted), status per decision 13, 302 to
  `FRONTEND_URL + next_path` **with `connection_id` and `status`
  params**; authorization URL contains `include_granted_scopes=false`
  AND `code_challenge`/`method=S256`; the mocked token exchange fails
  on a mismatched verifier and succeeds on the correct one (PKCE
  relation pinned); **replay** — a second callback with the same valid
  state → error redirect, security event, no second credential; expired
  pending row → same rejection even with an unexpired JWT; tampered
  state → error redirect, no credential, security event row; second
  connect of the same principal under a new label succeeds AND reports
  the sibling in `duplicate_of_connection_ids` (D3).
- `test_api_key_connect.py`: **api-key-never-stored** — connect with a
  raw key; assert the plaintext appears nowhere in
  `external_credentials`, `integration_connections`, `audit_events`
  (full-row scans), the response body (reference only), or captured
  logs (`caplog`); reference-only variant accepted; member (non-admin)
  → 403; malformed reference → 400 problem+json.
- `test_connection_lifecycle_routes.py`: test/refresh/revoke/rename
  happy paths; refresh with the mocked token endpoint returning 4xx for
  a poisoned refresh token → connection `needs_reauth`; revoke → token
  columns NULL (crypto-shred), status `revoked`, provider revoke
  failure does not block local revoke; revoked connection rejects
  test/refresh (transition guard); rename audits old/new label; blank
  label 400.
- `test_rbac_and_csrf_posture.py`: RBAC matrix — member can start a
  user-scoped connect, cannot start workspace-scoped (403), cannot
  enter api keys (403); read_only can list but not mutate; a non-owner
  member cannot revoke/rename another user's user-scoped connection;
  **CSRF posture** — POST routes without `X-CSRF-Token` under a session
  cookie → 403 from the middleware, while the GET callback succeeds
  with no CSRF token; and a source-level assertion that
  `middleware/csrf.py` `exempt_paths` contains no `/integrations` entry.

**Verify**: `TEST_DATABASE_URL=... uv run pytest
tests/routes/integrations tests/services/integrations -q` → all pass;
skips (not failures) without the env var; full suite green.

## Test plan

Covered by Step 8 (~28–34 tests). The pinned invariants: **state-blob
tamper, cross-flow replay, and single-use replay rejection**, **PKCE
S256 on auth URL and token exchange with verifier purpose separation**,
**the raw api key is unrecoverable from every persistence surface and
log**, **persisted scopes ⊆ requested scopes** and
`include_granted_scopes=false`, **multi-connection with
duplicate-principal warning, never a block** (D3), **crypto-shred on
revoke regardless of provider-side failure**, and **CSRF enforcement
untouched**.

## Done criteria

- [ ] `uv run ruff check .` exits 0; `uv run alembic check` clean with
      exactly one new migration (`integration_oauth_states`)
- [ ] `TEST_DATABASE_URL=... uv run pytest -q` exits 0 (full suite)
- [ ] Route smoke lists exactly the ten Step 5 paths
- [ ] `git diff middleware/csrf.py` is empty (decision 5)
- [ ] State replay rejected and PKCE pinned on auth URL + token exchange
      (tests green)
- [ ] Grep shows `get_secret_value` under
      `services/integrations/connections/` only at the write_secret call
      site
- [ ] `docs/architecture/governance.md` updated: §1 rows "Connect/revoke
      own user-scoped integrations (037–038)", "Connect/revoke
      workspace-scoped integrations (037–038)", "Enter API keys / secret
      references (037)" → `[implemented: plan 038]`; §5 api-key-connect
      exception bullet and rotation re-test bullet → `[implemented: plan
      038]`; §1 credential-metadata row → `[implemented (API): plan 038]`
      (042 owns the UI half)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The delivered 037 contract differs from the "Current state" excerpts
  (e.g. `credential_id` became nullable, the status vocabulary changed,
  `store_oauth_credential`'s signature moved, or
  `derive_purpose_key`/`ensure_credential_keys_loaded` are absent) —
  reconcile against the landed code first.
- The login OAuth utilities have moved or changed shape
  (`services/auth/oauth/utils.py` state functions, `safe_next_path`) —
  the Step 3 clone was written against those lines.
- `middleware/csrf.py`'s method gate (`_should_enforce_csrf`, 64-69)
  now enforces GETs — decision 5's justification collapses; redesign
  the callback posture before coding.
- A `routes/integrations/` package already exists.
- You cannot complete the connect handshake generically without
  implementing data-plane API calls — ship the generic flow proven
  against the suite-local test provider and STOP on the real-provider
  gap (real-provider live connects are 041-adjacent territory; manual
  QA uses real dev credentials — Airtable's API key is the cheapest).
- You feel the need to widen `exempt_paths`, add a second migration,
  enqueue a job, or send a notification — 037/039 boundaries leaking.

## Maintenance notes

- **Consumers**: 039 replaces the `# discovery enqueue seam — plan 039`
  comments with `enqueue_discovery(...)` and owns everything after
  `discovery_pending`; its sweep also purges expired
  `integration_oauth_states` rows and stale `auth_pending` connections.
  040 resolves active context across the N connections these routes
  create (D3). 041 extends `fetch_external_principal` for Airtable
  whoami and adds real provider operations. 042 builds provider cards,
  connect dialogs (label required — D3), inline rename, the
  re-authenticate CTA (start with `connection_id`), and the
  duplicate-principal warning.
- **Redirect URI discipline**: `INTEGRATIONS_OAUTH_REDIRECT_URI` must
  exactly match the provider console value; the callback never accepts
  a caller-supplied redirect (state carries only a relative
  `next_path`) — keep it that way.
- **Provider registries stay separate**: login providers
  (`core/auth/oauth_providers/`) authenticate humans; the integrations
  manifest authorizes data access. A future consolidation must not let
  a login client mint integration credentials (different client ids,
  decision 11).
- Reviewers should scrutinize: the callback's transaction boundaries
  (pending-row consume + credential swap + status transition commit
  atomically or roll back to `auth_pending`), the stub-credential
  fingerprint never colliding with a real one (`pending:` prefix),
  SecretStr handling in `connect_api_key` (no `repr` leaks), the
  verifier never appearing in the JWT or logs, and that both callback
  outcomes are redirects, never JSON.
