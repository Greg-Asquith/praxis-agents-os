# Plan 023: Audit & security log read API and viewer UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat f83d210..HEAD -- apps/api/models/audit_event.py apps/api/models/security.py apps/api/services/audit_events/ apps/api/services/security/ apps/api/core/dependencies.py apps/web/src/app/router.tsx`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (exposes sensitive operational data; authz mistakes here
  are cross-tenant leaks)
- **Depends on**: none (write/query services exist)
- **Category**: operational surfaces (roadmap `000_MASTER_ROADMAP.md` Lane O;
  **hard requirement of Gate G1**)
- **Planned at**: commit `f83d210`, 2026-07-02

## Decisions taken

Resolving `docs/legacy/ROADMAP_QUESTIONS_GAPS.md` §Audit And Security Logs:

1. **Audit events: workspace owner + admin.** Gated with the existing (and
   currently unused) `require_owner` route dependency
   (`core/dependencies.py:262`, built from `MANAGER_ROLES = {owner, admin}`).
   Workspace-scoped strictly: `workspace_id` is always taken from the
   request's workspace context, never from a query param.
2. **Security events: super-admin only.** `security_events` has **no
   `workspace_id`** — rows are global and carry other users' emails, IPs,
   and endpoints. Showing them to workspace admins would be a cross-tenant
   leak, so v1 uses the existing `require_super_admin` gate. Workspace admins
   still see workspace-relevant security happenings (membership/invitation
   events) through the audit stream, which duplicates them with workspace
   scoping.
3. **`AuthUser` gains `is_super_admin: bool`** (derived from the existing
   allowlist check) so the frontend can show/hide the Security tab honestly
   instead of probing for 403s.
4. **`details` render as read-only JSON.** No redaction layer in v1 — writers
   already control what goes into `details` (and `utils/json_safe.py`
   sanitizes on write). The 026 dispatch plan owns the input-digest question
   for tool events.
5. **Retention is NOT decided here** — plan 029 owns retention policy; this
   viewer reads whatever exists.

## Why this matters

Every sensitive mutation in the app already writes an audit row, and auth
infrastructure writes security events — but nothing reads them back except
SQL. Gate G1 says: no integration side-effect tools until operators can see
what agents and users did. This plan is the read half: list + filter + detail
for audit events per workspace, and a super-admin surface for global security
events. It also sets the pagination/filter idiom later list surfaces reuse.

## Current state

Backend — everything exists except routes/schemas:

- `apps/api/models/audit_event.py` — `audit_events`: `workspace_id`
  (nullable FK, indexed), `occurred_at`, `action(64)`, `resource_type(100)`,
  `resource_id(255)`, `status(32)`, `summary`, `actor_type/actor_id/
  actor_user_id/actor_display`, `requested_by_user_id`, `details` JSONB
  (GIN), `request_id`, `ip_address`, `user_agent`. Composite indexes on
  `(workspace_id, occurred_at)`, `(resource_type, resource_id, occurred_at)`,
  `(status, occurred_at)`, `(actor_user_id, occurred_at)`.
- `apps/api/services/audit_events/queries.py` — **the exact functions the
  routes need already exist**: `list_audit_events(db, *, workspace_id,
  resource_type, resource_id, actor_user_id, action, status, occurred_after,
  occurred_before, limit=50, offset=0)` (lines 47–75, newest-first),
  `count_audit_events` (78–103), `get_audit_event(db, *, event_id,
  workspace_id=None)` (106–117). Exported in `__init__.py:16-22`.
- Enums (`services/audit_events/enums.py`): `AuditAction`
  (create/read/update/delete/execute/enable/disable), `AuditResourceType`
  (user, user_auth, session, workspace, workspace_membership, invitation,
  notification, agent, agent_schedule, agent_schedule_run), `AuditActorType`,
  `AuditStatus` (success/failure/denied). Values in real use today: actions
  CREATE/UPDATE/DELETE/ENABLE/DISABLE/EXECUTE/READ; resource types
  WORKSPACE, USER_AUTH, NOTIFICATION, INVITATION, AGENT,
  WORKSPACE_MEMBERSHIP, AGENT_SCHEDULE, USER.
- `apps/api/models/security.py` — `security_events`: `event_type(100)`,
  `ip_address` INET, `endpoint`, `user_email`, `user_agent`, `details` JSONB,
  `request_id`, `occurred_at`. **No workspace column.** 27 event types in
  `services/security/enums.py:16-42`. Queries mirror audit:
  `list_security_events`/`count_security_events`/`get_security_event`
  (`services/security/queries.py:41-99`).
