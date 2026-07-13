# Plan 039: Integration resource discovery, selection, and status machine

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md` and flip the governance cells listed in
> "Done criteria" in `docs/architecture/governance.md`.
>
> **Notes pre-flight (run before Step 1)**: this plan implements slices of
> `docs/architecture/governance.md` §1 (resource selection row), §3
> (integration resources/discovery runs 90 d; credentials 30 d post-revoke
> — the sweep half), and §6 (needs_reauth / discovery-failure
> notifications to the connecting user), and honors
> `docs/architecture/integration-packaging.md` §4.6 import laws (the
> harness never imports `integrations.*`; resolution goes through the
> loader). Re-read those sections; the notes win over this plan.
>
> **Drift check (run first)**:
> `git diff --stat edc3abc..HEAD -- apps/api/services/integrations/ apps/api/services/jobs/ apps/api/workers/ apps/api/routes/integrations/ apps/api/models/integrations.py apps/api/models/jobs.py apps/api/services/notifications/ apps/api/core/settings/`
> The 037 implementation commit and 038's additions
> (`routes/integrations/`, connection ops, the enqueue seam comments) are
> EXPECTED — verify them against those plans' contracts rather than
> treating the diff as drift. Any OTHER in-scope change is a STOP-grade
> mismatch against the "Current state" excerpts (verified 2026-07-10).

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (background jobs mutating connection state; wrong
  transitions strand connections, but no new secret-bearing surface)
- **Depends on**: 030 (hard, **DONE** — job harness), 037 (hard,
  **DONE** — tables, status guard, manifest + loader), 038 (**hard** —
  the connect flows that produce `discovery_pending` connections and the
  enqueue seam comments)
- **Category**: Phase 4a integrations (roadmap `000_MASTER_ROADMAP.md` §4
  Phase 4a row 039; decisions D3, D4, D11)
- **Planned at**: commit `0cbbb39`, 2026-07-06. **Consolidated** at
  2026-07-10: plans 061 (plugin resolution), 074 (periodic
  re-discovery), 080 (four-kind smoke, notifications path), and roadmap
  decision D11 (no fake provider) folded into the body; anchors
  re-verified against the tree with the 037 implementation present
  (post-`edc3abc`).

## Decisions taken

1. **Discovery is a job, never a request-path call**: kind
   `integrations.discover_resources` on the 030 harness. The OAuth
   callback and api-key connect only `enqueue_job(...)` at 038's named
   seam and return — a slow or failing provider can never hang or fail
   the browser redirect. A test pins that the callback service performs
   no discovery I/O.
2. **Enqueue shape**: `kind="integrations.discover_resources"`,
   `subject_type="integration_connection"`, `subject_id=connection_id`,
   empty payload (ids only per 030's payload discipline). 030's
   partial-unique in-flight dedup index then gives "at most one
   discovery in flight per connection" for free — re-triggering during a
   run returns the existing job.
3. **Provider dispatch resolves through the loaded plugin, never by
   importing `integrations.*`** (packaging note §4.6). The delivered
   loader (`services/integrations/loader.py:12`) registers only the
   manifest and drops the plugin object — this plan extends it with a
   module-level `LOADED_PROVIDER_PLUGINS: dict[str,
   IntegrationProviderPlugin]` populated during `load_enabled_providers`
   so the discovery handler can resolve `plugin.discover_resources` by
   provider key. A loaded plugin with `discover_resources=None` on a
   `requires_discovery` manifest raises
   `IntegrationValidationError("provider discovery not implemented")` —
   expected for all shipped providers until 041 lands; documented, not a
   gap.
4. **The handler is idempotent by construction** (030 contract:
   at-least-once execution). It diffs provider results against
   `integration_resources` keyed by the unique constraint
   `(connection_id, resource_type, external_id)`: new → insert
   `available`; returned-and-known → update
   `last_seen_at`/`display_name`/`writable`/`permissions_metadata`,
   resurrect `removed` rows; known-but-missing → `removed` +
   `removed_at` (rows are never deleted here — `enabled` selections
   survive transient provider blips; only the sweep hard-deletes).
   Running it twice yields identical rows.
5. **`needs_resource_selection` is computed from data, never stored by
   hand**: `recompute_connection_status` derives the target — discovery
   succeeded ∧ `manifest.requires_discovery` ∧ zero `enabled` live
   resources → `needs_resource_selection`; ≥1 enabled →
   `active`. Every writer (discovery handler, selection service) calls
   it; nothing else assigns those two statuses. All transitions still
   flow through 037's `transition_connection_status` guard.
6. **Failed discovery keeps the credential** (donor rule: users retry
   without reconnecting). Failure path: mark the
   `integration_discovery_runs` row `failed`, transition the connection
   to `degraded` (had a prior succeeded run) or `error` (never
   completed), leave the credential untouched. The retry route
   re-enqueues without re-auth. Only an auth-class failure
   (`IntegrationAuthError` from the credential service) transitions to
   `needs_reauth` instead.
7. **Notification wiring per governance §6** (recipient: the connecting
   user, `connection.connected_by_user_id`; in-app via
   `create_notification`,
   `services/notifications/create_notification.py:21`):
   - `integration_needs_reauth` — emitted on the **transition into**
     `needs_reauth` (once per transition, not per failed call) via an
     `on_enter` hook in `transition_connection_status`, not sprinkled
     notify calls.
   - `integration_discovery_failed` — emitted **only after the final
     retry** (030 contract). The handler checks
     `job.attempts >= job.max_attempts` before raising its terminal
     failure and emits the notification itself. Discovery jobs are
     therefore enqueued **without** `initiated_by_user_id` — otherwise
     030's generic `job_failed` notification would double-notify.
     Recorded as the deliberate choice.
8. **One retention sweep kind, `integrations.sweep_stale`**
   (self-rescheduling, `ensure_*` idempotent enqueue — the
   `sweep_terminal_jobs.py` pattern). It enforces governance §3:
   hard-delete `integration_discovery_runs` older than 90 d, hard-delete
   `integration_resources` rows `removed`/soft-deleted for 90 d, and
   hard-delete revoked credentials + their revoked/soft-deleted
   connections 30 d after `revoked_at` (tokens were already
   crypto-shredded at revoke; audit rows survive via SET NULL FKs,
   `models/audit_event.py:19,37,44`). It also expires never-completed
   `auth_pending` connections older than 7 d and purges expired
   `integration_oauth_states` rows (038's pending PKCE rows).
9. **Periodic re-discovery, `integrations.rediscover_stale`** (same
   self-rescheduling pattern): each pass calls `enqueue_discovery` for
   every non-deleted `requires_discovery` connection in
   `{active, needs_resource_selection, degraded}` whose newest
   **succeeded** discovery run is older than
   `INTEGRATIONS_REDISCOVERY_INTERVAL_SECONDS` (default 86400).
   `needs_reauth`/`revoked`/`auth_pending` are skipped (auth first);
   `error` stays manual-retry-only. Rationale: 040 gates write fan-out
   on `writable`/`permissions_metadata` fail-closed and 041 derives
   those from provider role checks — an upstream permission revoke must
   flip `writable=false` without a human pressing re-discover.
   Notification semantics unchanged (decision 7 as written).
10. **Resource selection RBAC**: per governance §1, selection = member+
    (`require_editor`); viewing = `require_read`. For user-owned
    connections, selection is additionally restricted to the owner (or
    admin+), reusing 038's `require_connection_mutation_allowed`.
    Manual re-discovery uses the same member+ rule (it refreshes our
    mirror — not credential surgery).
11. **Selection is a bulk PUT of enabled ids** (`enabled_resource_ids`
    replace-set per connection), not per-resource toggles — 042 wants
    one save; the service validates every id belongs to the connection
    and is not `removed`, applies the diff, audits one UPDATE with
    added/removed id lists, then `recompute_connection_status`.
12. **Settings**: `INTEGRATIONS_DISCOVERY_TIMEOUT_SECONDS` (default 300,
    the `@job_handler(timeout=...)` override),
    `INTEGRATIONS_STALE_RETENTION_DAYS` (default 90, §3),
    `INTEGRATIONS_REVOKED_RETENTION_DAYS` (default 30, §3 credentials),
    `INTEGRATIONS_SWEEP_INTERVAL_SECONDS` (default 3600),
    `INTEGRATIONS_REDISCOVERY_INTERVAL_SECONDS` (default 86400). The
    retention defaults come straight from governance §3; changing them
    means updating the note, not just settings.
13. **Tests prove the engine with a suite-local test provider** (D11):
    registered through the loader/plugin seam in test fixtures only —
    a test plugin whose `discover_resources` is a real callable, with
    any provider HTTP mocked at the transport layer. No shipped
    manifest has a working discovery arm until 041.

## Superseded decisions

Recorded so they are not re-proposed; full history in
`docs/plans/complete/{061,074,080}-*.md` and roadmap decision D11.

- **Fake provider** (`services/integrations/providers/fake.py`, then
  `apps/api/integrations/fake/`) — removed by D11; the suite-local test
  provider (decision 13) replaces it everywhere.
- **Two-kind (then three-kind) smoke** — superseded by plan 080: 037's
  delivered `integrations.rotate_credential_encryption`
  (`services/jobs/handlers/rotate_credential_encryption.py:25`) plus
  this plan's three kinds make FOUR `integrations.*` kinds after this
  plan.
- **`services/notifications/service.py:105-158`** — the service was
  decomposed; the same `create_notification` signature lives at
  `services/notifications/create_notification.py:21`.

## Why this matters

038 leaves a conditional discovery-enqueue seam, while the shipped manifests
remain `requires_discovery=False` until their real callables land in 041.
Connections authenticated before then are honestly `active`; after 041 flips
the manifests, the periodic re-discovery pass picks them up. This plan makes
that status machine real:
connections flow to `needs_resource_selection`/`active` driven by what
the provider actually returned, users pick which sub-entities (Google
Ads accounts under an MCC, Airtable bases — D4) agents may touch,
failures notify the person who connected (§6) without burning the
credential, and the 90 d/30 d retention laws (§3) get their sweeper.
Plan 040 cannot resolve active context without `enabled` resources;
041's operations refuse to ship against unselected, undiscovered
connections; 042's resource-selection UI is a rendering of these routes.

## Current state

Anchors verified 2026-07-10 against the tree with the 037 implementation
present. 038 deliverables are consumed-and-verified-at-execution.

- **Jobs harness (030, delivered)**: `enqueue_job`
  (`services/jobs/enqueue_job.py:20`), `@job_handler(kind=...,
  timeout=..., max_attempts=...)` (`services/jobs/registry.py:32`,
  import-time duplicate rejection), handlers async `(db, job)`, kind
  pattern `^[a-z][a-z0-9_.]*$` (`services/jobs/domain.py:16` — dotted
  namespaces fit), the in-flight dedup index, the self-rescheduling
  sweep pattern + `ensure_sweep_job`
  (`services/jobs/handlers/sweep_terminal_jobs.py:41`). Assembly point:
  `services/jobs/handlers/__init__.py` imports handler modules for
  registration side effects (the `rotate_credential_encryption` line is
  the precedent). Worker bootstrap: `workers/job_runner.py:49-52` calls
  the `ensure_*` sweep functions each pass — the clean seam for this
  plan's two ensure calls.
- **037 delivered**: `models/integrations.py` — the four tables;
  `integration_resources` uniqueness
  `(connection_id, resource_type, external_id)` (line 189),
  `availability` CHECK `available/unavailable/removed`, `enabled`
  (default false), `writable` + `permissions_metadata`,
  `first_seen_at`/`last_seen_at`/`removed_at`;
  `integration_discovery_runs` counters
  (`resources_found/added/removed/unchanged`), `job_id` UUID no-FK,
  status `running/succeeded/failed`, `started_at`/`finished_at`,
  `error_code`/`error_message`. `services/integrations/domain.py`
  transition map; `transition_connection_status(db, connection, status,
  *, reason=None)` as the single status writer (same-status no-op);
  `ensure_fresh_credential` raising `IntegrationAuthError` on auth
  failures; `services/secrets.resolve_secret`; audit resource type
  `INTEGRATION_RESOURCE`. Manifest/loader/plugin:
  `manifest.py::PROVIDER_MANIFESTS` (with `requires_discovery`),
  `plugin.py::IntegrationProviderPlugin(manifest, discover_resources,
  tool_definitions)`, `loader.py:12::load_enabled_providers` — note the
  loader does NOT yet retain plugin objects (decision 3 extends it).
- **Will exist after 038** (verify): `routes/integrations/` +
  `services/integrations/connections/` ops; the
  `# discovery enqueue seam — plan 039` comments in
  `complete_oauth_callback.py` and `connect_api_key.py`;
  `require_connection_mutation_allowed` in
  `services/integrations/connections/utils.py`; the
  `integration_oauth_states` table (its expiry sweep lands here).
