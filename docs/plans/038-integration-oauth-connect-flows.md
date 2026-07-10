# Plan 038: Integration OAuth connect flows and connection routes

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md` and flip the governance cells listed in
> "Done criteria" in `docs/architecture/governance.md`.
>
> **Governance pre-flight (run before Step 1)**: this plan implements slices
> of `docs/architecture/governance.md` §1 (connect/revoke role rows, API-key
> entry) and §5 (api-key connect exception, rotation re-test). Re-read those
> sections; the note wins over this plan.
>
> **Amendment (plan 067) pre-flight**: the "Amendment (plan 067,
> 2026-07-07)" block at the end of this file amends decisions 1/9 and
> Steps 1/2/3/7; where it conflicts with the body above, the amendment
> wins.
>
> **Amendment (plan 074) pre-flight**: the "Amendment (plan 074,
> 2026-07-07)" block at the end of this file amends this plan; where it
> conflicts with the body above, the amendment wins.
>
> **Amendment (plan 080) pre-flight**: the "Amendment (plan 080,
> 2026-07-10)" block at the end of this file amends this plan (route
> count, callback success params, PKCE verifier key purpose); where it
> conflicts with the body above or the earlier amendments, it wins.
>
> **Amendment (decision D11) pre-flight**: the "Amendment (decision D11,
> 2026-07-10)" block at the end of this file removes every fake-provider
> arm — the OAuth service is purely generic manifest-driven; tests use a
> suite-local test provider with transport-mocked endpoints. Where it
> conflicts with the body above or any earlier amendment, it wins.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/routes/ apps/api/services/integrations/ apps/api/services/secrets/ apps/api/services/auth/oauth/ apps/api/core/auth/oauth_providers/ apps/api/middleware/csrf.py apps/api/core/rate_limiting.py apps/api/core/settings/ apps/api/core/dependencies.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. Note: `services/integrations/`
> and `services/secrets/` are EXPECTED to have appeared (plan 037); verify
> they match 037's contract rather than treating that diff as drift.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH (a browser-facing OAuth surface plus an api-key intake
  path; state forgery, secret leakage, and RBAC mistakes are all
  security-grade failures)
- **Depends on**: 037 (hard — models, manifest, credential service, secrets
  provider, status guard). Soft: 030 (not used here; discovery enqueue is
  039's). Does NOT depend on 031–036.
- **Category**: Phase 4a integrations (roadmap `000_MASTER_ROADMAP.md` §4
  Phase 4a row 038; donor `DONOR_PORT_ROADMAP.md` §4.2 / §6 row C2;
  decisions D3, D4)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Signed single-value OAuth state** (donor fix, roadmap 038 row): ONE
   HS256 JWT carried entirely in the OAuth `state` parameter — no cookies,
   no server-side state row. Payload: `type="integration_oauth_state"`,
   `connection_id`, `provider_key`, `owner_scope`, `workspace_id` (acting
   workspace), `user_id`, validated relative `next_path`, `jti`, `iat`,
   `exp` (TTL 10 minutes). This is the exact mechanism the login flow
   already uses (`services/auth/oauth/utils.py:137-154` signs with
   `SECRET_KEY`, `verify_oauth_state` at 210-238 pins the `type` claim) —
   we clone the pattern into `services/integrations/oauth/utils.py` with an
   integrations-specific `type` claim so login states and connect states
   can never be replayed across flows. We do NOT import from
   `services/auth` (cross-service imports are against local convention; the
   helper is ~40 lines).
2. **The callback is an API-side browser-redirected GET** —
   `GET /api/v1/integrations/oauth/callback` — unlike the login flow, where
   the SPA receives the redirect and POSTs the code back
   (`routes/auth/oauth/complete_oauth_login.py`). Rationale: integration
   callbacks must work for workspace-scoped connects where the connection
   row, credential write, scope filtering, and status transition are one
   server-side transaction, and a single registered provider redirect URI
   on the API keeps the Google/Airtable console configuration
   SPA-independent. After processing, the route 302-redirects to
   `FRONTEND_URL + next_path`.
3. **CSRF posture — no exempt-list change.** `CSRFMiddleware` only enforces
   `POST/PUT/PATCH/DELETE` (`middleware/csrf.py:64-69`), so the GET callback
   is structurally outside CSRF enforcement and needs **no** entry in
   `exempt_paths` (`middleware/csrf.py:45-55`). Its anti-forgery guarantee
   is the signed state blob (decision 1) — the OAuth 2.0 `state` parameter
   is precisely a CSRF token for this flow. Every mutating integration
   route (start, api-key connect, test, refresh, revoke) is an ordinary
   SPA `fetch` carrying `X-CSRF-Token`, and stays fully enforced. Per
   AGENTS.md we do not widen the exempt list; a reviewer seeing
   `exempt_paths` touched should reject the PR.
4. **Rate limiting fail-closed on the browser-facing pair.** OAuth start
   and callback are rate-limited per client IP through the existing
   Postgres-backed limiter (`core/rate_limiting.py:67 check_rate_limit`,
   fail-closed for auth flows per AGENTS.md) with integration-specific
   keys; find the auth-flow wiring precedent via `check_rate_limit`'s
   callers (e.g. `core/rate_limiting.py:432`) and copy it. The
   session-authenticated JSON routes rely on auth + RBAC as elsewhere.
5. **RBAC per governance §1**: user-scoped connect/revoke = member+
   (`require_editor`, `core/dependencies.py:268`); workspace-scoped
   connect/revoke and ALL api-key entry = admin+ (`require_owner`,
   `core/dependencies.py:267` — MANAGER_ROLES is owner+admin). Additionally,
   a user-owned connection may only be mutated by its `owner_user_id`
   (or a workspace admin acting where it was connected) — ownership check in
   the service op, role check in the route dependency.
6. **The connection row is created at initiate time** in `auth_pending`
   (donor status machine starts there), with its required `label` (D3)
   captured up front. A callback that never arrives leaves an inert
   `auth_pending` row; 039's sweep ages those out. The credential row is
   created only in the callback.
7. **api-key connect never persists or logs the raw value** (governance §5
   api-key exception): request schema takes `api_key: SecretStr`; the
   service immediately calls `services/secrets.write_secret` (037), builds
   the credential via `store_secret_reference_credential` (reference
   columns only — 037's CHECK makes token columns impossible), and the
   response/audit carry `reference.render()` only. The route also accepts a
   pre-existing `secret_reference` instead of a raw value (references-only
   API, §5). A raw secret in any other request field is a validation error.
8. **Google-specific hard-won details** (donor §4.2): auth URLs carry
   `include_granted_scopes=false`, `access_type=offline`, `prompt=consent`
   (the login provider already sets the latter two,
   `core/auth/oauth_providers/google.py:33-43`); persisted
   `granted_scopes` are the **intersection** of the token response `scope`
   field with the manifest's requested scopes — never whatever extra the
   user granted.
9. **Separate OAuth clients for integrations.** New settings
   `INTEGRATIONS_GOOGLE_CLIENT_ID` / `INTEGRATIONS_GOOGLE_CLIENT_SECRET` /
   `INTEGRATIONS_OAUTH_REDIRECT_URI` — NOT the login client
   (`GOOGLE_OAUTH_CLIENT_ID`, `core/settings/auth.py:27-32`). Login and
   integration consent screens have different scopes, brand verification
   requirements, and blast radius; local dev may set both to the same
   values. The `gmail`/`google_ads` manifest `enabled_setting` gates flip
   to `INTEGRATIONS_GOOGLE_CLIENT_ID` here (037 left them pointing at an
   empty-by-default setting).
10. **Post-callback status**: providers with `requires_discovery=True` go
    to `discovery_pending`; 039 wires the actual job enqueue at a named
    seam (`# discovery enqueue seam — plan 039` comment in the callback
    service op). Until 039 lands, such connections honestly sit in
    `discovery_pending` — documented as pending, not faked. Providers
    without discovery go straight to `active`.
