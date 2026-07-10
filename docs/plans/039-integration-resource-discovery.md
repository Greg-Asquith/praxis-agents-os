# Plan 039: Integration resource discovery, selection, and status machine

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md` and flip the governance cells listed in
> "Done criteria" in `docs/architecture/governance.md`.
>
> **Governance pre-flight (run before Step 1)**: this plan implements slices
> of `docs/architecture/governance.md` §1 (resource selection row), §3
> (integration resources/discovery runs 90 d; credentials 30 d post-revoke —
> the sweep half), and §6 (needs_reauth / discovery-failure notifications to
> the connecting user). Re-read those sections; the note wins over this
> plan.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/services/integrations/ apps/api/services/jobs/ apps/api/workers/ apps/api/routes/integrations/ apps/api/models/integrations.py apps/api/models/jobs.py apps/api/services/notifications/ apps/api/core/settings/`
> `services/integrations/`, `routes/integrations/`, `models/integrations.py`,
> `services/jobs/`, and `models/jobs.py` are EXPECTED to exist (plans
> 030/037/038); verify them against those plans' contracts rather than
> treating the diff as drift. Any OTHER in-scope change since `0cbbb39` is a
> STOP-grade mismatch.
>
> **Amendment (plan 074) pre-flight**: the "Amendment (plan 074,
> 2026-07-07)" block at the end of this file amends this plan; where it
> conflicts with the body above, the amendment wins.

> **Amendment (2026-07-07, plan 061 — provider packaging)**: per
> `docs/architecture/integration-packaging.md`, the fake provider lives at
> `apps/api/integrations/fake/` (not
> `services/integrations/providers/fake.py`), and the discovery job
> resolves each provider's `discover_resources` function through the
> loaded `IntegrationProviderPlugin` (037 amendment) rather than importing
> a provider module directly — the harness must not import `integrations.*`
> (note §4.6).

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (background jobs mutating connection state; wrong
  transitions strand connections, but no new secret-bearing surface)
- **Depends on**: 030 (**hard** — job harness: `enqueue_job`,
  `@job_handler`, sweep pattern), 037 (**hard** — tables, status guard,
  manifest, fake provider), 038 (**hard** — the connect flows that produce
  `discovery_pending` connections and the enqueue seam comments)
- **Category**: Phase 4a integrations (roadmap `000_MASTER_ROADMAP.md` §4
  Phase 4a row 039; donor `DONOR_PORT_ROADMAP.md` §4.2 / §6 row C3;
  decisions D3, D4)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Discovery is a job, never a request-path call** (donor fix, roadmap
   row): kind `integrations.discover_resources` on the 030 harness. The
   OAuth callback and api-key connect only `enqueue_job(...)` at 038's
   named seam and return — a slow or failing provider can never hang or
   fail the browser redirect. A test pins that the callback service
   performs no discovery I/O.
2. **Enqueue shape**: `kind="integrations.discover_resources"`,
   `subject_type="integration_connection"`, `subject_id=connection_id`,
   empty payload (the connection row is the payload — ids only per 030's
   payload discipline). 030's partial-unique in-flight dedup index then
   gives us "at most one discovery in flight per connection" for free —
   re-triggering during a run returns the existing job.
3. **The handler is idempotent by construction** (030 contract:
   at-least-once execution). It diffs provider results against
   `integration_resources` keyed by the 037 unique constraint
   `(connection_id, resource_type, external_id)`: new → insert
   `available`; returned-and-known → update `last_seen_at`/`display_name`/
   `writable`/`permissions_metadata`, resurrect `removed` rows; known-but-
   missing → `removed` + `removed_at` (rows are never deleted here —
   `enabled` selections survive transient provider blips via the
   `unavailable` state; only the sweep hard-deletes). Running it twice
   yields identical rows.