- **Notifications**: `create_notification(db, *, notification_type,
  title, body=None, payload=None, actions=None, recipient_user_id=None,
  target_email=None, workspace_id=None, source=None,
  requested_by_user_id=None)` at
  `services/notifications/create_notification.py:21` — audits its own
  CREATE; `workspace_id` nullable (user-owned connections may have no
  workspace context).
- **Governance rows**: §3 "Credentials (037) — 30 d after revoke";
  "Integration resources/discovery runs (039) — 90 d". §6 row
  "Integration `needs_reauth` / discovery failure → connecting user"
  (`governance.md:159`).
- **RBAC**: `require_editor`/`require_read`
  (`core/dependencies.py:268-269`).
- **Typed errors**: `core/exceptions/integration.py` —
  `IntegrationNotFoundError` (119, → 404), `IntegrationValidationError`
  (126, → 400), `IntegrationConnectionError` (91),
  `IntegrationAuthError` (98, → 401).
- **Audit FK survival**: `models/audit_event.py:19,37,44` — SET NULL
  FKs, so hard deletes keep audit rows.
- **Tests**: job-handler test precedent at
  `tests/services/jobs/` (register throwaway kinds in fixtures, clean
  up `JOB_HANDLERS` in teardown); integration factories at
  `tests/factories/integrations.py`.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations (this plan adds NO migration) |
