# Plan 016: Add the skills CRUD service and routes

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat ccb721b..HEAD -- apps/api/models/skills.py apps/api/services/agents/ apps/api/routes/ apps/api/services/audit_events/enums.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction (feature foundation)
- **Planned at**: commit `ccb721b`, 2026-07-01

## Why this matters

Skills are user-created instruction packages that agents activate on demand
(progressive disclosure). The `skills` DB table, its migration, and the
`agents.skill_ids` association already exist — but there is **no way to create,
read, update, or delete a skill**. Every later skill plan (document uploads in
plan 017, runtime disclosure in plan 018, the management UI in plan 019) sits on
top of this CRUD surface. This plan builds it exactly in the shape of the
existing agents CRUD so it is boring, predictable, and testable.

The naming and size rules below follow the open Agent Skills standard
(SKILL.md / agentskills.io, adopted industry-wide since late 2025): a skill's
`name` + `description` are **always** in the agent's context (level 1 of
progressive disclosure), so they are deliberately small; `instructions` load
only on activation (level 2).

## Current state

- `apps/api/models/skills.py` — the `Skill` model already exists: `name(64)`,
  `human_name(255)`, `description(Text, NOT NULL)`, `workspace_id` (FK,
  CASCADE), `created_by` (FK users), `instructions(Text, NOT NULL)`,
  `documentation_refs(JSONB, default {})`, `metadata_json` (column name
  `metadata`), `is_active`, `is_favorite`, `last_used_at`, plus `BaseModel`
  fields (`id`, `created_at`, `updated_at`, soft-delete `deleted/deleted_at/deleted_by`).
  Unique constraint `uq_skills_workspace_name` on `(workspace_id, name)`.
- The table is created in `apps/api/alembic/versions/core/0001_create_core_schema.py`
  (lines 383–409). **No migration is needed in this plan.**
- `apps/api/services/agents/utils.py:63-93` — `validate_agent_references`
  already validates `skill_ids` on agent create/update via
  `_ensure_active_skills_exist` (utils.py:211-233): skills must exist, be
  active, be non-deleted, and belong to the workspace. Do not change this.
- There is **no** `services/skills/` package and **no** `routes/skills/` package.
- `apps/api/services/audit_events/enums.py:25-37` — `AuditResourceType` has no
  `SKILL` member yet:

  ```python
  class AuditResourceType(StrEnum):
      """The kind of resource an event concerns."""

      USER = "user"
      ...
      AGENT = "agent"
      AGENT_SCHEDULE = "agent_schedule"
      AGENT_SCHEDULE_RUN = "agent_schedule_run"
  ```

  Members are plain strings persisted as-is; adding one requires no migration.
- `apps/api/routes/__init__.py:17-25` — routers are registered alphabetically
  on `api_router`:

  ```python
  api_router = APIRouter(prefix=settings.API_V1_PREFIX)
  api_router.include_router(agent_runs_router)
  api_router.include_router(agents_router)
  api_router.include_router(auth_router)
  api_router.include_router(conversations_router)
  api_router.include_router(models_router)
  api_router.include_router(schedules_router)  # added by 021 (9208c47)
  api_router.include_router(storage_router)
  ...
  ```

### Conventions to copy exactly

- **Route package shape** — one operation per file, `__init__.py` only composes.
  `apps/api/routes/agents/__init__.py`:

  ```python
  router = APIRouter(prefix="/agents", tags=["agents"])
  router.include_router(list_agents_router)
  router.include_router(create_agent_router)
  router.include_router(get_agent_router)
  router.include_router(update_agent_router)
  router.include_router(delete_agent_router)
  ```

- **Route handler shape** — `apps/api/routes/agents/create_agent.py`:

  ```python
  @router.post("/", status_code=status.HTTP_201_CREATED)
  async def create_agent(
      request: Request,
      db: AsyncDbSessionDep,
      actor: CurrentUserDep,
      workspace_context: CurrentWorkspaceDep,
      payload: AgentCreateRequest,
  ) -> AgentRead:
      workspace, membership = workspace_context
      return await create_agent_service(
          db, request=request, actor=actor, workspace=workspace,
          membership=membership, payload=payload,
      )
  ```

  Dependencies come from `core/dependencies.py` (`AsyncDbSessionDep`,
  `CurrentUserDep`, `CurrentWorkspaceDep`).
