# Plan 090: Make integration credential failures and recovery auth-mode aware

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan, its row in
> `docs/plans/000_README.md`, its roadmap entry, and the implemented markers
> in `docs/architecture/governance.md`.
>
> **Pre-flight**: Read the root `AGENTS.md`, both app `AGENTS.md` files,
> `REVIEW.md`, and `docs/architecture/governance.md` §1, §5, and §6.
>
> **Drift check (run first)**:
> `git diff --stat f24cc8c..HEAD -- apps/api/core/exceptions/integration.py apps/api/core/settings/providers.py apps/api/models/integrations.py apps/api/services/secrets/ apps/api/services/integrations/ apps/api/routes/integrations/ apps/api/alembic/versions/core/ apps/api/tests/services/secrets/ apps/api/tests/services/integrations/ apps/api/tests/routes/integrations/ apps/api/.env.example apps/web/src/features/integrations/ apps/web/tests/features/integrations/ docker-compose.yml makefiles/local.mk docs/architecture/governance.md`
> A material change to the status machine, secret-provider contract,
> credential schemas, lifecycle routes, or connection-row composition is a
> STOP condition until this plan is reconciled with the live code.

## Status

- **Status**: DONE 2026-07-28
- **Priority**: P1 (live correctness defect with a false recovery instruction)
- **Effort**: M-L (one core migration plus backend, credential, local-provider,
  frontend, and regression work)
- **Risk**: MEDIUM-HIGH (credential handling, status migration, RBAC, audit,
  discovery retry, and provider-facing recovery)
- **Depends on**: 037–042 and 089 (all DONE)
- **Category**: corrective integration lifecycle
- **Planned at**: commit `f24cc8c`, 2026-07-28
- **Execution progress**: **Complete 2026-07-28; Slices A–D done.**
  Secret-store availability is distinct from provider authentication;
  `needs_reauth` is OAuth-only; reference credentials use
  `needs_credential` and admin/owner in-place replacement; local encrypted
  secrets use one API-root-anchored, cross-process-locked, atomically replaced
  store; and recovery controls are driven by the connection auth mode. The
  service-account paste field is obscured as a password input and replacement
  failures use replacement-specific copy. A live retry exposed and fixed a
  process-restart regression: replacement now initializes credential
  cryptography before computing the new principal fingerprint. Migration
  upgrade/downgrade, focused suites, exhaustive consumer review, and the full
  repository gate passed. Final totals were 1,292 API tests and 80 web test
  files / 383 tests. The first full run had one unrelated artifact-sweeper
  count failure caused by transient test-database state; its isolated rerun
  and the complete second `make check` passed. The operator's light-theme
  screenshot confirmed the obscured field and corrected failure heading;
  automated browser QA was unavailable because no browser instance was
  exposed.

## Product intent

A service account or API key has no interactive sign-in session. Only OAuth
may tell an operator to "Sign in again." A non-OAuth credential rejected by
its provider needs replacement, while Praxis being unable to read its secret
store is an operational failure that should be retried without blaming or
discarding the credential.

After this plan:

- `needs_reauth` means OAuth reauthorization and nothing else;
- `needs_credential` means a service-account key or API key must be replaced;
- secret-store failures follow retriable `error`/`degraded` discovery behavior;
- recovery controls use the connection's auth mode, not every mode its
  provider supports;
- OAuth refresh is never offered or invoked for reference credentials;
- local API and worker processes resolve one encrypted store deterministically,
  with cross-process-safe writes; and
- operator copy is accurate, including the existing "Service Account Ley"
  typo.

## Incident evidence

The defect was observed locally on 2026-07-28 for a Google Ads connection with
`auth_mode="service_account"`:

- The connection persisted `status="needs_reauth"` and
  `status_reason="resource_discovery_auth_failed"`.
- Its latest discovery failed with
  `Secret reference could not be resolved | provider=local |
  operation=resolve_secret`.