| Kind registration smoke | `uv run python -c "from services.jobs.registry import JOB_HANDLERS; import services.jobs.handlers; print(sorted(k for k in JOB_HANDLERS if k.startswith('integrations.')))"` | `['integrations.discover_resources', 'integrations.rediscover_stale', 'integrations.rotate_credential_encryption', 'integrations.sweep_stale']` |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/integrations tests/routes/integrations -q` | all pass |
| Jobs regression | `TEST_DATABASE_URL=... uv run pytest tests/services/jobs -q` | all pass, untouched behavior |
| Worker smoke | `uv run python -m workers.job_runner --once` | one pass, exit 0 |
| Full API tests | `TEST_DATABASE_URL=... uv run pytest -q` | all pass |

## Scope

**In scope:**

- `apps/api/core/settings/integrations.py` (extend — decision 12 fields)
- `apps/api/services/integrations/loader.py` (extend —
  `LOADED_PROVIDER_PLUGINS`, decision 3)
- `apps/api/services/integrations/discovery/` (create): `__init__.py`,
  `run_discovery.py` (the core diff logic, handler-agnostic),
  `handlers.py` (`@job_handler` registrations), `enqueue_discovery.py`,
  `sweep_stale.py`, `rediscover_stale.py`
- `apps/api/services/integrations/connections/` (extend):
  `recompute_connection_status.py`, `list_connection_resources.py`,
  `update_resource_selection.py`, `notify_connection_event.py`
- `apps/api/services/integrations/connections/complete_oauth_callback.py`
  and `connect_api_key.py` (edit — replace the 038 seam comments with
  `enqueue_discovery`)
- `apps/api/services/integrations/connections/transition_connection_status.py`
  (edit — the `on_enter(needs_reauth)` notification hook, decision 7)
- `apps/api/services/jobs/handlers/__init__.py` (edit — one import line
  so the integration handlers register) and `workers/job_runner.py`
  (edit — two `ensure_*` calls beside lines 49-52)
- `apps/api/routes/integrations/` (extend, route-per-file):
  `list_connection_resources.py`, `update_resource_selection.py`,
  `trigger_discovery.py` + `__init__.py` composition
- `apps/api/tests/services/integrations/` (extend),
  `apps/api/tests/routes/integrations/` (extend),
  `apps/api/tests/factories/integrations.py` (extend — discovery-run
  factory + test-provider resource seeding helper)

**Out of scope (do NOT touch):**

- Any Alembic migration — 037/038 shipped the schema. Needing a column
  is a STOP.
- Active context, context groups, fan-out execution — 040 (resource
  `enabled` selection is this plan; *which enabled resource a run uses*
  is 040).
- Real provider discovery implementations (Google Ads MCC traversal,
  Airtable base listing) — 041 fills each package's
  `discover_resources`; until then every shipped provider raises
  not-implemented (decision 3).
- UI — 042. 030's harness internals (`claim_jobs`, backoff, dedup
  index) — consume, never modify.

## Git workflow

- Branch: `advisor/039-integration-resource-discovery`
- Commit style: `API - Integration Resource Discovery`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings + plugin retention

Add the decision 12 fields to `IntegrationsSettingsMixin`, all
`Field(..., gt=0)` with descriptions citing governance §3 for the
retention pair. Extend `loader.py` per decision 3
(`LOADED_PROVIDER_PLUGINS` populated in `load_enabled_providers`,
cleared/replaced on re-load so tests can re-register).

**Verify**: settings import prints `90`/`30` for the retention pair; a
quick `python -c` load with a monkeypatched allowlist shows the plugin
retained; ruff exit 0.

### Step 2: Discovery core (`discovery/run_discovery.py`)

`run_discovery(db, *, connection_id, job_id=None) ->
IntegrationDiscoveryRun` — handler-agnostic so tests and a future
synchronous admin tool share it:

1. Load the connection (+ manifest); not found / revoked →
   `IntegrationNotFoundError` / `IntegrationConnectionError`.
2. Create the `integration_discovery_runs` row (`running`, `job_id`).
3. Resolve credentials via `ensure_fresh_credential` (oauth) or
   `resolve_secret` (reference modes). `IntegrationAuthError` here →
   run `failed` with `error_code="auth"`; the connection is flipped to
   `needs_reauth` by the credential path and the §6 notification fires
   from the transition hook — do NOT also emit discovery-failed.
4. Fetch resources via `LOADED_PROVIDER_PLUGINS[provider_key]
   .discover_resources` (decision 3; None → not-implemented error).
5. Apply the idempotent diff (decision 4), stamping
   `first_seen_at`/`last_seen_at`, `writable`, `permissions_metadata`,
   counters onto the run row.
6. Mark the run `succeeded`, then `recompute_connection_status`.
7. Audit one UPDATE on `INTEGRATION_RESOURCE` with the counters.

On any non-auth exception: run row `failed` +
`error_code`/`error_message` (1000-char sanitize rule via a local
helper), connection → `degraded`/`error` per decision 6, credential
untouched, re-raise so the harness counts the attempt.

**Verify**: Step 8 drives it with the suite-local test provider; run
twice → identical resource rows, counters `added=0, unchanged=N` on the
second pass.

### Step 3: Status recomputation (`recompute_connection_status.py`)

`recompute_connection_status(db, connection) -> str` (decision 5):
derive the target from the latest discovery-run status, the count of
live (`deleted=false`, availability != 'removed') `enabled` resources,
and `manifest.requires_discovery`:

- discovery succeeded ∧ requires_discovery ∧ enabled == 0 →
  `needs_resource_selection`
- (enabled ≥ 1) ∨ (not requires_discovery) → `active`
- no change otherwise (degraded/error/needs_reauth are event-driven,
  not recomputed)

Apply via `transition_connection_status`; same-status is its existing
no-op. Module docstring states the invariant: **no other code assigns
`needs_resource_selection` or promotes to `active`** — grep is the
review check.

**Verify**: 037's transition-map tests still green; Step 8 pins the
compute table.

### Step 4: Handlers + enqueue + sweeps

`discovery/handlers.py`:

```python
@job_handler(kind="integrations.discover_resources",
             timeout=settings.INTEGRATIONS_DISCOVERY_TIMEOUT_SECONDS)