- **Service package shape** — one operation per file
  (`services/agents/create_agent.py`, `list_agents.py`, `get_agent.py`,
  `update_agent.py`, `delete_agent.py`), Pydantic contracts in `schemas.py`,
  helpers in `utils.py`, `__init__.py` only re-exports. `AsyncSession` is the
  first positional arg named `db`; everything else keyword-only after `*`.
- **Schema shape** — `apps/api/services/agents/schemas.py`: read models use
  `ConfigDict(from_attributes=True, populate_by_name=True)` + a
  `from_agent(...)` classmethod; `metadata_json` is exposed as `metadata` via
  `Field(serialization_alias="metadata")` on reads and `Field(alias="metadata")`
  on requests. List responses are `{<items>, total, limit, offset}`.
- **Update semantics** — `services/agents/update_agent.py` distinguishes
  "field omitted" from "field sent as null" via `payload.model_fields_set`
  (see its `skill_ids` handling at lines 104-128). Match that pattern.
- **Audit** — from `services/agents/create_agent.py`:

  ```python
  await record_workspace_audit_event(
      db, request=request, workspace_id=workspace.id,
      action=AuditAction.CREATE, resource_type=AuditResourceType.AGENT,
      resource_id=agent.id, actor=actor, details={...})
  ```

- **Errors** — raise types from `core/exceptions/general.py`
  (`AppValidationError(field=...)`, `NotFoundError(resource_type=, resource_id=)`,
  `ConflictError(conflicting_resource=)`); they render as RFC 7807 problem+json
  via `core/exceptions/exception_handlers.py`.
- **Write access** — model on `require_agent_write_access` in
  `services/agents/utils.py` (read the function; reuse the same role logic for
  a `require_skill_write_access`).

## Commands you will need

| Purpose   | Command (run from `apps/api`)          | Expected on success |
|-----------|----------------------------------------|---------------------|
| Install   | `uv sync`                              | exit 0              |
| Lint      | `uv run ruff check .`                  | exit 0, no errors   |
| Migration sanity | `uv run alembic check`          | "No new upgrade operations detected" |
| Tests     | `uv run pytest tests/routes/skills tests/services/skills -q` | all pass |
| Full skills-adjacent tests | `uv run pytest tests/routes/agents tests/services/agents -q` | all pass (no regression) |

## Scope

**In scope** (the only files you should create/modify):

- `apps/api/services/skills/__init__.py` (create)
- `apps/api/services/skills/schemas.py` (create)
- `apps/api/services/skills/utils.py` (create)
- `apps/api/services/skills/create_skill.py`, `list_skills.py`, `get_skill.py`,
  `update_skill.py`, `delete_skill.py` (create)
- `apps/api/routes/skills/__init__.py`, `create_skill.py`, `list_skills.py`,
  `get_skill.py`, `update_skill.py`, `delete_skill.py` (create)
- `apps/api/routes/__init__.py` (register the router)
- `apps/api/services/audit_events/enums.py` (add `SKILL = "skill"`)
- `apps/api/tests/factories/skills.py` (create)
- `apps/api/tests/routes/skills/test_skill_routes.py` (create)
- `apps/api/tests/services/skills/test_skill_schemas.py` (create)

**Out of scope** (do NOT touch):

- `apps/api/models/skills.py` — the model is correct as-is; no schema change.
- `apps/api/alembic/` — no migration is needed.
- `documentation_refs` handling beyond exposing it read-only — uploads and
  manifest mutation are plan 017.
- `services/agents/*` — agent-side validation of `skill_ids` already exists.
- Any runtime consumption of skills — plan 018.
- The frontend — plan 019.

## Git workflow

- Branch: `advisor/016-skills-backend-crud`
- Commit style matches the repo (`git log --oneline`): `API - Add Skills CRUD Routes`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the `SKILL` audit resource type

In `apps/api/services/audit_events/enums.py`, add to `AuditResourceType`
(after `AGENT_SCHEDULE_RUN`):

```python
SKILL = "skill"
```

**Verify**: `uv run ruff check .` → exit 0.

### Step 2: Create `services/skills/schemas.py`

Define, following `services/agents/schemas.py` idioms:

- `SKILL_NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"` — lowercase kebab-case,
  per the open Agent Skills standard. Validate with a `field_validator` that
  strips, lowercases nothing (reject uppercase rather than coercing), and
  raises `ValueError` with a message naming the allowed pattern.