4. **`needs_resource_selection` is computed from data, never stored by
   hand** (donor design): `recompute_connection_status` derives the target
   status — discovery succeeded ∧ `manifest.requires_discovery` ∧ zero
   `enabled` live resources → `needs_resource_selection`; ≥1 enabled →
   `active`. Every writer (discovery handler, selection service) calls it;
   nothing else assigns those two statuses. All transitions still flow
   through 037's `transition_connection_status` guard.
5. **Failed discovery keeps the credential** (donor: "failed discovery
   keeps the credential so users retry without reconnecting"). Failure
   path: mark the `integration_discovery_runs` row `failed`, transition the
   connection to `degraded` (was previously `active`) or `error` (never
   completed a discovery), and leave the credential untouched. The retry
   route re-enqueues without any re-auth. Only an auth-class failure
   (`IntegrationAuthError` from the credential service) transitions to
   `needs_reauth` instead.
6. **Notification wiring per governance §6** (recipient: the connecting
   user, `connection.connected_by_user_id`; in-app via
   `create_notification`, `services/notifications/service.py:105-158`):
   - `integration_needs_reauth` — emitted on the **transition into**
     `needs_reauth` (once per transition, not per failed call). 037 built
     the status flip; this plan adds an `on_enter` hook to the transition
     op rather than sprinkling notify calls.
   - `integration_discovery_failed` — emitted **only after the final
     retry** (030 contract). The handler checks
     `job.attempts >= job.max_attempts` before raising its terminal
     failure and emits the notification itself, because it knows the
     connection context. Discovery jobs are therefore enqueued **without**
     `initiated_by_user_id` — otherwise 030's generic `job_failed`
     notification would double-notify. Recorded as the deliberate choice.
7. **One sweep kind, `integrations.sweep_stale`**, registered here per
   030's decision 6 pattern (self-rescheduling, `ensure_*` idempotent
   enqueue). It enforces BOTH governance §3 integration rows: hard-delete
   `integration_discovery_runs` older than 90 d, hard-delete
   `integration_resources` rows `removed`/soft-deleted for 90 d, and
   hard-delete revoked credentials + their revoked/soft-deleted
   connections 30 d after `revoked_at` (tokens were already crypto-shredded
   at revoke — the sweep removes the metadata rows; audit rows survive via
   SET NULL FKs, `models/audit_event.py:19,37,44`). It also expires
   never-completed `auth_pending` connections older than 7 d (038 decision
   6 left them inert).
8. **Resource selection RBAC**: per governance §1 "Select integration
   resources / edit context groups (039–040)" = member+ →
   `require_editor`; viewing resources = `require_read`. For user-owned
   connections, selection is additionally restricted to the owner (or
   admin+), reusing 038's `require_connection_mutation_allowed` helper.
   Manual re-discovery uses the same member+ rule (it is a read of the
   provider, a refresh of our mirror — not credential surgery).
9. **Selection is a bulk PUT of enabled ids** (`enabled_resource_ids`
   replace-set per connection), not per-resource toggles — the UI (042)
   wants one save; the service validates every id belongs to the
   connection and is not `removed`, applies the diff, audits one UPDATE
   with added/removed id lists, then `recompute_connection_status`.
10. **Settings**: `INTEGRATIONS_DISCOVERY_TIMEOUT_SECONDS` (default 300,
    the per-kind `@job_handler(timeout=...)` override),
    `INTEGRATIONS_STALE_RETENTION_DAYS` (default 90, §3),
    `INTEGRATIONS_REVOKED_RETENTION_DAYS` (default 30, §3 credentials),
    `INTEGRATIONS_SWEEP_INTERVAL_SECONDS` (default 3600). All
    `[default — confirm at review]` values come straight from governance
    §3; changing them means updating the note, not just settings.

## Why this matters

038 leaves discovery-requiring connections parked in `discovery_pending`
with an honest TODO. This plan makes the status machine real: connections
flow to `needs_resource_selection`/`active` driven by what the provider
actually returned, users pick which sub-entities (Google Ads accounts under
an MCC, Airtable bases — D4) agents may touch, failures notify the person
who connected (§6) without burning the credential, and the 90 d/30 d
retention laws (§3) get their sweeper. Plan 040 cannot resolve active
context without `enabled` resources; 041's operations refuse to ship
against unselected, undiscovered connections; 042's resource-selection UI
is a rendering of these routes.