- Authz plumbing: `require_role` factory + prebuilt `require_owner`
  (owner+admin) at `core/dependencies.py:238-264` — **no route uses
  `require_owner` yet; this plan is its first consumer.**
  `require_super_admin` (222–235, email allowlist) is already used via
  `routes/users/dependencies.py:12` (`SuperAdminDep`).
- **No `routes/audit_events/` or `routes/security_events/` packages; no
  read schemas; no tests touch these services.**

Frontend:

- Conventions as in plan 022 "Current state" (feature folders, query-key
  factories, suspense queries, `router.tsx` registration, nav config,
  breadcrumbs).
- Role gating precedent is inline only:
  `workspace-settings-form.tsx:45-47` computes `canManage` from
  `useActiveWorkspace().workspace.current_user_role`. **No reusable
  permission hook exists.**
- JSON rendering precedent: `JsonBlock` in
  `features/conversations/components/tool-call-content-blocks.tsx:14`
  (props `{label, value}`; renders a scrollable `<pre>` via
  `safeJsonPreview`, not collapsible — it moved out of `tool-call-row.tsx`
  in commit `603fff7`). Check the repo's arch lint (`pnpm check`
  includes an `arch` rule) before importing across features; if cross-feature
  import is disallowed, lift `JsonBlock` into `src/components/ui/` as part
  of this plan rather than duplicating it.
- No pagination or filter-bar primitives exist; list pages pass fixed limits.
  Audit logs are the first surface that genuinely needs prev/next paging.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| API lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Migration sanity | `cd apps/api && uv run alembic check` | no new operations (no migration here) |
| API tests | `cd apps/api && uv run pytest tests/routes/audit_events tests/routes/security_events tests/contract -q` | all pass |
| Web lint/build | `cd apps/web && pnpm lint && pnpm build` | exit 0 |

## Scope

**In scope (create unless marked otherwise):**

- `apps/api/services/audit_events/schemas.py`
- `apps/api/services/audit_events/list_events.py`, `get_event.py` (service
  ops wrapping the existing queries + the count, producing the envelope)
- `apps/api/services/audit_events/__init__.py` (modify: re-export)
- `apps/api/services/security/schemas.py`, `list_events.py`, `get_event.py`,
  `__init__.py` (same shape)
- `apps/api/routes/audit_events/__init__.py`, `list_audit_events.py`,
  `get_audit_event.py`
- `apps/api/routes/security_events/__init__.py`, `list_security_events.py`,
  `get_security_event.py`
- `apps/api/routes/__init__.py` (modify: register both routers)
- `apps/api/services/auth/schemas.py` + `services/auth/utils.py` (modify:
  `is_super_admin` on `AuthUser`, decision 3)
- `apps/api/tests/routes/audit_events/…`, `tests/routes/security_events/…`,
  `tests/contract/test_openapi_routes.py` (modify)
- `apps/web/src/features/audit/` (`types.ts`, `api/`, `components/`,
  `routes/audit-route.tsx`)
- `apps/web/src/features/auth/types.ts` (modify: `is_super_admin`)
- `apps/web/src/app/router.tsx`, `src/config/navigation.ts`,
  `src/components/shell/app-breadcrumbs.tsx` (modify)
- `apps/web/src/components/ui/json-block.tsx` (create only if the arch rule
  forbids importing conversations' `JsonBlock` from
  `tool-call-content-blocks.tsx`)

**Out of scope (do NOT touch):**

- Audit/security **write** paths, enums, models, migrations — read-only plan.
- Retention, export, redaction (plan 029).
- `tool_name`/`tool_provider` audit columns (plan 026 adds them; the viewer
  renders `details` generically so 026 needs no viewer change).
- User-visible "my sessions/security" profile surface (distinct product
  question; note as follow-up).

## Git workflow

- Branch: `advisor/023-audit-security-log-viewer`
- Commit style: `API - Add Audit & Security Read Routes`,
  `Web - Add Audit Log Viewer`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Read schemas + service operations (audit)

`services/audit_events/schemas.py`: `AuditEventRead` exposing every model
column (`from_attributes` config + `from_event` classmethod; `details:
dict[str, Any]`), `AuditEventsListResponse{events, total, limit, offset}`.