async def discover_resources(db, job):
    try:
        await run_discovery(db, connection_id=job.subject_id, job_id=job.id)
    except IntegrationAuthError:
        raise  # needs_reauth + its notification already handled; let the job fail
    except Exception:
        if job.attempts >= job.max_attempts:   # final attempt (030: claim already incremented)
            await notify_connection_event(db, connection_id=job.subject_id,
                                          event="discovery_failed")
        raise
```

`enqueue_discovery.py` — `enqueue_discovery(db, *, connection) -> Job`:
decision 2 shape, `workspace_id=connection.owner_workspace_id`, **no
`initiated_by_user_id`** (decision 7 — leave a comment saying exactly
why). Replace 038's two seam comments with calls to it (only for
`manifest.requires_discovery` providers).

`sweep_stale.py` (decision 8) — deletion order respects FKs (resources
and discovery runs cascade from connections; delete credentials last),
then self-reschedules; plus `ensure_integrations_sweep_job(db)`
following the `ensure_sweep_job` pattern. `rediscover_stale.py`
(decision 9) — same pattern, `ensure_integrations_rediscover_job(db)`.
Bootstrap both from `workers/job_runner.py` beside the existing
`ensure_*` calls (lines 49-52); imports must not enqueue.

Register the kinds with one import line in
`services/jobs/handlers/__init__.py` (the
`rotate_credential_encryption` precedent).

**Verify**: kind smoke prints the four kinds; `uv run python -m
workers.job_runner --once` exits 0 with both sweeps enqueued+executed;
`tests/services/jobs` untouched and green.

### Step 5: Notifications (`notify_connection_event.py`)

One op (decision 7) so wording/payload stay consistent —
`notify_connection_event(db, *, connection_id, event)` with
`event in {"needs_reauth", "discovery_failed"}`, calling
`create_notification`: `notification_type=f"integration_{event}"`,
`recipient_user_id=connection.connected_by_user_id`,
`workspace_id=connection.owner_workspace_id` (None for user-owned),
`source="integrations"`, `payload={"connection_id": ...,
"provider_key": ..., "label": ...}` (ids and display data — nothing
secret). Wire the `needs_reauth` case into
`transition_connection_status` as an on-enter hook: fires only when the
previous status differs.

**Verify**: Step 8 pins exactly-once semantics for both events.

### Step 6: Selection + discovery routes

Service ops:

- `list_connection_resources.py` — resources for a connection
  (excluding soft-deleted; including `removed` rows flagged so 042 can
  show "gone from provider"); read-scope + connection visibility per
  038's list rules.
- `update_resource_selection.py` (decision 11) — validates ids
  (unknown / other-connection / `removed` →
  `IntegrationValidationError`), applies the replace-set diff, audits
  UPDATE on `INTEGRATION_RESOURCE`
  (`{"enabled_added": [...], "enabled_removed": [...]}`), then
  `recompute_connection_status`.

Routes (route-per-file under `routes/integrations/`):

| File | Operation | Auth |
|------|-----------|------|
| `list_connection_resources.py` | `GET /integrations/connections/{connection_id}/resources` | `require_read` |
| `update_resource_selection.py` | `PUT /integrations/connections/{connection_id}/resources/selection` | `require_editor` + `require_connection_mutation_allowed` |
| `trigger_discovery.py` | `POST /integrations/connections/{connection_id}/discover` | `require_editor` + ownership rule; 202 with the job id; in-flight dedup returns the existing job |

CSRF/rate-limit posture: all three are ordinary session-authenticated
SPA routes — CSRF enforced by default, no exemptions, no new rate
limits (discovery triggering is already dampened by the in-flight
dedup).

**Verify**: route smoke shows the three new paths; RBAC tests green.

### Step 7: Test-provider fixtures

Extend `tests/factories/integrations.py` with
`create_integration_discovery_run(...)` and a helper to seed
test-provider resources. Add a fixture that registers the suite-local
test provider as a full plugin (manifest with `requires_discovery=True`
+ a controllable `discover_resources` callable) in
`LOADED_PROVIDER_PLUGINS`/`PROVIDER_MANIFESTS`, cleaned up in teardown.

### Step 8: Tests

- `tests/services/integrations/test_run_discovery.py` (DB): happy path
  populates resources with counters; **idempotency** — second run
  changes nothing (`added=0`, same row ids, `last_seen_at` advanced);
  lifecycle — provider drops a resource → `removed`+`removed_at`,
  returns it later → resurrected `available` with `enabled` preserved;
  `writable`/`permissions_metadata` persisted; non-auth provider
  failure → run `failed`, connection `degraded`/`error`, **credential
  row untouched** and a follow-up `run_discovery` succeeds without
  reconnecting (decision 6 pinned); auth failure → `needs_reauth`, no
  discovery-failed notification; not-implemented arm raises for a
  shipped provider key (decision 3).
- `tests/services/integrations/test_recompute_status.py` (DB): the
  decision 5 table — zero enabled → `needs_resource_selection`;
  enabling one → `active`; disabling all → back; non-discovery provider
  → `active` straight after connect; recompute never touches
  degraded/error/needs_reauth.
- `tests/services/integrations/test_discovery_handler.py` (DB): enqueue
  → `run_once` executes end to end against the test provider;
  **enqueue dedup** — two enqueues for one connection yield one
  in-flight job; failure below `max_attempts` → retry, no notification
  row; final attempt → `failed` job, exactly ONE
  `integration_discovery_failed` notification to
  `connected_by_user_id`, and no generic `job_failed` notification (the
  no-initiator choice); **the callback never discovers** — complete a
  test-provider OAuth connect (transport-mocked endpoints) and assert a
  pending job row exists while the test provider's `discover_resources`
  call count is still 0 (decision 1 pinned).
- `tests/services/integrations/test_needs_reauth_notification.py` (DB):
  transition into `needs_reauth` → one notification; a second failed
  refresh while already `needs_reauth` → no second; reconnect
  (→ `discovery_pending`) then failure again → a new one.
- `tests/services/integrations/test_sweep_stale.py` (DB): 91-day-old
  discovery runs deleted, 89-day-old kept; long-removed resources
  deleted, fresh `removed` kept; connection+credential revoked 31 d ago
  hard-deleted with audit rows surviving (SET NULL FKs), 29 d kept;
  stale `auth_pending` expired; expired `integration_oauth_states`
  purged; handler re-enqueues itself.
- `tests/services/integrations/test_rediscover_stale.py` (DB): a
  connection with a `writable=true` resource and a succeeded run aged
  past the interval, the test provider now reporting `writable=false`
  → one sweep pass enqueues discovery (no initiator) and the run flips
  the resource to `writable=false` (the value 040's `write_allowed`
  reads); fresh-run connections not enqueued;
  `needs_reauth`/`revoked` skipped; an in-flight discovery not
  duplicated.
- `tests/routes/integrations/test_resource_routes.py` (DB): list
  includes `removed` flagged rows; selection replace-set applies +
  recomputes status + audits the diff; invalid/foreign/removed ids →
  400; RBAC — read_only can list, cannot select (403); non-owner member
  cannot select on another user's user-scoped connection; trigger
  returns 202 and dedups.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/integrations
tests/routes/integrations tests/services/jobs -q` → all pass; skips
(not failures) without the env var; full suite green; worker `--once`
smoke exits 0.

