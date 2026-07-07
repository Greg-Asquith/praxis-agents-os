<!-- docs/plans/complete/065-api-service-scaffolding-consolidation.md -->

# Plan 065: Consolidate the API's duplicated pagination, asset-lifecycle, and notifications scaffolding

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat d326b68..HEAD -- apps/api/services apps/api/utils`
> If the pagination-owning list services, `services/assets/`, or
> `services/notifications/service.py` changed since this plan was written,
> compare the "Current state" excerpts against the live code before
> proceeding; on a mismatch, treat it as a STOP condition. Note: the working
> tree at planning time had uncommitted changes under
> `services/workspaces/invitations/` and `services/auth/` — re-read those
> files rather than trusting excerpts if they appear in your diff.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW–MED (response shapes must stay byte-identical; covered by existing route tests)
- **Depends on**: 062 (soft — for `make api-test`; env var works too)
- **Category**: tech-debt
- **Planned at**: commit `d326b68`, 2026-07-07
- **Completed at**: 2026-07-07

## Why this matters

Three backend patterns were copy-pasted per feature and are drifting:

1. **Pagination**: the `total`/`limit`/`offset` envelope is hand-redeclared in
   8 schema files and the count-query recipe
   (`select(func.count()).select_from(stmt.subquery())` + windowed re-query)
   is hand-rolled in every offset-style list service — while three different
   pagination contracts now coexist (offset envelope, total-only in files,
   split count function in audit, cursor-based in conversation messages).
2. **Assets**: the avatar and workspace-icon lifecycles are six files in three
   ~90%-identical pairs (create/confirm/delete × user-avatar/workspace-icon);
   a change to the upload token protocol must land twice, and a third public
   asset type means a fourth copy-paste.
3. **Notifications**: `services/notifications/service.py` (451 lines, 13
   functions) is the only service package violating the repo's documented
   one-operation-per-file convention.

Consolidating these gives every future list endpoint, asset type, and
notification operation one obvious home, and makes count/window bugs fixable
in one place.

## Current state

- Repo conventions (AGENTS.md): one service operation per file; service
  package `__init__.py` re-exports only; service-specific helpers in that
  service's `utils.py`; cross-service reusable helpers in top-level
  `apps/api/utils/`; typed exceptions from `core/exceptions`; async
  throughout; ruff config in `apps/api/ruff.toml`.
- The hand-rolled pagination recipe — exemplar
  `services/users/list_users.py:20-34`:

  ```python
  stmt = select(User)
  ...
  total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
  result = await db.execute(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset))
  return UsersListResponse(
      users=[UserRead.from_user(user) for user in result.scalars().all()],
      total=total or 0,
      limit=limit,
      offset=offset,
  )
  ```

  The same recipe appears in `services/workspaces/list_workspaces.py`,
  `services/workspaces/memberships/list_memberships.py`,
  `services/workspaces/invitations/list_invitations.py`, and similar list
  operations in agents/schedules/security/skills.
- The envelope triplet `total: int` / `limit: int` / `offset: int` is declared
  in: `services/{audit_events,agent_schedules,security,agents,workspaces,conversations,users,skills}/schemas.py`
  (8 files, verified by grep). Divergent contracts to leave alone:
  `services/files/list_files.py` returns `total` only;
  `services/conversations/list_messages.py` is cursor-based
  (`before_sequence` + `has_more`) — deliberate second pattern;
  `services/audit_events/queries.py` has a separate `count_audit_events`.
- The asset twin files — `services/assets/create_user_avatar_upload.py` and
  `create_workspace_icon_upload.py` differ only in: authz
  (`require_workspace_role` for icons, none for own avatar), size setting
  (`MAX_FILE_SIZE_AVATAR` vs `MAX_FILE_SIZE_ICON`), allowed content types
  (`allowed_avatar_content_types()` vs
  `allowed_workspace_icon_content_types()`), ref path
  (`users/{actor.id}/avatar` vs `workspaces/{workspace_id}/icon`), and
  `AssetKind` (`USER_AVATAR` vs `WORKSPACE_ICON`). The shared flow, from
  `create_user_avatar_upload.py:24-53`:

  ```python
  content_type = validate_upload_metadata(...)
  ref = public_asset_ref(f"users/{actor.id}/avatar", content_type=content_type)
  provider = get_storage_provider()
  upload = await provider.create_signed_upload(ref, content_type=content_type, expires_in=timedelta(minutes=10))
  upload_token, expires_at = create_asset_upload_token(kind=AssetKind.USER_AVATAR, ...)
  return AssetUploadGrant(upload=upload, upload_token=upload_token, max_size_bytes=max_size_bytes, expires_at=expires_at)
  ```

  The same twinning holds for `confirm_user_avatar_upload.py` /
  `confirm_workspace_icon_upload.py` and `delete_user_avatar.py` /
  `delete_workspace_icon.py`. Supporting modules: `services/assets/domain.py`
  (AssetKind, AssetUploadGrant, AssetUploadRequest), `tokens.py`, `utils.py`.
- `services/notifications/service.py` — 13 functions in one module:
  private helpers `_authorize_and_claim_user_notification` (:28),
  `_authorize_active_workspace` (:56), `_validate_actions` (:70),
  `_get_notification_or_raise` (:88); public ops `create_notification` (:103),
  `list_notifications` (:159), `count_unread` (:195),
  `mark_read_for_workspace` (:216), `mark_unread_for_workspace` (:250),
  `set_archived_for_workspace` (:282), `mark_all_read` (:316),
  `perform_action_for_workspace` (:343), `claim_unassigned_for_email` (:404),
  `mark_invitation_notifications_actioned` (:419). Layout exemplar to match:
  `services/users/` (one file per op, `__init__.py` re-exports,
  service-local `utils.py`). Notifications currently has no public routes —
  callers are other services and the worker; find them with
  `grep -rn "from services.notifications" apps/api --include="*.py"`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint + format | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Full API tests | `cd apps/api && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run pytest` | exit 0 |
| Focused suites | `... uv run pytest tests/services/workspaces tests/routes tests/services/assets -q` | exit 0 |
| OpenAPI unchanged | `cd apps/api && uv run pytest tests/contract -q` | exit 0 |

(Start Postgres first: `make db-up && make db-wait`; after plan 062,
`make api-test` provisions the test DB.)

## Scope

**In scope**:

- `apps/api/utils/pagination.py` (create)
- The 8 offset-style list service files and their `schemas.py` envelope
  declarations (enumerate with
  `grep -rln "select_from(.*subquery" apps/api/services` plus
  `grep -rln "total: int" apps/api/services --include="schemas.py"`)
- `apps/api/services/assets/` (all files)
- `apps/api/services/notifications/` (restructure)
- Import-site updates for moved notification functions
- Test files that import moved symbols (import updates only)

**Out of scope** (do NOT touch):

- `services/conversations/list_messages.py` — the cursor contract is a
  deliberate second pattern; do not migrate it.
- `services/files/list_files.py` response shape — adding `limit`/`offset` to
  its response would be an API change; leave it (recorded follow-up).
- Response schema **shapes**: no field added, removed, renamed, or re-typed
  anywhere. The consolidation is internal.
- `services/storage/providers/*` — the provider error-wrap consolidation was
  considered and deferred (MED risk, four SDK exception surfaces); only a
  future plan may take it.
- Route files, models, migrations.

## Git workflow

- Work on `main` unless told otherwise; commit per step; style:
  `API - Service Scaffolding Consolidation`.
- Do NOT push unless instructed.

## Steps

### Step 1: `paginate()` helper + envelope mixin

Create `apps/api/utils/pagination.py`:

```python
# apps/api/utils/pagination.py

"""Shared offset pagination for list services."""

from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class OffsetPage(BaseModel):
    """Envelope fields shared by offset-paginated list responses."""

    total: int
    limit: int
    offset: int


async def paginate(
    db: AsyncSession,
    stmt: Select[Any],
    *,
    order_by: Any,
    limit: int,
    offset: int,
) -> tuple[list[Any], int]:
    """Run the count + windowed query for one offset-paginated list."""
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(order_by).limit(limit).offset(offset))
    return list(result.scalars().all()), total or 0
```

Match the exact typing style of nearby code (check `utils/security.py` for
module conventions). If a list service orders by multiple columns, accept
`*order_by` variadic instead — inspect all 8 call sites first and pick the
signature that fits every one without behavior change.

**Verify**: `uv run ruff check .` exits 0.

### Step 2: Migrate the offset-style list services

For each of the 8 services found by the greps in Scope:

- Replace the hand-rolled count+window with `paginate(...)`.
- Change the response schema to inherit the envelope:
  `class UsersListResponse(OffsetPage): users: list[UserRead]` — field names,
  types, and optionality identical to before (Pydantic field order in the
  OpenAPI schema may shift; that is acceptable — names/types are the
  contract).
- Do NOT migrate audit's split `count_audit_events` if its count query filters
  differ from its list query (read it first); if they are equivalent, migrate
  it too, otherwise leave it and note that in your report.

**Verify** after each service:
`TEST_DATABASE_URL=... uv run pytest tests/services/<service> tests/routes/<service> -q` → green.
After all: `uv run pytest tests/contract -q` → green (route paths unchanged).
Then `grep -rn "select_from(.*subquery" apps/api/services --include="*.py"` →
no matches outside `utils/pagination.py` (or only the deliberately-skipped
audit count function).

### Step 3: Parameterize the asset lifecycle

In `services/assets/domain.py`, add a spec:

```python
@dataclass(frozen=True)
class AssetSpec:
    kind: AssetKind
    asset_label: str            # "avatar" / "workspace icon"
    max_size_setting: str       # settings attr name, e.g. "MAX_FILE_SIZE_AVATAR"
    allowed_content_types: Callable[[], frozenset[str]]
    ref_template: str           # "users/{owner_id}/avatar" / "workspaces/{owner_id}/icon"
```

Add generic operations (either in `services/assets/utils.py` or new
`_lifecycle.py` — pick `utils.py` to match the helper convention):
`create_asset_upload(spec, *, actor, owner_id, payload)`,
`confirm_asset_upload(spec, ...)`, `delete_asset(spec, ...)` — each the body
of today's twin files with the five varying values read from the spec.
**Authorization stays in the six thin operation files** (the workspace-icon
ops call `require_workspace_role` before delegating; the avatar ops don't) —
do not move authz into the generic layer, and do not change any public
function signature the routes import. Read `confirm_*` and `delete_*` pairs
fully before extracting; if the pairs have diverged beyond the five spec
values, STOP (see conditions).

**Verify**: `TEST_DATABASE_URL=... uv run pytest tests/services/assets tests/routes -q`
→ green; the six operation files are each ≤ ~30 lines
(`wc -l apps/api/services/assets/{create,confirm,delete}_*.py`).

### Step 4: Split notifications into one-op-per-file

Convert `services/notifications/service.py` into the standard layout:

- One file per public function (`create_notification.py`,
  `list_notifications.py`, `count_unread.py`, `mark_read_for_workspace.py`,
  `mark_unread_for_workspace.py`, `set_archived_for_workspace.py`,
  `mark_all_read.py`, `perform_action_for_workspace.py`,
  `claim_unassigned_for_email.py`, `mark_invitation_notifications_actioned.py`).
- The four private helpers move to `services/notifications/utils.py`.
- `__init__.py` re-exports every public function (match
  `services/users/__init__.py` style).
- Update all importers (`grep -rn "from services.notifications" apps/api`).
- Pure mechanical move: zero body changes; keep each function's docstring.
- Delete `service.py` at the end.

**Verify**: `uv run ruff check .` exits 0;
`TEST_DATABASE_URL=... uv run pytest tests/ -q -k notification` → green;
`grep -rn "notifications.service" apps/api --include="*.py"` → no matches;
full `uv run pytest` → green.

## Test plan

- Existing suites are the net: services/routes/contract tests for
  users, workspaces, agents, schedules, security, skills, assets,
  notifications must stay green with zero assertion edits (import-path edits
  allowed).
- New: `apps/api/tests/services/test_pagination.py` — `paginate()` against a
  seeded table (use an existing factory model, e.g. users): total counts
  filtered rows not the window, window respects limit/offset, empty result
  returns `([], 0)`. DB-backed; use `tests/support/database.py` +
  `tests/factories/users.py`, model the module after an existing
  `tests/services/` file.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `cd apps/api && uv run ruff check . && uv run ruff format --check .` exit 0
- [ ] Full `TEST_DATABASE_URL=... uv run pytest` exits 0
- [ ] `grep -rn "select_from(.*subquery" apps/api/services --include="*.py"` returns no list-service matches (documented audit exception allowed)
- [ ] `services/notifications/service.py` no longer exists; one file per public op
- [ ] `wc -l` on the six asset op files ≤ ~30 lines each
- [ ] No response schema field name/type changed (`uv run pytest tests/contract -q` green; spot-check one list route's JSON in a route test)
- [ ] Status row updated in `docs/plans/000_README.md`

## STOP conditions

Stop and report back (do not improvise) if:

- Any list service's count query intentionally differs from its list query
  (different filters) — `paginate()` would change behavior there.
- The asset confirm/delete pairs differ in more than the five spec-captured
  values (they were audited at the create pair in detail; verify the others).
- A notifications function is imported by name from `services.notifications.service`
  in a migration or worker in a way the re-export doesn't cover.
- The uncommitted workspace/auth changes in the working tree collide with the
  invitations list service migration.
- Any route/contract test fails for reasons other than an import path you
  just moved.

## Maintenance notes

- New list endpoints must use `paginate()` + `OffsetPage`; the cursor-based
  conversation-messages contract stays the documented exception for
  chat-history reads.
- A third public asset type (e.g. agent avatars) should be one new `AssetSpec`
  plus thin op files — reviewers should reject a fourth copy-paste.
- Deferred follow-ups recorded in `docs/plans/000_README.md`: storage-provider
  error-wrap base (four largest files still share a lockstep template),
  `services/agents/utils.py` junk-drawer regroup, `files` list envelope
  alignment.
- Do not reference this plan number from implementation code or docstrings
  (AGENTS.md rule).