`list_events.py`: `list_audit_events_for_workspace(db, *, workspace, limit,
offset, action=None, resource_type=None, resource_id=None,
actor_user_id=None, status=None, occurred_after=None, occurred_before=None)`
— delegates to the existing `list_audit_events` + `count_audit_events` with
`workspace_id=workspace.id` forced. Validate `action`/`status`/
`resource_type` against the enums (`AppValidationError` naming the field) so
filters fail loudly instead of silently returning everything… **check the
query builder first**: `_filtered_select` applies exact-match filters, so an
unknown value returns an empty page — still validate, an empty page for a
typo'd filter is a debugging trap.

Data caveat: some existing audit rows carry **raw-string `resource_type`
values not in `AuditResourceType`** — the schedule-run execution services
(`prepare_schedule_run_execution.py` / `finalize_schedule_run_execution.py`)
write `"conversation"` and `"agent_run"` (plus `"agent_schedule_run"`, which
IS in the enum). Unfiltered lists will include them; the table renders the
raw string fine, but the filter dropdown can't target them. Validate filter
*input* against the enum anyway — do not "fix" the writers here (read-only
plan).

`get_event.py`: wrap `get_audit_event(db, event_id=…,
workspace_id=workspace.id)`; `None` → `NotFoundError(resource_type=
"audit_event")`.

**Verify**: `uv run ruff check .` → exit 0.

### Step 2: Audit routes

`routes/audit_events/` with
`APIRouter(prefix="/audit-events", tags=["audit-events"],
dependencies=[Depends(require_owner)])` — gate the whole router (decision 1);
handlers still take `CurrentWorkspaceDep` for scoping.

- `GET /audit-events/` — query params: `limit` (ge=1, le=200, default 50 —
  smaller cap than other lists; rows are wide), `offset`, `action`,
  `resource_type`, `resource_id`, `actor_user_id: UUID | None`, `status`,
  `occurred_after: datetime | None`, `occurred_before: datetime | None`.
- `GET /audit-events/{event_id}` — `AuditEventRead`.

Register in `routes/__init__.py` (alphabetical: after `agents_router`,
before `auth_router`).

**Verify**: `uv run python -c "from main import app; print(sorted(r.path for r in app.routes if 'audit' in r.path))"`
→ the two paths.

### Step 3: Security routes + `is_super_admin`

Same shape under `routes/security_events/` (`prefix="/security-events"`),
gated with the existing super-admin dependency (reuse the pattern from
`routes/users/dependencies.py:12`; import the dependency rather than
re-deriving the allowlist check). Filters: `event_type` (validated against
`SecurityEventType`), `user_email`, `ip_address`, `endpoint`,
`occurred_after/before`, `limit/offset`. No workspace scoping — that is the
point of the super-admin gate.

`AuthUser.is_super_admin`: add the field to the schema
(`services/auth/schemas.py`) and populate it in `build_auth_user`
(`services/auth/utils.py:44`) using the same check `require_super_admin`
uses — extract that check into a small shared helper if it is currently
inlined in the dependency, rather than duplicating the allowlist read.

**Verify**: `uv run ruff check .` → exit 0.

### Step 4: Backend tests

`tests/routes/audit_events/test_audit_event_routes.py` (model on
`test_agent_routes.py` auth setup; seed events by calling
`safe_record_operation_audit_event` directly or via factories-inline):

- owner → 200 with envelope; admin → 200; member → 403; read_only → 403;
  unauthenticated → 401 (all problem+json)
- workspace scoping: events written for workspace B never appear for
  workspace A (this is the test that matters most — assert on a same-shaped
  event in both workspaces)
- filters: action, resource_type, status, actor_user_id, and a
  before/after window each narrow correctly; unknown action value → 400
- detail: happy path; cross-workspace event id → 404; system event with
  `workspace_id NULL` is NOT visible in any workspace list