11. **Revoke is best-effort remote, guaranteed local**: call the provider's
    revoke endpoint through `services/integrations/http.py` and ignore
    failures (the login precedent logs-and-continues,
    `core/auth/oauth_providers/google.py:88-99`), then ALWAYS
    `revoke_credential` (crypto-shred, 037) and transition to `revoked`.
12. **Duplicate-principal warning, never a block** (D3): the callback
    response state and the connection detail payload include
    `duplicate_of_connection_ids` from `find_duplicate_principals` (037) so
    042 can warn; connecting the same Gmail account twice under two labels
    is a supported flow.

## Why this matters

037 built the vault; nothing can get into it yet. This plan is the write
path: the browser OAuth dance and the api-key intake, plus the
test/refresh/revoke lifecycle routes the UI (042) and ops flows need. It is
the platform's second browser-redirected surface after login OAuth, and the
first that accepts customer secrets — the reason the state blob, CSRF
posture, scope filtering, and never-store-raw-keys invariants are pinned by
tests here rather than reviewed by hope. Everything downstream (039
discovery, 040 context, 041 operations) assumes connections created through
these flows are correctly labeled, scoped, deduplicated-by-warning, and
auditable.

## Current state

Anchors verified at `0cbbb39`, except the 037 deliverables which this plan
consumes and re-verifies at execution.