## Current state

Anchors at `0cbbb39` for stable code; 030/037/038 deliverables are
consumed-and-verified-at-execution contracts.

- Will exist after 030 (verify): `services/jobs/` — `enqueue_job(db, *,
  kind, workspace_id=None, subject_type=None, subject_id=None,
  payload=None, ..., initiated_by_user_id=None)`, `@job_handler(kind=...,
  timeout=...)` decorator with import-time duplicate rejection, handlers
  async `(db, job)`, kind pattern `^[a-z][a-z0-9_.]*$` (dotted namespaces —
  `integrations.discover_resources` and `integrations.sweep_stale` fit),
  the in-flight dedup index on (kind, subject, hash), the
  `jobs.sweep_terminal` self-rescheduling sweep pattern +
  `ensure_sweep_job` idempotent enqueue, and the registry assembly point
  (`services/jobs/registry.py` imports `services.jobs.handlers`; 030's
  maintenance notes say consumer plans register kinds there — this plan
  registers via an import hook from its own package, keeping integration
  handlers in `services/integrations/`).
- Will exist after 037 (verify): `models/integrations.py` — the four
  tables; `integration_resources` uniqueness
  `(connection_id, resource_type, external_id)`, `availability` CHECK
  `available/unavailable/removed`, `enabled` flag, `writable` +
  `permissions_metadata`; `integration_discovery_runs` counters
  (`resources_found/added/removed/unchanged`), `job_id` UUID (no FK),
  status `running/succeeded/failed`; `services/integrations/domain.py`
  transition map; `transition_connection_status` as the single status
  writer; the `fake` provider's `discover_resources()`;
  `ensure_fresh_credential` raising `IntegrationAuthError` on auth
  failures; audit resource types `INTEGRATION_RESOURCE` etc.
- Will exist after 038 (verify): `routes/integrations/` +
  `services/integrations/connections/` ops; the
  `# discovery enqueue seam — plan 039` comments in
  `complete_oauth_callback.py` and `connect_api_key.py`;
  `require_connection_mutation_allowed` in
  `services/integrations/connections/utils.py`.
- Stable at `0cbbb39`:
  - Notifications: `services/notifications/service.py:105-158`
    `create_notification(db, *, notification_type, title, body=None,
    payload=None, actions=None, recipient_user_id=None, target_email=None,
    workspace_id=None, source=None, requested_by_user_id=None)` — already
    audits its own CREATE; `workspace_id` is nullable (user-owned
    connections may have no workspace context).
  - Governance §3 rows: "Credentials (037) — 30 d after revoke; tokens
    crypto-shredded at revoke"; "Integration resources/discovery runs
    (039) — ✓ / plain rows — 90 d". §6 row: "Integration needs_reauth /
    discovery failure → connecting user — emitting plan 039".
  - RBAC deps: `require_editor`/`require_read`
    (`core/dependencies.py:268-269`).
  - Typed errors: `IntegrationNotFoundError` (404),
    `IntegrationValidationError` (400), `IntegrationConnectionError` (400),
    `IntegrationAuthError` (401) — `core/exceptions/integration.py:91-137`.
  - Worker: one worker process; 030 adds `workers/main.py` supervising the
    schedule loop and the job loop — this plan adds NO worker wiring, only
    handlers.
  - Tests: DB-backed via `TEST_DATABASE_URL` gating; job-handler test
    precedent will exist at `tests/services/jobs/test_job_runner.py`
    (030 Step 7 — register throwaway kinds in fixtures, clean up
    `JOB_HANDLERS` in teardown).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations (this plan adds NO migration) |