- `tests/routes/security_events/test_security_event_routes.py`: non-super-admin
  owner → 403; super-admin (use the settings override support in
  `tests/support/settings.py` to allowlist the test user's email) → 200 +
  filters by `event_type`; `/auth/me` reflects `is_super_admin` true/false.

Extend `tests/contract/test_openapi_routes.py` with the four paths.

**Verify**: `uv run pytest tests/routes/audit_events tests/routes/security_events tests/contract tests/routes/auth -q` → all pass.

### Step 5: Frontend — feature, filters, drawer

- `features/audit/types.ts`: `AuditEvent`, `AuditEventsListResponse`,
  `SecurityEvent`, `SecurityEventsListResponse`, and string-union mirrors of
  the enum values (documented as mirrors of
  `services/audit_events/enums.py` — same maintenance note style as
  `runtime-tools.ts` used).
- `features/audit/api/`: `list-audit-events.ts` (workspace-scoped query keys;
  filters + `{limit, offset}` in the key so pages/filters cache separately;
  non-suspense `useQuery` with `placeholderData: keepPreviousData` for smooth
  paging), `get-audit-event.ts`, `list-security-events.ts` (enabled only when
  `is_super_admin`).
- `routes/audit-route.tsx` at path `/audit`: gate on
  `current_user_role === "owner" || === "admin"` (inline, per the
  settings-form precedent) rendering an `EmptyState` "You need admin access"
  otherwise; `Tabs`: **Audit log** and (only when
  `useCurrentUser().is_super_admin`) **Security events**.
- `components/audit-filter-bar.tsx`: selects for action / resource type /
  status (Title Case labels, "All" default), actor select fed by the existing
  workspace memberships query, two `datetime-local` inputs for the window,
  and a Reset button. Controlled state lifted to the route; every change
  resets `offset` to 0.
- `components/audit-events-table.tsx`: Occurred (formatDateTime), Action +
  status badge (`denied`/`failure` → destructive), Resource
  (`resource_type` + truncated `resource_id`), Actor (`actor_display`
  fallback `actor_type`), Summary (truncate). Row click opens
  `components/audit-event-detail.tsx` — a `Dialog` ("detail drawer") showing
  all fields + `details` via `JsonBlock` + request metadata
  (request_id/ip/user_agent). Prev/Next buttons from
  `total`/`limit`/`offset` ("Showing X–Y of Z"), disabled at bounds.
- Security tab mirrors the table with event_type/user_email/ip columns and
  its own filter subset.
- Nav item ("Audit log", shield icon) rendered only for owner/admin — pass
  the role into the nav filtering the way `disabled` items are handled in
  `primary-navigation.tsx`, or filter in the component; breadcrumb branch for
  `/audit`.

**Verify**: `pnpm lint` → exit 0 and `pnpm build` → exit 0.

## Test plan

Backend: Step 4 (~14–18 tests — authz matrix, scoping, filters, contract).
Frontend: lint + build + manual pass — as owner see audit rows for an agent
create/delete; filter by action; open detail dialog; page forward/back; as a
member confirm the nav item is absent and direct navigation shows the
not-authorized state; as non-super-admin confirm no Security tab.

## Done criteria

- [ ] `cd apps/api && uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no new operations
- [ ] `uv run pytest tests/routes/audit_events tests/routes/security_events tests/contract tests/routes/auth -q` exits 0
- [ ] `cd apps/web && pnpm lint && pnpm build` exits 0
- [ ] Workspace-scoping test (events from workspace B invisible in A) exists
      and passes
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `routes/audit_events/` or `routes/security_events/` already exists.
- The query functions' signatures differ from "Current state"
  (`services/audit_events/queries.py`, `services/security/queries.py`).
- `security_events` has gained a `workspace_id` column (decision 2's premise
  is gone — the gating decision needs revisiting, likely to owner/admin
  workspace-scoped).
- `require_owner` / `require_super_admin` are missing or renamed in
  `core/dependencies.py`.
- The arch lint blocks both importing AND lifting `JsonBlock` (conventions
  changed; ask before inventing a third pattern).

## Maintenance notes

- Plan 026 adds `tool_name`/`tool_provider` columns and per-invocation tool
  audit events. This viewer needs only additive work then: two filter fields
  and two table columns — its generic `details` rendering already covers the
  payloads. 026 should extend, not fork, `audit-filter-bar.tsx`.
- The enum mirrors in `features/audit/types.ts` must be updated whenever
  `AuditAction`/`AuditResourceType` gain members (016 adds SKILL; 026 adds
  tool types; 031+ add file types). Same discipline as the old
  `runtime-tools.ts` comment — until/unless a meta endpoint is justified.
- Follow-up (not planned): user-facing "my security activity" in profile
  settings, and audit export — both flagged in the gaps doc, both blocked on
  029 retention decisions.
- Reviewers should scrutinize: router-level `require_owner` actually applied
  (test the 403s), forced `workspace_id` scoping (no query-param override),
  and that security routes never leak to workspace admins.