- Earlier runs for the same connection succeeded and discovered 16 accounts.
- The same stored reference resolved after the local API/worker restart.

Never record the reference name, service-account identity, key contents, or
other secret-bearing metadata in tests, logs, plans, or audit assertions.
This evidence proves the classification and stale-status defects, but not
whether the original resolution failure came from a differing working
directory, a non-atomic/cross-process race, or both. Step 2 fixes both supported
failure modes; do not claim a narrower historical cause without reproducing it.

## Decisions taken

1. **`needs_reauth` becomes OAuth-only.** Add `needs_credential` to the
   persisted status vocabulary and CHECK. A provider-originated
   `IntegrationAuthError` maps to `needs_reauth` only for OAuth; `api_key`,
   `service_account`, and `system_token` map to `needs_credential`.
2. **Secret resolution is not provider authentication.** Add a typed 503
   exception such as `IntegrationCredentialUnavailableError` for a configured
   secret provider that cannot find, read, decrypt, or resolve a reference.
   Local and cloud implementations normalize equivalent availability cases
   without exposing provider response bodies or values. Discovery treats this
   like other operational failures: preserve the credential; settle to
   `error` before any success or `degraded` after prior success; notify only
   after the final retry.
3. **Do not classify by strings.** Exception type identifies vault
   availability; the persisted credential auth mode classifies a genuine
   provider `IntegrationAuthError`. Do not inspect message, provider, or
   operation strings to choose a status.
4. **Add mode-correct replacement, not OAuth conversion.** Add
   `PUT /integrations/connections/{connection_id}/credential`, admin-authorized
   under governance §1. It accepts exactly one of `api_key`,
   `service_account_json`, or `secret_reference`, matching the connection's
   existing auth mode. OAuth receives a typed 400 directing callers to its
   existing reauthorization flow; `system_token` remains unsupported unless
   an existing user-managed provider requires it during execution.
5. **Preserve connection identity and history.** For raw input, write a new
   version under the existing app-managed secret name; for a reference,
   resolve it before mutation. Parse service-account JSON with the existing
   provider-attributed helper. Row-lock and revalidate the connection and
   credential, update only reference/principal metadata, audit rendered
   references but never values, transition to `discovery_pending`, and enqueue
   deduplicated discovery. Do not create a duplicate connection.
6. **Retain the prior version.** Do not destroy it during replacement; it must
   remain readable until the new version passes discovery, per governance §5.
   Automatic cleanup is deferred because the model does not distinguish
   app-managed from external references. Never delete an externally owned
   secret.
7. **Recovery is status- and mode-driven.**
   - OAuth `needs_reauth` → "Sign in again" / OAuth reconnect.
   - Service-account `needs_credential` → "Replace Service Account Key".
   - API-key `needs_credential` → "Replace API key".
   - `error` or stalled discovery → "Try again" / discovery retry.
   - `degraded` retains prior usable resources and offers discovery retry in
     lifecycle actions.
   - Impossible status/mode pairs fail safe as "Needs attention" with no
     unsafe mutation.
8. **Lifecycle operations enforce their domains server-side.**
   `refresh_connection` rejects non-OAuth credentials without mutating status
   or counters. The UI shows "Refresh Access" only for OAuth.
   `test_connection` may remain for reference modes, but tests and UI must be
   honest that it proves vault resolution; discovery is the provider-level
   check for discovery providers. Do not move discovery into the request path.
9. **Make the local store deterministic and durable.** Add a local-only
   secret-store path setting separate from `LOCAL_STORAGE_ROOT`; secrets must
   not sit beneath a potentially served object root. Anchor a relative path to
   the API root derived from `__file__`, never `Path.cwd()`, while preserving
   `apps/api/.local/secrets.enc.json`. Use an OS-level inter-process lock and
   same-directory atomic replace for read/modify/write; retain `0600`.
10. **Separate notifications.** Add an edge-triggered `needs_credential`
    notification ("Replace integration credential"). Keep `needs_reauth`
    OAuth-only. Provider summaries treat both as "Needs attention." Never put a
    rendered secret reference in notification copy.