| Kind registration smoke | `uv run python -c "from services.jobs.registry import JOB_HANDLERS; print(sorted(k for k in JOB_HANDLERS if k.startswith('integrations.')))"` | `['integrations.discover_resources', 'integrations.sweep_stale']` |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/integrations tests/routes/integrations -q` | all pass |
| Jobs regression | `TEST_DATABASE_URL=... uv run pytest tests/services/jobs -q` | all pass, untouched behavior |
| Worker smoke | `uv run python -m workers.job_runner --once` | one pass, exit 0 |
| Full API tests | `TEST_DATABASE_URL=... uv run pytest -q` | all pass |

## Scope

**In scope:**

- `apps/api/core/settings/integrations.py` (extend — decision 10 fields)
- `apps/api/services/integrations/discovery/` (create): `__init__.py`,
  `run_discovery.py` (the core diff logic, handler-agnostic),
  `handlers.py` (`@job_handler` registrations for both kinds),
  `enqueue_discovery.py`, `sweep_stale.py`
- `apps/api/services/integrations/connections/` (extend):
  `recompute_connection_status.py`, `list_connection_resources.py`,
  `update_resource_selection.py`, `notify_connection_event.py`
- `apps/api/services/integrations/connections/complete_oauth_callback.py`
  and `connect_api_key.py` (edit — replace the 038 seam comments with
  `enqueue_discovery`)
- `apps/api/services/integrations/connections/transition_connection_status.py`
  (edit — add the `on_enter(needs_reauth)` notification hook, decision 6)
- `apps/api/services/jobs/handlers/__init__.py` (edit — one import line at
  the 030 assembly point so integration handlers register;
  `services/jobs/registry.py` imports this package for side effects and
  names it the extension seam)
- `apps/api/routes/integrations/` (extend, route-per-file):
  `list_connection_resources.py`, `update_resource_selection.py`,
  `trigger_discovery.py` + `__init__.py` composition
- `apps/api/tests/services/integrations/` (extend),
  `apps/api/tests/routes/integrations/` (extend),
  `apps/api/tests/factories/integrations.py` (extend — discovery-run
  factory)

**Out of scope (do NOT touch):**

- Any Alembic migration — 037 shipped the schema, including
  `integration_discovery_runs`. Needing a column is a STOP.
- Active context, context groups, fan-out execution — 040 (resource
  `enabled` selection is this plan; *which enabled resource a run uses* is
  040).
- Real provider discovery implementations (Google Ads MCC traversal,
  Airtable base listing) — 041 fills the manifest dispatch with real
  clients; this plan runs against the `fake` provider and leaves the
  google_ads/airtable dispatch arms raising
  `IntegrationValidationError("provider discovery not implemented")`.
- UI — 042. Workers/compose/make wiring — 030 owns the loop.
- 030's harness internals (`claim_jobs`, backoff, dedup index) — consume,
  never modify.

## Git workflow

- Branch: `advisor/039-integration-resource-discovery`
- Commit style: `API - Integration Resource Discovery`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

Add the decision 10 fields to `IntegrationsSettingsMixin`
(`core/settings/integrations.py`), all `Field(..., gt=0)` with
descriptions citing governance §3 for the two retention values. No
validator changes.

**Verify**: settings import prints `90`/`30` for the retention pair; ruff
exit 0.

### Step 2: Discovery core (`services/integrations/discovery/run_discovery.py`)

`run_discovery(db, *, connection_id, job_id=None) -> IntegrationDiscoveryRun`
— handler-agnostic so tests and a future synchronous admin tool share it:

1. Load the connection (+ manifest); not found / revoked →
   `IntegrationNotFoundError` / `IntegrationConnectionError`.
2. Create the `integration_discovery_runs` row (`running`, `job_id`).
3. Resolve credentials via `ensure_fresh_credential` (oauth) or
   `resolve_secret` (reference modes). `IntegrationAuthError` here →
   run `failed` with `error_code="auth"`, connection already flipped to
   `needs_reauth` by 037's refresh path (the §6 notification fires from
   the transition hook, decision 6) — do NOT also emit discovery-failed.
4. Fetch resources via the manifest dispatch (fake:
   `providers/fake.py::discover_resources`; google_ads/airtable arms raise
   until 041 — out of scope note above).
5. Apply the idempotent diff (decision 3), stamping
   `first_seen_at`/`last_seen_at`, `writable`, `permissions_metadata`
   (write-permission metadata from the provider payload), counters onto
   the run row.
6. Mark the run `succeeded`, then `recompute_connection_status` (Step 3).
7. Audit one UPDATE on `INTEGRATION_RESOURCE` with the counters (039 rows
   survive in audit as "counters" per §3).

On any non-auth exception: run row `failed` +
`error_code`/`error_message` (reuse 030's 1000-char sanitize rule via a
local helper), connection → `degraded` (had a prior succeeded run) or
`error` (never succeeded), credential untouched (decision 5), re-raise so
the 030 harness counts the attempt.

**Verify**: unit-level tests (Step 7) drive it directly with the fake
provider; run twice → identical resource rows, counters
`added=0, unchanged=N` on the second pass.

### Step 3: Status recomputation (`recompute_connection_status.py`)

`recompute_connection_status(db, connection) -> str` (decision 4): derive
the target from data — latest discovery run status, count of live
(`deleted=false`, availability != 'removed') `enabled` resources, and
`manifest.requires_discovery`:

- discovery succeeded ∧ requires_discovery ∧ enabled == 0 →
  `needs_resource_selection`
- (enabled ≥ 1) ∨ (not requires_discovery) → `active`
- no change otherwise (degraded/error/needs_reauth are event-driven, not
  recomputed)

Apply via `transition_connection_status` (the single guard); same-status is
its existing no-op. Add a module docstring stating the invariant: **no
other code assigns `needs_resource_selection` or promotes to `active`** —
grep is the review check.

**Verify**: transition-map tests from 037 still green; Step 7 pins the
compute table.

### Step 4: Handlers + enqueue + sweep

`services/integrations/discovery/handlers.py`:

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
`initiated_by_user_id`** (decision 6 — avoids 030's generic double
notification; leave a comment saying exactly that). Replace 038's two seam
comments with calls to it (only for `manifest.requires_discovery`
providers).

`sweep_stale.py` (decision 7):

```python
@job_handler(kind="integrations.sweep_stale", timeout=120.0)
async def sweep_stale(db, job):
    # 1. DELETE integration_discovery_runs WHERE created_at < now()-90d      (§3)
    # 2. DELETE integration_resources WHERE (removed OR deleted) since > 90d (§3)
    # 3. hard-delete credentials+connections revoked > 30d                   (§3 credentials)
    # 4. expire auth_pending connections older than 7d (038 decision 6)
    # then self-reschedule (jobs.sweep_terminal pattern)