- Will exist after 037 (verify against 037's contract at execution):
  `models/integrations.py` (four tables; connection status vocabulary
  including `auth_pending`), `services/integrations/` (manifest with
  `PROVIDER_MANIFESTS` + `is_provider_enabled`, `domain.py` transition map,
  `http.py` Retry-After helper, credential ops including
  `store_oauth_credential`, `store_secret_reference_credential`,
  `ensure_fresh_credential`, `revoke_credential`,
  `find_duplicate_principals`, `transition_connection_status`, and the
  `fake` provider *(superseded — see Amendment (decision D11): no fake —
  a suite-local test provider exists in 037's test tree instead)*),
  `services/secrets/` (`write_secret`, `resolve_secret`),
  audit resource types `INTEGRATION_*`/`SECRET_REFERENCE`.
- Login OAuth state signing precedent: `services/auth/oauth/utils.py` —
  `create_oauth_state` (137-154: HS256 JWT over `SECRET_KEY`, `jti`, `exp`
  from a 10-minute TTL at line 32), `verify_oauth_state` (210-238: decode,
  expiry/invalid → `OAuthAuthenticationError`, `type` claim pinned),
  `safe_next_path` (258-264: relative-path-only redirect validation),
  `resolve_provider_redirect_uri` (241-255: supplied URI must equal the
  configured one), token expiry math (305-312).
- Login OAuth route/service split precedent:
  `routes/auth/create_oauth_authorization_url.py` (route-per-file, thin,
  16-28) → `services/auth/oauth/create_oauth_authorization_url.py`
  (provider lookup, state mint, security event at 43-48). The login
  callback is SPA-driven (`complete_oauth_login`), which this plan
  deliberately does not copy (decision 2).
- Google provider client: `core/auth/oauth_providers/google.py` — auth URL
  params (33-43), token exchange (45-58), refresh (74-86), revoke
  (88-99); retry base `core/auth/oauth_providers/retrying.py` (bounded,
  httpx2). Integration flows use the manifest + `services/integrations/
  http.py` instead of instantiating these login-registry classes, but the
  endpoint URLs and parameter shapes come from here.
- CSRF: `middleware/csrf.py` — method gate at 64-69 (GET never enforced),
  exempt list 45-55 (login OAuth POST endpoints are exempted as pre-auth;
  integration routes are post-auth and need no exemption), Origin check
  75-113, signed-token check 146-194.
- Rate limiting: `core/rate_limiting.py:67 check_rate_limit` (Postgres
  backed); `get_client_ip` used by the CSRF middleware
  (`middleware/csrf.py:15,132`).
- RBAC: `require_role` (`core/dependencies.py:243-263`), `require_owner`
  = MANAGER_ROLES (owner+admin, line 267), `require_editor` (line 268),
  `require_read` (line 269); workspace resolution via `X-Workspace`
  (AGENTS.md).
- Router composition: `routes/__init__.py:8-35` — feature routers imported
  and included alphabetically on `api_router`; a new
  `routes/integrations/__init__.py` composes operation-module routers only
  (AGENTS.md route rules).
- Security events: `services/security/enums.py:13-42` `SecurityEventType`
  (AUTH_OAUTH_STARTED/SUCCEEDED/FAILED at 20-22; nothing
  integration-specific); `safe_record_security_event` usage precedent in
  the CSRF middleware (127-137).
- Notifications: none emitted here (governance §6 assigns integration
  notifications to 039).
- Settings: `core/settings/auth.py:10-21` OAUTH_REQUEST_TIMEOUT/
  MAX_RETRIES/BACKOFF_FACTOR (login-flow knobs; integrations use the
  INTEGRATIONS_HTTP_* knobs from 037); `FRONTEND_URL` exists (used by the
  CSRF origin allowlist, `middleware/csrf.py:91-92`).
- Frontend contract note: the SPA calls via `src/lib/api/client.ts` with
  credentials + CSRF + `X-Workspace` (AGENTS.md); 042 builds the UI. No
  web changes in this plan.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations (this plan adds NO migration) |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/routes/integrations tests/services/integrations -q` | all pass |
| Full API tests | `TEST_DATABASE_URL=... uv run pytest -q` | all pass |
| Route smoke | `uv run python -c "from routes import api_router; print(sorted({r.path for r in api_router.routes if '/integrations' in r.path}))"` | the Step 4 route set |

## Scope

**In scope:**

- `apps/api/core/settings/integrations.py` (extend — decision 9 settings:
  `INTEGRATIONS_GOOGLE_CLIENT_ID: str = ""`,
  `INTEGRATIONS_GOOGLE_CLIENT_SECRET: SecretStr = SecretStr("")`,
  `INTEGRATIONS_OAUTH_REDIRECT_URI: str = ""`,
  `INTEGRATIONS_OAUTH_STATE_TTL_MINUTES: int = 10`)
- `apps/api/services/integrations/manifest.py` (edit — point
  `gmail`/`google_ads` `enabled_setting` at
  `INTEGRATIONS_GOOGLE_CLIENT_ID`)
- `apps/api/services/integrations/oauth/` (create): `__init__.py`,
  `utils.py` (state mint/verify), `build_authorization_url.py`,
  `exchange_authorization_code.py`, `fetch_external_principal.py`
- `apps/api/services/integrations/connections/` (extend, one op per file):
  `start_oauth_connect.py`, `complete_oauth_callback.py`,
  `connect_api_key.py`, `list_connections.py`, `get_connection.py`,
  `test_connection.py`, `refresh_connection.py`, `revoke_connection.py`,
  `utils.py` (ownership/authorisation helpers), `schemas.py`
- `apps/api/routes/integrations/` (create, route-per-file):
  `__init__.py`, `list_providers.py`, `list_connections.py`,
  `get_connection.py`, `start_oauth_connect.py`, `oauth_callback.py`,
  `connect_api_key.py`, `test_connection.py`, `refresh_connection.py`,
  `revoke_connection.py` + registration in `routes/__init__.py`
- `apps/api/services/security/enums.py` (add
  `INTEGRATION_OAUTH_STATE_INVALID = "integration_oauth_state_invalid"`)
- `apps/api/tests/routes/integrations/` (create),
  `apps/api/tests/services/integrations/test_oauth_state.py` (create)

**Out of scope (do NOT touch):**

- Any Alembic migration — 037 owns the schema; if you need a column, STOP.
- Discovery job enqueue/handlers, sweeps, notifications, and the resource
  selection routes — 039 (leave only the named seam comment, decision 10).
- Active context — 040. Real provider operations and clients (Gmail
  message APIs, Google Ads services, Airtable data APIs) — 041; this plan
  touches only auth-protocol endpoints (authorize/token/revoke/whoami-class
  identity lookups) needed to complete the connect handshake.
- UI — 042.
- `middleware/csrf.py` `exempt_paths` (decision 3 — MUST remain untouched),
  `services/auth/**`, `core/auth/oauth_providers/**`.

## Git workflow

- Branch: `advisor/038-integration-oauth-connect-flows`
- Commit style: `API - Integration OAuth Connect Flows`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings + manifest gates

Add the decision 9 fields to `IntegrationsSettingsMixin` (037 created it).
No production-safety validator change: an empty client id simply leaves the
Google-family providers disabled via the manifest gate (mirrors how
`GOOGLE_OAUTH_ENABLED` login config is optional,
`core/settings/auth.py:27-32`). Flip `gmail`/`google_ads`
`enabled_setting` to `"INTEGRATIONS_GOOGLE_CLIENT_ID"` in the manifest.

**Verify**: settings import prints defaults; with
`INTEGRATIONS_GOOGLE_CLIENT_ID=x` set, `is_provider_enabled` returns True
for gmail/google_ads (quick python -c check); ruff exit 0.

### Step 2: State blob utilities

`services/integrations/oauth/utils.py` (decision 1), cloning the
`services/auth/oauth/utils.py:137-154,210-238` shape:

```python
def create_integration_oauth_state(*, connection_id, provider_key, owner_scope,
                                   workspace_id, user_id, next_path) -> str: ...
def verify_integration_oauth_state(state: str) -> dict[str, Any]: ...
def safe_next_path(next_path: str | None) -> str | None: ...  # copy of auth's 258-264 rule
```

- HS256 over `settings.SECRET_KEY`, `type="integration_oauth_state"`
  pinned on verify, `exp` from `INTEGRATIONS_OAUTH_STATE_TTL_MINUTES`,
  `jti` for log correlation.
- Verification failures raise `IntegrationAuthError`
  (`core/exceptions/integration.py:98` — 401) with
  `operation="oauth_state"`; the caller records the
  `INTEGRATION_OAUTH_STATE_INVALID` security event before re-raising
  (Step 5).
- Required claims checked explicitly (provider_key, connection_id,
  workspace_id, user_id) — missing → invalid, same as
  `verify_oauth_state`'s completeness check (utils.py:226-238).

**Verify**: `tests/services/integrations/test_oauth_state.py` (Step 7)
round-trips, expires, and tamper-rejects; ruff exit 0.

### Step 3: OAuth protocol ops + connect services

`services/integrations/oauth/` protocol ops (one per file), all
manifest-driven with a provider-key dispatch (`fake` short-circuits
in-process *(superseded — see Amendment (decision D11): no fake arm — the
service is purely generic manifest-driven)*; `gmail`/`google_ads` share
the Google endpoints from
`core/auth/oauth_providers/google.py:28-31` as URL constants re-declared
locally; `airtable` has no OAuth mode in v1):

- `build_authorization_url.py` — Google family:
  `client_id=INTEGRATIONS_GOOGLE_CLIENT_ID`, `redirect_uri=
  INTEGRATIONS_OAUTH_REDIRECT_URI`, `response_type=code`,
  `scope=" ".join(manifest.oauth_scopes)`, `state=<blob>`,
  `access_type=offline`, `prompt=consent`,
  **`include_granted_scopes=false`** (decision 8). Fake: returns
  `{FRONTEND_URL}/integrations/fake-consent?state=...` (the test suite
  calls the callback directly instead). *(superseded — see Amendment
  (decision D11): the fake-consent device is replaced by the suite-local
  test provider's transport-mocked authorize/token endpoints)*
- `exchange_authorization_code.py` — token POST via
  `services/integrations/http.py` (Retry-After aware, typed errors);
  validates the payload the way `_parse_token_payload` does
  (`core/auth/oauth_providers/retrying.py:28-49`: 200-with-error and
  missing access_token are failures).
- `fetch_external_principal.py` — resolves the stable external principal
  id + label for fingerprinting: Google userinfo `sub`/`email` for gmail;
  for google_ads, the authenticating Google identity at connect time (the
  MCC/account hierarchy is discovery data, 039/041); fake returns a
  configurable principal *(superseded — see Amendment (decision D11):
  the suite-local test provider's userinfo endpoint is mocked at the
  transport layer instead)*.

Connection service ops (`services/integrations/connections/`, one per
file):

- `start_oauth_connect.py` — validates the manifest (provider enabled,
  `oauth` in auth_modes, owner_scope matches the request), validates the
  non-empty label (schema + model CHECK), creates the
  `IntegrationConnection` in `auth_pending` with a placeholder credential?
  **No** — `credential_id` is not null per 037; instead create the
  connection AND a stub `ExternalCredential` row (`auth_mode='oauth'`, all
  token columns null, fingerprint = `f"pending:{connection_id}"`) in one
  transaction, replaced atomically in the callback. Returns
  `{authorization_url, state, connection_id}`. Audits CREATE on
  `INTEGRATION_CONNECTION`.
- `complete_oauth_callback.py` — verify state (Step 2); load the
  `auth_pending` connection by `connection_id` claim (missing/not-pending →
  `IntegrationConnectionError`); exchange the code; fetch the principal;
  **filter granted scopes** to the manifest's requested set (decision 8);
  write the real credential via `store_oauth_credential` (037) and swap
  `credential_id`; compute `duplicate_of_connection_ids`
  (`find_duplicate_principals`, D3 warn-only); transition to
  `discovery_pending` or `active` (decision 10) with the
  `# discovery enqueue seam — plan 039` comment; audit UPDATE with scopes +
  fingerprint (no tokens). On provider `error` query param or exchange
  failure: audit FAILURE, record the security event, leave `auth_pending`,
  and redirect to the frontend with `?integration_error=<code>`.
- `connect_api_key.py` (decision 7) — admin+ only (route layer); schema
  `IntegrationApiKeyConnectRequest` with `label`, `provider_key`, and
  exactly one of `api_key: SecretStr | None` /
  `secret_reference: SecretReferenceIn | None` (model_validator enforces
  XOR). Raw path: `write_secret(name=f"integrations-{provider_key}-{uuid4().hex}",
  value=...)` then `store_secret_reference_credential`; reference path:
  store as given (resolution proves it at test time). Creates the
  connection directly in `discovery_pending`/`active` (no auth_pending leg).
  Response and audit contain `reference.render()` only; the SecretStr value
  must never reach a log record, exception message, or audit detail.
- `list_connections.py` / `get_connection.py` — workspace-owned rows for
  the acting workspace + user-owned rows for the requesting user; detail
  includes credential **metadata** (admin+ for the credential block per
  governance §1: expiry, scopes, fingerprint, last refresh — never values
  or references' resolved contents; member view omits the credential
  block); includes `duplicate_of_connection_ids`.
- `test_connection.py` — resolves a working credential
  (`ensure_fresh_credential` for oauth; `resolve_secret` for references —
  §5 rotation re-test lives here) and performs the manifest's cheap
  identity call (fake: no-op *(superseded — see Amendment (decision D11):
  no fake arm — tests mock the identity endpoint at the transport
  layer)*; Google: userinfo). Success → audit; auth
  failure → transition `needs_reauth`, typed error.
- `refresh_connection.py` — forces `ensure_fresh_credential` regardless of
  leeway; surfaces the refreshed expiry.
- `revoke_connection.py` — decision 11: best-effort provider revoke via
  `http.py`, then `revoke_credential` (crypto-shred) + transition
  `revoked`. Ownership rules per decision 5 (utils.py helper:
  `require_connection_mutation_allowed(connection, user, membership)`).

**Verify**: ruff exit 0; service-level tests (Step 7) pass against the fake
provider without any network *(superseded — see Amendment (decision D11):
against the suite-local test provider with transport-mocked provider
HTTP)*.

### Step 4: Routes

`routes/integrations/` (route-per-file; `__init__.py` composes only), all
under prefix `/integrations`, registered in `routes/__init__.py`
alphabetically (between `conversations` and `models`):

| File | Operation | Auth |
|------|-----------|------|
| `list_providers.py` | `GET /integrations/providers` — manifest entries with `is_provider_enabled` filtering | `require_read` |
| `list_connections.py` | `GET /integrations/connections` | `require_read` |
| `get_connection.py` | `GET /integrations/connections/{connection_id}` | `require_read` (credential metadata block only for admin+, decision 5 / §1) |
| `start_oauth_connect.py` | `POST /integrations/connections/oauth/start` | `require_editor`; workspace-scoped providers additionally require admin+ (explicit check against `MANAGER_ROLES` in the service, per §1) |
| `oauth_callback.py` | `GET /integrations/oauth/callback?code&state[&error]` | **no session dependency** — identity comes from the signed state (decision 1/2); rate-limited (decision 4); returns `RedirectResponse` |
| `connect_api_key.py` | `POST /integrations/connections/api-key` | `require_owner` (admin+, §1 API-key entry) |
| `test_connection.py` | `POST /integrations/connections/{connection_id}/test` | `require_editor` + ownership rule |
| `refresh_connection.py` | `POST /integrations/connections/{connection_id}/refresh` | `require_editor` + ownership rule |
| `revoke_connection.py` | `POST /integrations/connections/{connection_id}/revoke` | `require_editor` + ownership rule (user-scoped own; workspace-scoped admin+, §1) |

Route modules stay thin (the
`routes/auth/create_oauth_authorization_url.py:16-28` shape): parse, call
the service op, return the schema. The callback route wraps the service in
the redirect contract: success and failure BOTH end in a 302 to the
frontend (an OAuth callback must never render problem+json to a human).

**Verify**: route smoke command lists all nine paths; existing route tests
still green (`uv run pytest tests/routes -q`).

### Step 5: Security events + rate limiting

- Add `INTEGRATION_OAUTH_STATE_INVALID` to `SecurityEventType`
  (`services/security/enums.py:13-42`) and record it (with `jti` when
  decodable, IP, endpoint) on every state verification failure — the
  pattern of the CSRF middleware's `_record_rejection`
  (`middleware/csrf.py:119-140`: dedicated committed session, never turns a
  rejection into a 500).
- Wire `check_rate_limit` (`core/rate_limiting.py:67`) into
  `start_oauth_connect` (per user) and `oauth_callback` (per client IP via
  `get_client_ip`), fail-closed, mirroring the auth-flow wiring found via
  its callers. Limits: reuse existing auth-flow limits/settings if a
  generic knob exists; otherwise conservative constants (e.g. 10/min
  start, 20/min callback) — record the choice in the PR description.

**Verify**: a tampered-state request produces exactly one
`security_events` row with the new type (test in Step 7); repeated
callbacks past the limit → 429 problem+json.

### Step 6: Audit sweep

Confirm every mutating op writes exactly one audit row (CREATE on start
and api-key connect; UPDATE on callback complete, test, refresh; DELETE on
revoke — resource `INTEGRATION_CONNECTION`, with credential events from
037's ops beneath). Confirm no audit `details` dict, log call, or
exception message interpolates a token, api key, or resolved secret —
grep for `api_key`, `access_token`, `refresh_token` in `details=` and log
format args under `services/integrations/`.

**Verify**: `TEST_DATABASE_URL=... uv run pytest tests/routes/integrations -q` green;
the Step 7 never-stored test passes.

### Step 7: Tests

`tests/services/integrations/test_oauth_state.py` (no DB): mint→verify
round-trip preserves claims; expired state rejected; **tamper rejection**
— flip one character anywhere in the blob → `IntegrationAuthError`, and a
login-flow state (`type="oauth_state"`) is rejected by the integrations
verifier (cross-flow replay pinned); `safe_next_path` rejects absolute
URLs and schemes.

`tests/routes/integrations/` (DB-backed, `pytestmark =
pytest.mark.asyncio`, factories from 037, fake provider enabled via test
env *(superseded — see Amendment (decision D11): the suite-local test
provider registered through the loader seam in test fixtures; its
authorize/token/userinfo endpoints mocked at the transport layer)*):

- `test_oauth_connect_flow.py`: start (member) → connection in
  `auth_pending` with label; callback with valid state → credential stored
  encrypted, scopes filtered to the manifest set (grant a superset in the
  fake payload *(superseded — see Amendment (decision D11): in the mocked
  token-endpoint response)*; assert intersection persisted), status
  `discovery_pending` (fake requires discovery *(superseded — see
  Amendment (decision D11): the suite-local test provider requires
  discovery)*), 302 to
  `FRONTEND_URL + next_path`; **the authorization URL contains
  `include_granted_scopes=false`** for a Google-family provider (unit-level
  on `build_authorization_url` with the gate setting patched); callback
  with tampered state → 401-class redirect with `integration_error`, no
  credential written, security event row present; second connect of the
  same fake principal *(superseded — see Amendment (decision D11): same
  test-provider principal, via the mocked userinfo endpoint)* under a new
  label succeeds AND reports the sibling in
  `duplicate_of_connection_ids` (D3).
- `test_api_key_connect.py`: **api-key-never-stored** — connect with a raw
  key; assert the plaintext appears nowhere in `external_credentials`,
  `integration_connections`, `audit_events` (full-row scans), the response
  body (reference only), or captured logs (`caplog`); reference-only
  variant accepted; member (non-admin) → 403; malformed reference → 400
  problem+json.
- `test_connection_lifecycle_routes.py`: test/refresh/revoke happy paths
  against the fake provider; refresh after poisoning the fake refresh
  token *(superseded — see Amendment (decision D11): against the
  suite-local test provider; the mocked token endpoint returns 4xx for
  the poisoned refresh token)* → connection `needs_reauth`; revoke →
  token columns NULL
  (crypto-shred), status `revoked`, provider revoke failure does not block
  local revoke; revoked connection rejects test/refresh (transition guard).
- `test_rbac_and_csrf_posture.py`: RBAC matrix — member can start a
  user-scoped connect, cannot start workspace-scoped (403), cannot enter
  api keys (403); read_only can list but not mutate; a non-owner member
  cannot revoke another user's user-scoped connection; **CSRF posture** —
  POST routes without `X-CSRF-Token` under a session cookie → 403 from the
  middleware, while the GET callback succeeds with no CSRF token; and a
  source-level assertion that `middleware/csrf.py` `exempt_paths` contains
  no `/integrations` entry (read the file in the test — cheap and pins
  decision 3).

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/routes/integrations tests/services/integrations -q`
→ all pass; skips (not failures) without the env var; full suite green.

## Test plan

Covered by Step 7 (~24–30 tests). The pinned invariants: **state-blob
tamper and cross-flow replay rejection** (one flipped character kills the
flow, login states don't open connections), **the raw api key is
unrecoverable from every persistence surface and log**, **persisted scopes
⊆ requested scopes** and `include_granted_scopes=false` on Google URLs,
**multi-connection with duplicate-principal warning, never a block** (D3),
**crypto-shred on revoke regardless of provider-side failure**, and **CSRF
enforcement untouched** (no exemptions; callback safe by method + signed
state).

## Done criteria

- [ ] `uv run ruff check .` exits 0; `uv run alembic check` clean (no new
      migration in this plan)
- [ ] `TEST_DATABASE_URL=... uv run pytest -q` exits 0 (full suite)
- [ ] Route smoke lists exactly the nine Step 4 paths *(superseded — see
      Amendment (plan 080): ten paths with 074's rename route)*
- [ ] `git diff middleware/csrf.py` is empty (decision 3)
- [ ] Grep shows no raw-value interpolation:
      `grep -rn "get_secret_value" apps/api/services/integrations/connections/`
      appears only at the write_secret call site
- [ ] `docs/architecture/governance.md` updated: §1 rows "Connect/revoke
      own user-scoped integrations (037–038)" and "Connect/revoke
      workspace-scoped integrations (037–038)" and "Enter API keys / secret
      references (037)" → `[implemented: plan 038]`; §5 api-key-connect
      exception bullet and rotation re-test bullet → `[implemented: plan
      038]`; §1 credential-metadata row stays pending 042's UI half —
      annotate `[implemented (API): plan 038]`
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 037 is not implemented (no `services/integrations/manifest.py` or
  the credential ops are missing) — hard dependency.
- 037's delivered contract differs from the "Current state" assumptions
  (e.g. `credential_id` became nullable, the status vocabulary changed, or
  `store_oauth_credential`'s signature moved) — reconcile with 037's plan
  doc first.
- The login OAuth utilities have moved or changed shape
  (`services/auth/oauth/utils.py` state functions, `safe_next_path`) — the
  Step 2 clone was written against those lines.
- `middleware/csrf.py`'s method gate (64-69) has changed such that GET
  requests are enforced — decision 3's justification collapses; redesign
  the callback posture before coding.
- A `routes/integrations/` package already exists.
- You cannot complete the connect handshake for a D4 provider without
  implementing data-plane API calls (messages, campaigns, records) — that
  is 041 scope leaking in; ship the fake-provider path and STOP on the
  real-provider gap. *(superseded — see Amendment (decision D11): ship
  the generic flow proven against the suite-local test provider and STOP
  — real-provider live connects remain 041-scope-leak territory)*
- You feel the need to widen `exempt_paths`, add a migration, enqueue a
  job, or send a notification — 037/039 boundaries leaking.

## Maintenance notes

- **Consumers**: 039 replaces the `# discovery enqueue seam — plan 039`
  comment in `complete_oauth_callback`/`connect_api_key` with
  `enqueue_job(kind="integrations.discover_resources", ...)` and owns
  everything after `discovery_pending`; 040 resolves active context across
  the N connections these routes create (D3); 041 adds real provider
  operations and will extend `fetch_external_principal` for Airtable
  whoami; 042 builds provider cards, the connect dialogs (label input is
  required — D3), connection pickers, and the duplicate-principal warning
  from `duplicate_of_connection_ids`.
- **Reconnect after `needs_reauth`**: the supported path is
  `start_oauth_connect` against the SAME connection id (extend the start
  op to accept `connection_id` for re-auth in 042's slice if product wants
  in-place reconnect; today a new connect + revoke of the stale connection
  is the documented flow). Record the choice in 042.
- **Redirect URI discipline**: `INTEGRATIONS_OAUTH_REDIRECT_URI` must
  exactly match the provider console value; the callback never accepts a
  caller-supplied redirect (state carries only a relative `next_path`) —
  keep it that way.
- **Provider registries stay separate**: login providers
  (`core/auth/oauth_providers/`) authenticate humans; the integrations
  manifest authorizes data access. A future consolidation must not let a
  login client mint integration credentials (different client ids,
  decision 9).
- Reviewers should scrutinize: the callback's transaction boundaries (the
  credential swap + status transition must commit atomically or roll back
  to `auth_pending`), the stub-credential fingerprint never colliding with
  a real one (`pending:` prefix), SecretStr handling in
  `connect_api_key` (no `repr` leaks), and that both callback outcomes are
  redirects, never JSON.

## Amendment (plan 067, 2026-07-07): PKCE + single-use state

Written before this plan executed; where this block conflicts with the
body above, this block wins. Grounding: RFC 9700 (OAuth 2.0 Security
BCP) and OAuth 2.1 require PKCE (S256) on authorization-code flows
including confidential clients, and require state/code replay defenses.
Both matter doubly here because the callback is deliberately not
session-bound (decision 1/2).

### New decisions

13. **PKCE S256 on every authorization-code connect.**
    `start_oauth_connect` generates a `code_verifier` per RFC 7636
    (43–128 chars from a CSPRNG) and sends
    `code_challenge=BASE64URL(SHA256(verifier))` +
    `code_challenge_method=S256` on the authorization URL;
    `exchange_authorization_code` sends the `code_verifier` in the token
    POST. Applies to the Google family AND the fake provider (which must
    verify challenge↔verifier so tests pin the relation) *(the fake
    clause is superseded — see Amendment (decision D11): tests pin the
    PKCE relation against the suite-local test provider's mocked token
    exchange)*. Any future
    OAuth-mode provider (e.g. Airtable, whose OAuth requires PKCE)
    inherits this unconditionally.
14. **Server-side pending-OAuth-state row, single-use.** New table
    `integration_oauth_states`: `jti` (PK, from the state JWT),
    `connection_id`, `code_verifier` (encrypted at rest with the same
    symmetric primitive 037 uses for token columns — reuse its helper;
    if 037 delivered no reusable helper, record the deviation and the
    fallback in the PR description), `created_at`, `expires_at` (same
    TTL as the JWT). Created in `start_oauth_connect`'s existing
    transaction; consumed in `complete_oauth_callback` by a single
    atomic `DELETE ... WHERE jti = :jti RETURNING ...` BEFORE the token
    exchange. No row (expired, swept, or replayed) → the existing
    invalid-state path: `IntegrationAuthError` +
    `INTEGRATION_OAUTH_STATE_INVALID` security event + error redirect.
    This amends decision 1's "no server-side state row"; the signed JWT
    stays (authenticity, claims, cross-flow `type` pinning) and its
    `jti` — previously log-correlation only — becomes the row key.
15. **Verifier-in-JWT rejected.** The state transits the browser and
    the JWT is signed, not encrypted; an attacker who steals state+code
    would also hold the verifier, defeating PKCE. The verifier never
    leaves the server.
16. **One migration allowed.** This supersedes "Any Alembic migration —
    037 owns the schema; if you need a column, STOP" and the
    "no new migration in this plan" done criterion, for exactly the
    `integration_oauth_states` table, on the same Alembic
    branch/version-path 037 used for the integration tables. Anything
    beyond that table remains a STOP.
17. **`INTEGRATIONS_OAUTH_REDIRECT_URI` must be `https` outside
    `ENVIRONMENT=local`** — enforced in the production-safety
    `model_validator` (`core/settings/__init__.py`, the
    `local_fs`/`console` pattern); empty remains allowed (provider
    disabled). This amends Step 1's "No production-safety validator
    change".

### Step deltas

- **Step 1**: add the decision 17 validator clause + a settings test.
- **Step 2**: unchanged shape; note in `utils.py` that `jti` keys the
  pending row (decision 14).
- **Step 3**: `start_oauth_connect` mints verifier/challenge and
  persists the pending row in its transaction; `build_authorization_url`
  gains `code_challenge`/`code_challenge_method=S256`;
  `exchange_authorization_code` gains `code_verifier`;
  `complete_oauth_callback` consumes the row first (decision 14). Fake
  provider verifies the S256 relation and rejects a wrong verifier.
  *(superseded — see Amendment (decision D11): the mocked token endpoint
  in the test suite verifies the S256 relation and rejects a wrong
  verifier)*
- **New step (before Step 1)**: the `integration_oauth_states`
  migration per decision 16; `uv run alembic check` clean afterwards.
- **Step 7 / test plan additions**: authorization URL carries
  `code_challenge` + `method=S256`; the fake exchange fails on a
  mismatched verifier and succeeds on the real one *(superseded — see
  Amendment (decision D11): the mocked exchange — PKCE S256 and
  single-use state are asserted against the transport-mocked token
  endpoint)*; **replay** — a
  second callback with the same valid state → error redirect, security
  event, no second credential, connection state unchanged; expired
  pending row → same rejection even with a not-yet-expired JWT;
  validator test — non-local env + `http://` redirect URI raises.
- **Done criteria deltas**: replace the "(no new migration in this
  plan)" criterion with "exactly one migration: `integration_oauth_states`";
  add "[ ] state replay rejected (test green)" and "[ ] PKCE pinned on
  auth URL + token exchange (tests green)".

### Maintenance

039's sweep should purge expired `integration_oauth_states` rows
alongside stale `auth_pending` connections (inert until then).

## Amendment (plan 074, 2026-07-07): connection label rename

Where this block conflicts with the body above, this block wins.

**New decision 18** (13–17 are plan 067's). D3 makes the per-connection
label a required, user-set value; 042 builds inline rename on it. Add
`rename_connection.py` (service op + route file):
`PATCH /integrations/connections/{connection_id}` with body `{label}`
(non-empty, same schema rule as connect), auth `require_editor` +
`require_connection_mutation_allowed` (the test/refresh ownership rule —
label surgery is not credential surgery). Audits one UPDATE on
`INTEGRATION_CONNECTION` with old/new label; no status transition, no
credential access.

**Step deltas**: Step 4's table gains the row and its verify line becomes
"lists all ten paths"; Step 6's audit sweep covers rename; Step 7 adds:
rename happy path + audit row, blank label 400, non-owner member 403 on a
user-scoped connection, read_only 403.

## Amendment (plan 080, 2026-07-10)

Where this amendment contradicts the body above (including the earlier
amendment blocks), this amendment wins. Grounding: the pre-handoff
readiness review at `bbfd769`; decisions recorded in
`docs/plans/080-phase4a-4b-handoff-readiness-sweep.md`.

1. **Ten routes, not nine.** The 074 amendment added
   `PATCH /integrations/connections/{connection_id}` (rename) and
   already updated Step 4's verify line to "all ten paths", but the done
   criterion still says "exactly the nine Step 4 paths". It reads: the
   route smoke lists exactly the TEN paths (Step 4's nine plus 074's
   rename).
2. **Callback success contract** (plan 080 decision 2): on success the
   callback's 302 redirect appends `connection_id=<connection uuid>` and
   `status=<post-callback connection status>` query parameters to
   `FRONTEND_URL + next_path`. The failure parameter stays
   `integration_error` as the body defines. 042's OAuth-return success
   alert consumes exactly these two success params — this pins the
   contract 042 decision 6 was written to reconcile against, so the
   redirect shape is no longer an open assumption.
3. **PKCE verifier key purpose** (plan 080 decision 7): the stored
   `code_verifier` (067 decision 14) is encrypted under a dedicated HKDF
   purpose string `praxis:oauth-pkce-verifier:v1`, derived through the
   purpose-derivation seam 037's 068 amendment ships
   (`derive_purpose_key` + `MultiFernet` over the credential root keys,
   newest first) — NOT by reusing the credential-token purpose
   `praxis:credential-tokens:v1`. This tightens 067's "encrypted at rest
   with the same symmetric primitive 037 uses ... reuse its helper"
   wording: reuse the primitive and the seam, never the purpose. Tests
   pin that a verifier ciphertext does not decrypt under the
   credential-token subkey.
4. **Route spelling confirmed authoritative.** The body consistently
   uses `POST /integrations/connections/oauth/start` (verified — no
   other spelling appears in this plan). Per plan 080 decision 2 the
   038/039 spellings are authoritative; 042's endpoint table (which
   sketched `oauth/initiate`, `.../resources`, `.../discovery`) is
   corrected by 042's own plan-080 amendment.

## Amendment (decision D11, 2026-07-10)

Where this amendment contradicts anything above — the plan body AND the
plan 067/074/080 amendment blocks — this amendment wins. Grounding:
roadmap decision D11 (2026-07-10): "**The fake integration provider is
removed entirely.** ... The plugin contract and loader are exercised by
a **suite-local test provider registered through the loader seam in test
code only** (fixtures under the test tree, never product code), with
provider HTTP (token/userinfo/discovery endpoints) mocked at the
transport layer."

1. **Every "fake short-circuits in-process" arm is removed.** The OAuth
   service ops (`build_authorization_url`,
   `exchange_authorization_code`, `fetch_external_principal`) and
   `test_connection`'s identity call are purely generic
   manifest-driven; there is no fake dispatch arm, no
   `{FRONTEND_URL}/integrations/fake-consent?state=...` device, and no
   "identity call (fake: no-op)" branch. The 067 amendment's "Applies
   to the Google family AND the fake provider" (decision 13) loses its
   fake clause; the `oauth_operations` plugin seam that would have
   carried the fake's in-process token ops is dropped with it (see
   037's D11 amendment item 6) — the engine's generic manifest-driven
   OAuth flow is the only token path.
2. **Tests register the suite-local test provider** (through the loader
   seam, in test fixtures — never product code) **and mock its
   authorize/token/userinfo endpoints at the transport layer.** Step
   7's "fake provider enabled via test env" setup becomes suite-local
   registration. PKCE S256 and single-use state are asserted against
   the mocked token exchange (including the 067 amendment's
   `code_challenge`/verifier assertions: the mocked exchange fails on a
   mismatched verifier and succeeds on the correct one); the poisoned
   refresh token, scope-superset filtering, and duplicate-principal
   cases become mocked-transport responses.
3. **STOP condition rewritten**: "ship the fake-provider path and STOP"
   becomes "ship the generic flow proven against the suite-local test
   provider and STOP" — real-provider live connects remain
   041-scope-leak territory. Manual QA connects real dev credentials
   (Airtable's API key is the cheapest connect).