## Test plan

Covered by Step 8 (~30–36 tests). The pinned invariants: **discovery
never runs in the request path**, **handler idempotency under
at-least-once delivery**, **failed discovery keeps the credential —
retry without reconnect**, **`needs_resource_selection`/`active` are
computed from data by exactly one function**, **each §6 notification
fires exactly once** (per transition / only after final retry, no
double via 030's generic path), **stale write permissions self-heal via
re-discovery**, and **the 90 d / 30 d retention boundaries with audit
survival** (§3).

## Done criteria

- [ ] `uv run ruff check .` exits 0; `uv run alembic check` clean (no
      new migration in this plan)
- [ ] `TEST_DATABASE_URL=... uv run pytest -q` exits 0 (full suite,
      including an untouched `tests/services/jobs`)
- [ ] Kind smoke prints exactly the four kinds listed in the Commands
      table
- [ ] `uv run python -m workers.job_runner --once` exits 0
- [ ] Grep shows `transition_connection_status` is still the only
      assigner of `IntegrationConnection.status`, and
      `recompute_connection_status` the only source of
      `needs_resource_selection`
- [ ] The 038 seam comments are gone, replaced by `enqueue_discovery`
      calls
- [ ] No `import integrations` (or `from integrations`) outside
      `services/integrations/loader.py` — packaging §4.6 law holds
- [ ] `docs/architecture/governance.md` updated: §3 rows "Credentials
      (037)" and "Integration resources/discovery runs (039)" →
      `[implemented: plan 039]`; §6 row "Integration needs_reauth /
      discovery failure" → `[implemented: plan 039]`; §1 row "Select
      integration resources / edit context groups (039–040)" → annotate
      `[implemented (selection): plan 039]` (context groups remain
      040's)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- 038 is not implemented, or its delivered contract differs from the
  assumptions here (seam comments missing,
  `require_connection_mutation_allowed` absent,
  `integration_oauth_states` shaped differently) — reconcile against
  038's plan doc first.
- The jobs harness contract differs: kind-name rule, handler signature
  `(db, job)`, attempts-at-claim semantics, or the
  notification-on-final-retry contract — decision 7's final-attempt
  check and decision 2's dedup depend on them exactly.
- There is no clean seam to bootstrap the ensure calls without editing
  030's claim/finalize internals — report rather than patching harness
  internals (as verified, `workers/job_runner.py:49-52` is the seam).
- Governance §3 retention values or the §6 recipient changed from the
  values cited here — the note wins.
- You feel the need to add a migration, implement Google Ads/Airtable
  API clients, resolve which resource a run should use, or build UI —
  037/041/040/042 scope leaking in.

## Maintenance notes

- **Consumers**: 040 (active context) reads `enabled` + `availability`
  + `writable` to build per-user-per-workspace selections and context
  groups across N connections (D3) — it treats `unavailable`/`removed`
  as non-resolvable. 041 fills each provider package's
  `discover_resources` (Google Ads MCC→account traversal populates
  `parent_external_id`; spend-capable accounts must set `writable` +
  `permissions_metadata` accurately — governance §2 / Gate G1). 042
  renders resource selection, discovery status/history from
  `integration_discovery_runs`, and the retry button on
  `degraded`/`error` connections.
- **Handler idempotency is a review gate**: any future change to
  `run_discovery` must keep the two-runs-identical property; the Step 8
  idempotency test is the tripwire — do not weaken it to "counters may
  differ".
- **Selection survives churn deliberately**: `enabled` persists through
  `unavailable`/`removed` and resurrections so a provider blip doesn't
  silently drop an agent's access scope. If product later wants
  auto-disable of long-removed resources, do it in the sweep with a
  notification, not in the diff.
- **Notification volume**: transition-edge + final-retry only. If 042
  adds an activity feed, resist per-attempt notifications — governance
  §6 ("every routine refresh — audit only") already rules on this.
- Reviewers should scrutinize: the final-attempt detection against
  030's claim-increments-attempts semantics (off-by-one double- or
  never-notifies), FK-safe deletion order in the sweep, the
  `on_enter(needs_reauth)` hook not firing on same-status no-ops, and
  that `enqueue_discovery` passes no `initiated_by_user_id`.