```

plus `ensure_integrations_sweep_job(db)` following 030's `ensure_sweep_job`
idempotent-enqueue pattern; call it from the sweep handler's
self-reschedule and once from `handlers.py` import-time? **No** — imports
must not enqueue. Wire it the same way 030 wires its own ensure call in the
worker pass IF 030 exposed a per-plan hook; otherwise (030 shipped only its
own built-in ensure) have `integrations.sweep_stale` bootstrapped by a
one-line addition beside 030's `ensure_sweep_job` call site in
`workers/job_runner.py` — a two-line, in-scope-by-necessity edit; record it
in the PR description. Deletion order in step 3 respects FKs (resources
and discovery runs cascade from connections; delete credentials last).

Register both kinds by importing
`services.integrations.discovery.handlers` from the 030 assembly point in
`services/jobs/handlers/__init__.py` (the package `registry.py` imports
for registration side effects; one import line).

**Verify**: kind-registration smoke prints both kinds;
`uv run python -m workers.job_runner --once` exits 0 with the sweep
enqueued+executed; `tests/services/jobs` untouched and green.

### Step 5: Notifications (`notify_connection_event.py`)

One op (decision 6) so wording/payload stay consistent —
`notify_connection_event(db, *, connection_id, event)` with
`event in {"needs_reauth", "discovery_failed"}`, calling
`create_notification` (`services/notifications/service.py:105`):
`notification_type=f"integration_{event}"`,
`recipient_user_id=connection.connected_by_user_id`,
`workspace_id=connection.owner_workspace_id` (None for user-owned),
`source="integrations"`, `payload={"connection_id": ..., "provider_key":
..., "label": ...}` (ids and display data — nothing secret). Wire the
`needs_reauth` case into `transition_connection_status` as an on-enter
hook: fires only when the previous status differs (once per transition,
not per failed refresh).

**Verify**: Step 7 pins exactly-once semantics for both events.

### Step 6: Selection + discovery routes

Service ops:

- `list_connection_resources.py` — resources for a connection (excluding
  soft-deleted; including `removed` rows flagged, so 042 can show "gone
  from provider"); read-scope + connection visibility per 038's list
  rules.
- `update_resource_selection.py` (decision 9) — validates ids (unknown /
  other-connection / `removed` id → `IntegrationValidationError`), applies
  the replace-set diff, audits UPDATE on `INTEGRATION_RESOURCE`
  (`{"enabled_added": [...], "enabled_removed": [...]}`), then
  `recompute_connection_status`.

Routes (route-per-file under `routes/integrations/`):

| File | Operation | Auth |
|------|-----------|------|
| `list_connection_resources.py` | `GET /integrations/connections/{connection_id}/resources` | `require_read` |
| `update_resource_selection.py` | `PUT /integrations/connections/{connection_id}/resources/selection` | `require_editor` + `require_connection_mutation_allowed` (decision 8, §1) |
| `trigger_discovery.py` | `POST /integrations/connections/{connection_id}/discover` | `require_editor` + ownership rule; 202 with the job id; in-flight dedup returns the existing job (decision 2) |

CSRF/rate-limit posture: all three are ordinary session-authenticated SPA
routes — CSRF enforced by default, no exemptions, no new rate limits
(discovery triggering is already dampened by the in-flight dedup).

**Verify**: route smoke shows the three new paths; RBAC tests green.

### Step 7: Tests

Extend `tests/factories/integrations.py` with
`create_integration_discovery_run(...)` and a helper to seed fake-provider
resources.

- `tests/services/integrations/test_run_discovery.py` (DB): happy path
  populates resources with counters; **idempotency** — second run changes
  nothing (`added=0`, same row ids, `last_seen_at` advanced); lifecycle —
  provider drops a resource → `removed`+`removed_at`, returns it later →
  resurrected `available` with `enabled` preserved; `writable`/
  `permissions_metadata` persisted from the provider payload; non-auth
  provider failure → run `failed`, connection `degraded`/`error`,
  **credential row untouched** (tokens still present) and a follow-up
  `run_discovery` succeeds without reconnecting (decision 5 pinned);
  auth failure → connection `needs_reauth`, no discovery-failed
  notification.
- `tests/services/integrations/test_recompute_status.py` (DB): the
  decision 4 table — zero enabled → `needs_resource_selection`; enabling
  one → `active`; disabling all → back to `needs_resource_selection`;
  non-discovery provider → `active` straight after connect; recompute
  never touches degraded/error/needs_reauth.
- `tests/services/integrations/test_discovery_handler.py` (DB; the 030
  `test_job_runner.py` fixture pattern): enqueue → `run_once` executes end
  to end against the fake provider; **enqueue dedup** — two enqueues for
  one connection yield one in-flight job; failure below `max_attempts` →
  retry, **no notification row**; final attempt → `failed` job, exactly
  ONE `integration_discovery_failed` notification to
  `connected_by_user_id`, and no generic `job_failed` notification (the
  no-initiator choice, decision 6); **the callback never discovers** —
  complete a fake OAuth connect and assert a pending job row exists while
  the fake provider's `discover_resources` call count is still 0
  (decision 1 pinned).
- `tests/services/integrations/test_needs_reauth_notification.py` (DB):
  transition into `needs_reauth` → one notification; a second failed
  refresh while already `needs_reauth` → no second notification;
  reconnect (→ `discovery_pending`) then failure again → a new one.
- `tests/services/integrations/test_sweep_stale.py` (DB): 91-day-old
  discovery runs deleted, 89-day-old kept; long-removed resources deleted,
  fresh `removed` kept; connection+credential revoked 31 d ago hard-deleted
  with audit rows surviving (FKs SET NULL), revoked 29 d kept; stale
  `auth_pending` expired; handler re-enqueues itself.
- `tests/routes/integrations/test_resource_routes.py` (DB): list includes
  `removed` flagged rows; selection replace-set applies + recomputes
  status + audits the diff; invalid/foreign/removed ids → 400; RBAC —
  read_only can list, cannot select (403); non-owner member cannot select
  on another user's user-scoped connection; trigger returns 202 and dedups.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/integrations tests/routes/integrations tests/services/jobs -q`