- `SkillRead`: `id`, `name`, `human_name`, `description`, `instructions`,
  `workspace_id`, `created_by`, `documentation_refs: dict[str, Any]`
  (default `{}` — read-only surface of the plan-017 manifest), `is_active`,
  `is_favorite`, `last_used_at`, `metadata_json` aliased to `metadata`,
  `created_at`, `updated_at`, `deleted`, `deleted_at`. `from_attributes`
  config + `from_skill` classmethod.
- `SkillsListResponse`: `skills: list[SkillRead]`, `total`, `limit`, `offset`.
- `SkillCreateRequest`:
  - `name: str` — min 1, max 64, must match `SKILL_NAME_PATTERN`.
  - `human_name: str | None` — max 255, blank→None normalization.
  - `description: str` — min 1, **max 1024** (level-1 metadata: always in the
    agent prompt, so keep it budgeted).
  - `instructions: str` — min 1, **max 20000** (matches the agent
    `instructions` cap).
  - `is_active: bool = True`, `is_favorite: bool = False`.
  - `metadata_json: dict[str, Any] | None = Field(default=None, alias="metadata")`.
  - Do **not** accept `documentation_refs` — the manifest is owned by plan 017.
- `SkillUpdateRequest`: same fields, all optional/None defaults, same
  validators applied only when the value is present (copy the
  `normalize_required_when_present` pattern from `AgentUpdateRequest`).

**Verify**: `uv run ruff check .` → exit 0.

### Step 3: Create `services/skills/utils.py`

- `get_skill_for_workspace(db, *, workspace, skill_id) -> Skill` — select where
  `Skill.id == skill_id`, `Skill.workspace_id == workspace.id`,
  `Skill.deleted == False`; raise
  `NotFoundError("Skill not found", resource_type="skill", resource_id=str(skill_id))`
  when missing. Model on `get_agent_for_workspace` in `services/agents/utils.py`.
- `require_skill_write_access(membership)` — same role check as
  `require_agent_write_access` (read it first and reuse its role sets from
  `services/workspaces/utils.py`).
- `classify_skill_integrity_error(exc)` (or equivalent) — map an
  `IntegrityError` on `uq_skills_workspace_name` to
  `ConflictError("A skill with this name already exists in the workspace", conflicting_resource="skill")`.
  Model on the agents' integrity-classification helper in
  `services/agents/utils.py` (find its slug/name-conflict handling and mirror it).

**Verify**: `uv run ruff check .` → exit 0.

### Step 4: Create the five service operations

Each in its own file, `db` first positional then keyword-only args, mirroring
the corresponding `services/agents/<op>.py`:

- `create_skill.py` — `create_skill(db, *, request, actor, workspace, membership, payload) -> SkillRead`.
  Require write access; insert; flush inside a try/except that routes
  `IntegrityError` through the step-3 classifier; audit
  `AuditAction.CREATE` / `AuditResourceType.SKILL` with
  `details={"skill_name": skill.name}`; return `SkillRead.from_skill(skill)`.
- `list_skills.py` — `list_skills(db, *, workspace, limit, offset, include_inactive) -> SkillsListResponse`.
  Filter `workspace_id`, `deleted == False`, and `is_active` unless
  `include_inactive`; `func.count()` for total; order by `created_at` desc
  (uses index `ix_skills_workspace_created`).
- `get_skill.py` — fetch via `get_skill_for_workspace`, return `SkillRead`.
- `update_skill.py` — partial update honoring `payload.model_fields_set`
  (copy the `update_agent.py` pattern including `changed_fields` tracking);
  audit `UPDATE` with `details={"changed_fields": changed_fields}`; rejecting
  `name`/`description`/`instructions` explicitly set to null with
  `AppValidationError`.
- `delete_skill.py` — soft delete (`deleted = True`, `deleted_at = now`,
  `deleted_by = actor.id` — match however `delete_agent.py` does it exactly);
  audit `DELETE`. Deleting a skill still referenced by an agent's `skill_ids`
  is allowed; the runtime (plan 018) skips dangling references defensively.

`__init__.py` re-exports the five callables only.

**Verify**: `uv run ruff check .` → exit 0.

### Step 5: Create the route package and register it