11. **Fix the visible typo.**
    `integrationAuthModeLabel("service_account")` returns
    `"Service Account Key"`, not `"Service Account Ley"`.

## Current state

Verified at `f24cc8c`:

- `apps/api/services/secrets/providers/local.py:19-39` derives its path from
  `Path(settings.LOCAL_STORAGE_ROOT).parent`, relative to CWD, uses only a
  `threading.Lock`, and raises `IntegrationAuthError` for an absent reference.
- `apps/api/services/secrets/resolve_secret.py:21-44` audits then re-raises
  resolution failures.
- `apps/api/services/integrations/discovery/run_discovery.py:151-177` maps
  every `IntegrationAuthError` to `needs_reauth`; other failures become
  `error` or `degraded`.
- `apps/api/services/integrations/discovery/handlers.py:52-70` gives auth
  failures a distinct terminal path; generic failures notify on final attempt.
- `apps/api/models/integrations.py:122-139` and
  `apps/api/services/integrations/domain.py` define the eight-state CHECK and
  transition law. The next core migration is `0027`.
- `apps/api/services/integrations/connections/test_connection.py:65-100`
  performs provider identity I/O only for OAuth; reference modes only resolve
  their secret.
- `apps/api/services/integrations/connections/refresh_connection.py:38-65`
  unconditionally invokes the OAuth refresh seam.
- `connect_api_key.py` and `connect_service_account.py` contain the
  reference-only intake, validation, audit, and discovery patterns the
  replacement service must reuse. No existing-connection replacement route
  exists.
- `apps/web/src/features/integrations/components/connection-status.ts:42-47`
  maps every `needs_reauth` from status alone.
- `connection-row.tsx:188-198` offers OAuth reconnect when the provider
  supports OAuth, not when the connection uses it, and exposes "Refresh
  Access" for every non-revoked connection.
- `apps/web/src/features/integrations/format.ts:17-19` contains
  `"Service Account Ley"`.
- Regression homes include
  `tests/services/secrets/test_local_secrets_provider.py`,
  `tests/services/integrations/test_run_discovery.py`,
  `test_discovery_handler.py`, `test_needs_reauth_notification.py`,
  `tests/routes/integrations/test_connection_lifecycle_routes.py`,
  `test_service_account_connect.py`, and
  `apps/web/tests/features/integrations/connection-status-badge.test.ts`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| API lint/format | `make api-lint && make api-format-check` | exit 0 |
| Migration drift | `make api-migrations-check` | exit 0, no drift |
| Focused backend | `cd apps/api && uv run pytest tests/services/secrets/test_local_secrets_provider.py tests/services/integrations/test_run_discovery.py tests/services/integrations/test_discovery_handler.py tests/services/integrations/test_needs_reauth_notification.py tests/routes/integrations/test_connection_lifecycle_routes.py tests/routes/integrations/test_service_account_connect.py -q` | all pass |
| Focused frontend | `cd apps/web && pnpm vitest run tests/features/integrations && npm run typecheck -- --pretty false` | all pass |
| Full gate | `make check` | API and web gates pass |

## Suggested executor toolkit

- Use the `fastapi` skill, if available, for the request schema, service,
  route, typed exception mapping, and tests.
- Use `frontend-design` only to fit the replacement dialog into the existing
  provider page; this is not a redesign.
- If `components.json` exists, use `shadcn` for existing dialog/form
  composition rather than adding primitives.

## Scope

**In scope:**

- Secret-resolution availability exception taxonomy.
- Deterministic local secret path, cross-process locking, atomic persistence,
  and equivalent cloud-provider exception normalization where unambiguous.
- `needs_credential` CHECK/migration/domain transitions, discovery
  classification, context blocking, rediscovery skip law, notifications, and
  status consumers.
- Existing-connection API-key/service-account replacement service, schema,
  route, audit, enqueue, and tests.