→ all pass; skips (not failures) without the env var; full suite green;
worker `--once` smoke exits 0.

## Test plan

Covered by Step 7 (~26–32 tests). The pinned invariants: **discovery never
runs in the request path** (callback enqueues, provider call count 0),
**handler idempotency under at-least-once delivery** (030 contract),
**failed discovery keeps the credential — retry without reconnect**,
**`needs_resource_selection`/`active` are computed from data by exactly one
function**, **each §6 notification fires exactly once** (per transition /
only after final retry, no double via 030's generic path), and **the 90 d /
30 d retention boundaries with audit survival** (§3).

## Done criteria

- [ ] `uv run ruff check .` exits 0; `uv run alembic check` clean (no new
      migration in this plan)
- [ ] `TEST_DATABASE_URL=... uv run pytest -q` exits 0 (full suite,
      including an untouched `tests/services/jobs`)
- [ ] Kind smoke prints exactly `['integrations.discover_resources',
      'integrations.sweep_stale']`
- [ ] `uv run python -m workers.job_runner --once` exits 0
- [ ] Grep shows `transition_connection_status` is still the only assigner
      of `IntegrationConnection.status`, and `recompute_connection_status`
      the only source of `needs_resource_selection`
- [ ] The 038 seam comments are gone, replaced by `enqueue_discovery`
      calls
- [ ] `docs/architecture/governance.md` updated: §3 rows "Credentials
      (037)" and "Integration resources/discovery runs (039)" →
      `[implemented: plan 039]`; §6 row "Integration needs_reauth /
      discovery failure" → `[implemented: plan 039]`; §1 row "Select
      integration resources / edit context groups (039–040)" → annotate
      `[implemented (selection): plan 039]` (context groups remain 040's)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- **Plan 030 is not implemented at execution time** (no `services/jobs/`
  with `enqueue_job` + `@job_handler`, or the worker doesn't run job
  handlers) — this plan hard-depends on the harness; do not build a
  bespoke queue or run discovery inline as a stopgap.
- 037 or 038 is not implemented, or their delivered contracts differ from
  the "Current state" assumptions (status vocabulary, resource uniqueness
  key, seam comments missing, `transition_connection_status` signature) —
  reconcile against those plan docs first.
- 030's kind-name rule, handler signature `(db, job)`, attempts-at-claim
  semantics, or notification-on-final-retry contract changed — decision 6's
  final-attempt check and decision 2's dedup depend on them exactly.
- There is no clean seam to bootstrap `ensure_integrations_sweep_job`
  without editing 030's claim/finalize internals — report rather than
  patching harness internals.
- Governance §3 retention values or the §6 recipient/table changed from the
  values cited here — the note wins.
- You feel the need to add a migration, implement Google Ads/Airtable API
  clients, resolve which resource a run should use, or build UI — that is
  037/041/040/042 scope leaking in.

## Maintenance notes

- **Consumers**: 040 (active context) reads `enabled` + `availability` +
  `writable` to build per-user-per-workspace selections and context groups
  across N connections (D3) — it must treat `unavailable`/`removed` as
  non-resolvable, and its compatibility filtering consumes
  `resource_type` against tool `provider_keys`/`resource_types`. 041
  replaces the google_ads/airtable dispatch arms in `run_discovery` with
  real clients (Google Ads MCC→account traversal populates
  `parent_external_id`; spend-capable accounts must set `writable` +
  `permissions_metadata` accurately because governance §2 makes spend
  mutations approval-locked with `supports_auto=False` — Gate G1). 042
  renders resource selection, discovery status/history from
  `integration_discovery_runs`, and the retry button on `degraded`/`error`
  connections.
- **Handler idempotency is a review gate** (030 maintenance note): any
  future change to `run_discovery` must keep the two-runs-identical
  property; the Step 7 idempotency test is the tripwire — do not weaken it
  to "counters may differ".
- **Selection survives churn deliberately**: `enabled` persists through
  `unavailable`/`removed` and resurrections so a provider blip doesn't
  silently drop an agent's access scope. If product later wants
  auto-disable of long-removed resources, do it in the sweep with a
  notification, not in the diff.
- **Notification volume**: today it is transition-edge + final-retry only.
  If 042 adds an activity feed, resist per-attempt notifications — the
  governance §6 table row ("every routine refresh — audit only") already
  rules on this.
- Reviewers should scrutinize: the final-attempt detection against 030's
  claim-increments-attempts semantics (off-by-one here double- or
  never-notifies), FK-safe deletion order in the sweep, the
  `on_enter(needs_reauth)` hook not firing on same-status no-ops, and that
  `enqueue_discovery` passes no `initiated_by_user_id` (decision 6's
  double-notification guard).

## Amendment (plan 074, 2026-07-07): periodic re-discovery

Where this block conflicts with the body above, this block wins.

**New decision 11.** One new self-rescheduling kind,
`integrations.rediscover_stale` (the `integrations.sweep_stale` pattern):
each pass calls `enqueue_discovery` for every non-deleted
`requires_discovery` connection in
`{active, needs_resource_selection, degraded}` whose newest **succeeded**
discovery run is older than `INTEGRATIONS_REDISCOVERY_INTERVAL_SECONDS`
(new decision-10 setting, default 86400). `needs_reauth`/`revoked`/
`auth_pending` are skipped (auth first); `error` stays manual-retry-only.
030's in-flight dedup prevents double-enqueue; the decision-3 diff makes
re-runs idempotent. Rationale: 040 gates write fan-out on
`writable`/`permissions_metadata` fail-closed and 041 derives those from
provider role checks — an upstream permission revoke must flip
`writable=false` without a human pressing re-discover. Notification
semantics unchanged: decision 6 applies as written (`needs_reauth` on
transition only; `discovery_failed` only after the final retry; no
`initiated_by_user_id` on the enqueue).

**Step deltas**: Step 1 adds the setting; Step 4 adds the handler beside
`sweep_stale.py`, bootstrapped at the same `ensure_integrations_sweep_job`
call site; the kind smoke (and its done criterion) becomes
`['integrations.discover_resources', 'integrations.rediscover_stale',
'integrations.sweep_stale']`. **Test-plan delta**
(`test_rediscover_stale.py`, DB): a connection with a `writable=true`
resource and a succeeded run aged past the interval, fake provider now
reporting `writable=false` → one sweep pass enqueues discovery (no
initiator) and the run flips the resource row to `writable=false` — the
value 040's `write_allowed` computation reads at resolution time (040
owns the gate-side test). Also pin: fresh-run connections not enqueued;
`needs_reauth`/`revoked` skipped; an in-flight discovery not duplicated.