`routes/skills/` mirrors `routes/agents/` exactly:

- `POST /skills/` → 201, `SkillRead` (create)
- `GET /skills/` → `SkillsListResponse`, query params
  `limit: Annotated[int, Query(ge=1, le=500)] = 100`,
  `offset: Annotated[int, Query(ge=0)] = 0`, `include_inactive: bool = False`
  (copy `routes/agents/list_agents.py`)
- `GET /skills/{skill_id}` → `SkillRead`
- `PATCH or PUT /skills/{skill_id}` → match whichever verb
  `routes/agents/update_agent.py` uses — check it and copy
- `DELETE /skills/{skill_id}` → match the agents delete route's status code

`routes/skills/__init__.py` composes with
`APIRouter(prefix="/skills", tags=["skills"])`. In `routes/__init__.py`, import
and include `skills_router` keeping alphabetical order (between
`schedules_router` and `storage_router` — `schedules_router` landed with
plan 021).

**Verify**: `uv run ruff check .` → exit 0, and
`uv run python -c "from main import app; print([r.path for r in app.routes if 'skills' in r.path])"`
→ prints the five `/api/v1/skills...` paths.

### Step 6: Tests

- `tests/factories/skills.py` — `build_skill(*, workspace, created_by, **overrides) -> Skill`
  returning an **unsaved** instance with sensible defaults
  (`name=f"skill-{uuid4().hex[:8]}"`, `description=...`, `instructions=...`),
  matching the hand-written builder style of `tests/factories/workspaces.py`.
- `tests/routes/skills/test_skill_routes.py` — model the auth setup on
  `tests/routes/agents/test_agent_routes.py` (its `_authenticated_workspace`
  helper + `bearer_headers` from `tests/support/auth.py`). Cover:
  - create → 201, response echoes fields, audit row written
    (query the audit model the way the agents route tests do, if they do)
  - create duplicate name in same workspace → 409
  - create with invalid name (`"Bad Name"`, `"-leading"`, 65 chars) → 422
  - list excludes soft-deleted and (by default) inactive skills
  - get/update/delete happy paths; get from another workspace → 404
  - update with `"name": null` → 400
  - unauthenticated request → 401
- `tests/services/skills/test_skill_schemas.py` — pure schema tests: name
  pattern acceptance/rejection table, description length cap, metadata alias
  round-trip. Model on `tests/services/agents/test_agent_schemas.py`.

**Verify**: `uv run pytest tests/routes/skills tests/services/skills -q` → all
pass. Then `uv run pytest tests/routes/agents tests/services/agents -q` → all
pass (no regression).

## Test plan

Covered by Step 6. New tests: ~12–16 route/service/schema tests as listed. Use
existing tests as structural patterns; do not invent new fixtures when
`tests/conftest.py` + factories suffice.

## Done criteria

Machine-checkable. ALL must hold (run from `apps/api`):

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no new operations (no schema drift)
- [ ] `uv run pytest tests/routes/skills tests/services/skills -q` exits 0
- [ ] `uv run pytest tests/routes/agents tests/services/agents -q` exits 0
- [ ] `grep -rn "SKILL = \"skill\"" services/audit_events/enums.py` returns one match
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `services/skills/` or `routes/skills/` already exists (someone got here first).
- The `Skill` model fields differ from the "Current state" description
  (e.g. `documentation_refs` renamed or removed).
- `uv run alembic check` reports pending operations before you make any change
  (pre-existing drift is not yours to fix).
- The agents route tests fail **before** your changes (baseline is broken).
- You find an existing skills validation rule elsewhere that conflicts with
  `SKILL_NAME_PATTERN` (e.g. seeded data with uppercase names).

## Maintenance notes

- Plan 017 adds document upload/conversion routes under
  `/skills/{skill_id}/documents` and owns all writes to `documentation_refs`.
  Keep `SkillCreateRequest`/`SkillUpdateRequest` free of that field.
- Plan 018 consumes `name`, `description`, `instructions` at runtime; the
  1024-char description cap is a prompt-budget decision — if it is ever raised,
  reconsider the level-1 catalog cost per skill.
- Reviewers should scrutinize: workspace scoping on every query (no cross-
  workspace reads), audit rows on all three mutations, and the 409 path.
- Deferred: skill import/export as SKILL.md-compatible bundles (noted in the
  plans README as a possible follow-up).