- OAuth-only refresh guard and accurate test-connection contract.
- Auth-mode-aware status/actions, replacement forms, query invalidation,
  tests, and the label typo.
- Governance §1/§5/§6 updates when implementation lands, and relevant
  `AGENTS.md` updates if setup, routes, env, or architecture changes.

**Out of scope:**

- Google JWT claims/token caching, developer-token handling, Ads discovery, or
  BigQuery query authorization.
- Changing a connection's auth mode.
- Provider-specific synchronous discovery or live-network tests.
- Automatic deletion of superseded external secret versions.
- A generalized health framework, background secret-manager monitor, or new
  notification channels.
- Renaming OAuth's `needs_reauth` or changing unrelated integration copy.

## Git workflow

- Suggested branch: `fix/090-auth-mode-aware-integration-recovery`.
- If the operator authorizes commits, separate backend taxonomy/storage,
  replacement lifecycle, frontend recovery, and docs.
- Do not commit, push, or open a PR without explicit human approval.

## Execution slices

### Slice A — Failure taxonomy and local-store reliability

1. Add the typed 503 availability exception. Normalize local missing,
   corrupt, and unreadable references plus equivalent cloud cases. Preserve
   resolve-failure audit behavior and redaction.
2. Add the explicit store-path setting, stable API-root resolution, env/docs,
   bootstrap, and Compose changes required to preserve the existing file.
3. Add inter-process locking and atomic replace. Test permissions, missing
   store, malformed ciphertext, two independent provider instances, concurrent
   version writes, and reads during writes using only temporary paths.
4. Route vault availability through discovery's generic retry and
   `error`/`degraded` path. Add the incident regression: prior-success service
   account + unavailable vault retains credential/resources, becomes
   `degraded`, emits no auth notification, and later returns to `active`.

**Verify**:
`cd apps/api && uv run pytest tests/services/secrets/test_local_secrets_provider.py tests/services/integrations/test_run_discovery.py tests/services/integrations/test_discovery_handler.py -q`
→ all pass.

### Slice B — Auth-mode status law and replacement lifecycle

1. Add `needs_credential` via core migration `0027`, domain transitions,
   context unavailability, rediscovery exclusions, provider summaries, and
   every exhaustive consumer. Preserve OAuth behavior.
2. Classify genuine provider auth failure by credential auth mode and add the
   edge-triggered replacement notification.
3. Implement replacement per decisions 4–6 by reusing parsing, references,
   authorization, auditing, and enqueue helpers.
4. Guard refresh as OAuth-only and pin reference-mode `test_connection`
   semantics.
5. Test migration round-trip; RBAC; mode mismatch; OAuth/revoked/missing/raced
   rejection; service-account, API-key, and reference replacement; redaction;
   deduplicated enqueue; and cleanup after persistence failure.

**Verify**:
`make api-migrations-check && cd apps/api && uv run pytest tests/services/integrations tests/routes/integrations -q`
→ all pass.

### Slice C — Truthful recovery UI and copy

1. Add `needs_credential` to the hand-written type. Make status presentation
   accept connection context; never select actions from
   `provider.auth_modes.includes(...)`.
2. Add a replacement mutation and reuse existing API-key/service-account form
   models and fields in replacement mode. Do not edit the label. Clear secret
   state on success, failure, and close; invalidate connection, provider
   summary, resources, and discovery queries.
3. Show OAuth reconnect/refresh only for OAuth; show replacement for
   `needs_credential`; show discovery retry for operational/stalled/degraded
   cases where permitted. Preserve `canEdit`.
4. Fix the typo. Add a mixed-mode Google Ads regression proving a
   service-account row never renders OAuth recovery merely because Google Ads
   also supports OAuth.
5. Run keyboard/responsive QA in both themes. Focus must return from the
   dialog; failures must not echo values; success must reuse the connection
   row and enter discovery.

**Verify**:
`cd apps/web && pnpm vitest run tests/features/integrations && pnpm check`
→ all pass.

### Slice D — Full gate and documentation reconciliation

1. Run:
   `rg -n "needs_reauth|needs_credential|IntegrationAuthError|Refresh Access|Service Account Ley" apps/api apps/web docs/architecture/governance.md`.
   Review every match: no reference mode reaches `needs_reauth`, no vault
   availability raises auth, no non-OAuth UI offers OAuth recovery, and no
   typo remains.
2. Update governance §1 with replacement RBAC, §5 with rotation/local-store
   behavior, and §6 with separate auth/replacement/discovery notifications.
   Do not cite plan numbers from runtime code.
3. Run `make check`, record exact totals and unavailable live/browser QA, then
   reconcile indexes and move this plan to `docs/plans/complete/`.

## Test plan

Backend:

- stable store path from different CWDs;
- independent processes cannot lose versions; readers never see partial data;
- missing/corrupt/unreadable references raise the operational exception and
  retain redacted failure audit;
- vault unavailable → `degraded` after prior success or final `error` on first
  discovery, then recovery without credential/resource loss;
- OAuth 401 → `needs_reauth`; reference-mode 401 → `needs_credential`;
- same-status failures do not duplicate notifications;
- replacement RBAC, validation, locking, persistence, redaction, transition,
  and enqueue;
- non-OAuth refresh rejection is mutation-free; and
- migration upgrade/downgrade restores the exact CHECK.

Frontend:

- complete status/auth-mode presentation matrix and impossible-pair fallback;
- mixed-mode Google Ads service account has no OAuth recovery;
- OAuth retains "Sign in again" and "Refresh Access";
- replacement payloads, secret-state clearing, and query invalidation;
- read-only/member roles gain no credential actions; and
- exact `"Service Account Key"` label.

Use existing factories, mocked transport, and temporary stores. No live
provider calls belong in pytest.

## Done criteria

- [x] `needs_reauth` is reachable only for OAuth.
- [x] Rejected service-account/API-key credentials use `needs_credential` and
      the replacement notification.
- [x] Vault unavailability uses neither credential-action status and preserves
      prior resources/credentials through retry.
- [x] API and worker resolve one store path; writes are locked and atomic.
- [x] Admin/owner can replace a key on the existing connection without value
      exposure or duplicate connection creation.
- [x] OAuth refresh is rejected and hidden for non-OAuth credentials.
- [x] Mixed-mode Google Ads service-account rows never show OAuth recovery.
- [x] `"Service Account Ley"` has zero matches.
- [x] Migration drift, focused suites, and `make check` pass.
- [x] Governance, roadmap, README, and this status are reconciled.

## STOP conditions

Stop and report if:

- A non-local/test non-OAuth connection already persists `needs_reauth`; a
  maintainer-approved data migration policy is then required.
- A cloud secret provider can only distinguish vault availability by parsing
  unsafe/free-text response content.
- Preserving the local store requires copying, decrypting, or printing values.
- Safe cross-process locking needs a new runtime dependency or unsupported
  platform contract; present the trade-off first.
- Replacement cannot retain the previous cloud secret version. Never
  overwrite/delete the only known-good version.
- Validation would require synchronous provider discovery. Keep it async.
- The route needs weaker RBAC than governance §1 or exposes metadata to
  member/read-only users.
- A focused gate fails twice after one reasonable correction, or the fix
  expands into provider tool/runtime behavior outside Scope.

## Maintenance notes

- Review exception provenance, auth-mode branching, row locks, cleanup, audit
  payloads, and rendered recovery actions before cosmetic copy.
- Superseded app-managed versions remain after successful replacement because
  ownership is not explicit. A later cleanup plan may add ownership metadata
  and retention but must never delete external versions.
- Every future auth mode must define rejection status, replacement, refresh,
  notification, and presentation before entering `AUTH_MODES`.
- Reference-mode `test_connection` proves vault resolution only. A future
  provider identity-probe hook belongs in a separate plan.
- Cloud secret managers remain mandatory outside local environments; do not
  loosen that validation.
