# Plan 021: Add the schedule REST routes

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat f83d210..HEAD -- apps/api/models/agent.py apps/api/services/agent_schedules/ apps/api/routes/ apps/api/workers/agent_runner.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (scheduling is a high-risk area per AGENTS.md; the worker
  and claim loop are live and must not change behavior)
- **Depends on**: none (worker landed in plans 001/005)
- **Category**: operational surfaces (roadmap `000_MASTER_ROADMAP.md` Lane O;
  Gate G1 input)
- **Planned at**: commit `f83d210`, 2026-07-02

## Decisions taken

Resolving the `docs/legacy/ROADMAP_QUESTIONS_GAPS.md` §Schedules questions
that bind here:

1. **Who can do what**: any non-read-only member creates schedules; the
   schedule's owner or a workspace admin/owner mutates them; every workspace
   member can read them. This is exactly what the existing (currently unused)
   `services/agent_schedules/authorisation.py` helpers implement — routes
   adopt them, not new rules.
2. **Run-now = `next_run_at = now()`** on an active schedule, audited as
   `EXECUTE`. The worker's claim loop picks it up within one poll interval
   with zero worker changes. Run-now on a paused schedule is a 409. Side
   effect to document in the response: after the manual run completes,
   `mark_run_completed` recomputes the next fire from *now* (shifts interval
   phase; runs a `once` schedule early and retires it).
3. **Enable recomputes `next_run_at` from now** — re-enabling a schedule paused
   for a week must not backfill missed fires.
4. **Failure policy is the existing one** (bounded retries, then terminal
   failure + auto-disable). Routes surface it via the existing
   `schedule_health_from_run` values; they do not add retry knobs.
5. **Approval decisions stay on agent-run endpoints.** Schedule surfaces
   expose `agent_run_id` for awaiting-approval runs; the UI (plan 022) links
   to the existing `GET /agent-runs/{id}/approval-state` +
   `POST /agent-runs/{id}/resume`. Known limitation to record in the API docs:
   those endpoints enforce `AgentRun.user_id == actor.id`
   (`services/agent_runs/get_approval_state.py:37-44`), so only the schedule
   owner can act on its approvals today. Widening that is a deliberate
   follow-up, not a side effect of this plan.
6. **`active_context` stays untouched** — the column exists and plan 040 fills
   it. Create/update requests must not accept it yet.

## Why this matters

The scheduler is a complete backend (models, claim loop with SKIP LOCKED,
prepare/finalize/reconcile, approval mirroring, worker) with **no public
surface at all** — no routes, no schemas file, nothing for the frontend to
call. The service layer even ships route-ready helpers that nothing consumes.
Gate G1 requires schedules to be operator-visible before integration tools
ship side effects. This plan is pure surface: routes + schemas + audit rows
over existing services, changing no scheduling behavior.

## Current state

- Models (`apps/api/models/agent.py`): `AgentSchedule` (lines 104–165) —
  `agent_id`/`user_id`/`workspace_id`, `schedule_type` CHECK
  `('cron','interval','once')`, `cron_expression`, `interval_minutes`,
  `run_once_at`, `timezone(64)` default `'UTC'`, `default_prompt`,
  `execution_params` JSONB, `active_context` JSONB (unconsumed), `is_active`,
  `last_run_at`, `next_run_at`, soft-delete `BaseModel` fields.
  `AgentScheduleRun` (lines 168–273) — `scheduled_for`, `attempt_count`,
  `status` CHECK `('pending','claimed','accepted','running',
  'awaiting_approval','completed','retryable_failed','terminal_failed',
  'cancelled')`, claim columns, `conversation_id`, `agent_run_id`,
  `accepted_at`/`completed_at`/`failed_at`, `last_error_code`,
  `last_error_message`; UNIQUE `(schedule_id, scheduled_for)`.
- Services (`apps/api/services/agent_schedules/`), all existing and NOT to be
  modified:
  - `domain.py`: `normalize_schedule_config(...)` (line 46) validates
    type/cron (croniter)/interval ≥1/future-once/timezone and raises
    `AppValidationError`; `calculate_next_run` (142); `preview_schedule_runs`
    (171, capped at 100) — built for a preview endpoint, unused.
  - `runs.py`: `schedule_health_from_run(run) -> "healthy"|"retrying"|
    "needs_attention"|"cancelled"` (line 70) and
    `get_latest_runs_by_schedule_ids` (95, `DISTINCT ON`) — docstrings say
    they exist for list/detail responses; unused.
  - `authorisation.py`: `assert_can_create_schedule(*, membership)` (19,
    rejects read-only) and `assert_can_mutate_schedule(*, schedule,
    current_user, membership)` (26, schedule owner or workspace admin/owner)
    — written for routes, unused.
  - Claim/execution lifecycle: `claim_due_schedule_runs` selects **active,
    non-deleted** schedules with `next_run_at <= now` (`runs.py:256`);
    `finalize_schedule_run_execution` mirrors `awaiting_approval` onto the
    schedule run (`finalize_schedule_run_execution.py:72-76`);
    `reconcile_schedule_run_execution` propagates late approval outcomes
    (`reconcile_schedule_run_execution.py:33`).
- **No `services/agent_schedules/schemas.py`, no `routes/schedules/`
  package.** Router registration point: `routes/__init__.py:17-25`.
- Audit: the only schedule audit event today is the scheduler's terminal
  DISABLE (`runs.py:226-253`, actor SYSTEM "Scheduler").
  `AuditResourceType.AGENT_SCHEDULE` and `AGENT_SCHEDULE_RUN` already exist
  (`services/audit_events/enums.py:36-37`); `AGENT_SCHEDULE_RUN` is never
  emitted.
- Conventions to copy exactly: the agents route/service/schema shapes as
  documented in plan 016 §"Conventions to copy exactly" (route-per-file,
  `AsyncDbSessionDep`/`CurrentUserDep`/`CurrentWorkspaceDep`, list envelope
  `{items, total, limit, offset}`, `record_workspace_audit_event`, RFC 7807
  errors, `payload.model_fields_set` partial updates).
- Test exemplars: `tests/routes/agents/test_agent_routes.py`
  (`_authenticated_workspace` + `bearer_headers`),
  `tests/contract/test_openapi_routes.py:58-94` (path/method assertions).
  Factories exist for user/workspace/membership only — construct `Agent` /
  `AgentSchedule` inline as agent tests do.

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint    | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | "No new upgrade operations detected" |
| New tests | `uv run pytest tests/routes/schedules tests/services/agent_schedules -q` | all pass |
| Regression | `uv run pytest tests/routes/agents tests/contract -q` | all pass |

## Scope

**In scope (create unless marked otherwise):**

- `apps/api/services/agent_schedules/schemas.py`
- `apps/api/services/agent_schedules/create_schedule.py`, `list_schedules.py`,
  `get_schedule.py`, `update_schedule.py`, `delete_schedule.py`,
  `pause_schedule.py`, `enable_schedule.py`, `run_schedule_now.py`,
  `list_schedule_runs.py`, `preview_schedule.py`
- `apps/api/services/agent_schedules/utils.py` (fetch helper)
- `apps/api/services/agent_schedules/__init__.py` (modify: re-export the new
  operations alongside the existing ones)
- `apps/api/routes/schedules/__init__.py` + one route file per operation above
- `apps/api/routes/__init__.py` (modify: register `schedules_router`
  alphabetically)
- `apps/api/tests/routes/schedules/test_schedule_routes.py`
- `apps/api/tests/contract/test_openapi_routes.py` (modify: add schedule paths)

**Out of scope (do NOT touch):**

- `models/agent.py`, `alembic/` — no schema change, no migration.
- `domain.py`, `runs.py`, `prepare/finalize/reconcile_*`, `authorisation.py`,
  `workers/agent_runner.py` — the scheduling engine is frozen in this plan.
- `active_context` — plan 040.
- Approval decision endpoints — they live on agent-runs and stay there.
- The frontend — plan 022.

## Git workflow

- Branch: `advisor/021-schedule-routes`
- Commit style: `API - Add Schedule Routes`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `services/agent_schedules/schemas.py`

Following `services/agents/schemas.py` idioms
(`ConfigDict(from_attributes=True, populate_by_name=True)`, `from_*`
classmethods, list envelopes):

- `AgentScheduleRead`: `id`, `agent_id`, `user_id`, `workspace_id`,
  `schedule_type`, `cron_expression`, `interval_minutes`, `run_once_at`,
  `timezone`, `default_prompt`, `execution_params`, `is_active`,
  `last_run_at`, `next_run_at`, `created_at`, `updated_at`, plus computed
  `health: str | None` and `latest_run: AgentScheduleRunRead | None`
  (populated by the list/get services via `get_latest_runs_by_schedule_ids`
  and `schedule_health_from_run`). Do NOT expose `active_context` yet.
- `AgentScheduleRunRead`: `id`, `schedule_id`, `scheduled_for`, `status`,
  `attempt_count`, `conversation_id`, `agent_run_id`, `accepted_at`,
  `completed_at`, `failed_at`, `last_error_code`, `last_error_message`,
  `created_at`, plus `health`.
- `AgentSchedulesListResponse` / `AgentScheduleRunsListResponse`: items +
  `total`, `limit`, `offset`.
- `AgentScheduleCreateRequest`: `agent_id: UUID`, `schedule_type: str`,
  `cron_expression: str | None`, `interval_minutes: int | None`,
  `run_once_at: datetime | None`, `timezone: str | None`,
  `default_prompt: str` (min 1 after strip, max 20000 — a blank prompt is a
  guaranteed terminal failure at prepare time, so reject it at write time),
  `execution_params: dict | None`, `is_active: bool = True`. Shape-level
  checks only — timing-field cross-validation belongs to
  `normalize_schedule_config` in the service, not the schema (do not
  duplicate croniter logic).
- `AgentScheduleUpdateRequest`: same fields optional (no `agent_id`
  re-targeting — changing the agent is delete + recreate), honoring
  `model_fields_set` semantics.
- `SchedulePreviewRequest`: the four timing fields + `timezone` +
  `preview_count: int = Field(default=5, ge=1, le=20)`;
  `SchedulePreviewResponse`: `next_runs: list[datetime]`.

**Verify**: `uv run ruff check .` → exit 0.

### Step 2: Service operations

One file each, `db` first positional then keyword-only, mirroring
`services/agents/<op>.py`. All queries filter `workspace_id` and
`deleted == False`. Add `get_schedule_for_workspace(db, *, workspace,
schedule_id)` to a new `utils.py` (model on `get_agent_for_workspace`;
`NotFoundError(resource_type="agent_schedule")`).

- `create_schedule.py`: `assert_can_create_schedule(membership=membership)`;
  validate the target agent exists, is active, non-deleted, in-workspace
  (reuse the agents util the way `validate_agent_references` does; unknown →
  `AppValidationError(field="agent_id")`); run `normalize_schedule_config`
  over the timing fields; compute `next_run_at = calculate_next_run(config)`
  when `is_active` else `None`… **check `claim_due_schedule_runs` first**: it
  filters on `is_active`, so a paused schedule may keep its `next_run_at`
  safely — set it always, from the config. `user_id = actor.id`. Audit
  `CREATE`/`AGENT_SCHEDULE` with `details={"agent_id", "schedule_type",
  "timezone", "is_active"}`.
- `list_schedules.py`: filters `agent_id: UUID | None`,
  `include_inactive: bool = False`; order `created_at` desc (rides
  `ix_agent_schedules_workspace_active`); batch-load latest runs via
  `get_latest_runs_by_schedule_ids` and attach `health`/`latest_run`.
- `get_schedule.py`: fetch + latest run + health.
- `update_schedule.py`: `assert_can_mutate_schedule`; partial update via
  `model_fields_set`; if ANY timing field or `timezone` changes, re-run
  `normalize_schedule_config` on the merged result and recompute
  `next_run_at`; `is_active` transitions here follow the same rules as
  pause/enable (Step 3). Audit `UPDATE` with `changed_fields`.
- `delete_schedule.py`: `assert_can_mutate_schedule`; soft delete exactly as
  `delete_agent.py` does; audit `DELETE`. In-flight runs are untouched — the
  claim loop already skips deleted schedules.
- `pause_schedule.py`: mutate-guard; `is_active = False`; audit `DISABLE`
  (actor USER — distinguishable from the scheduler's SYSTEM DISABLE).
  Idempotent: pausing a paused schedule is a no-op 200.
- `enable_schedule.py`: mutate-guard; `is_active = True`; recompute
  `next_run_at = calculate_next_run(config, basis=now)` per decision 3; a
  `once` schedule whose `run_once_at` is in the past cannot be re-enabled →
  `AppValidationError`. Audit `ENABLE`.
- `run_schedule_now.py`: mutate-guard; paused → `ConflictError`; set
  `next_run_at = now()`; audit `EXECUTE`/`AGENT_SCHEDULE` with
  `details={"requested_at"}`. Return the schedule read model (202 at the
  route). Do NOT touch run rows — the worker owns creation.
- `list_schedule_runs.py`: read access (any member); runs for one schedule,
  `status: str | None` filter validated against the model's status set,
  order `scheduled_for` desc, limit/offset envelope. Rides
  `(schedule_id, created_at)` index.
- `preview_schedule.py`: pure function call — `normalize_schedule_config`
  (with `require_future_once=False`) + `preview_schedule_runs`. No DB writes,
  no audit.

**Verify**: `uv run ruff check .` → exit 0.

### Step 3: Route package

`routes/schedules/` with `APIRouter(prefix="/schedules",
tags=["schedules"])`, one file per operation, thin handlers unpacking
`CurrentWorkspaceDep`:

- `POST /schedules/` → 201 `AgentScheduleRead`
- `GET /schedules/` → list; `limit ge=1 le=500 =100`, `offset ge=0 =0`,
  `include_inactive: bool = False`, `agent_id: UUID | None = None`
- `GET /schedules/{schedule_id}` → `AgentScheduleRead`
- `PATCH /schedules/{schedule_id}` → `AgentScheduleRead`
- `DELETE /schedules/{schedule_id}` → 204
- `POST /schedules/{schedule_id}/pause` → 200 `AgentScheduleRead`
- `POST /schedules/{schedule_id}/enable` → 200 `AgentScheduleRead`
- `POST /schedules/{schedule_id}/run-now` → 202 `AgentScheduleRead`
- `GET /schedules/{schedule_id}/runs` → `AgentScheduleRunsListResponse`
- `POST /schedules/preview` → 200 `SchedulePreviewResponse` (register this
  route BEFORE the `/{schedule_id}` routes in `__init__.py` so `preview`
  never matches as a UUID path — FastAPI matches in inclusion order)

Register `schedules_router` in `routes/__init__.py` alphabetically (after
`models_router`, before `skills_router` if plan 016 landed, else before
`storage_router`).

**Verify**: `uv run ruff check .` → exit 0, and
`uv run python -c "from main import app; print(sorted(r.path for r in app.routes if 'schedules' in r.path))"`
→ prints the ten `/api/v1/schedules...` paths.

### Step 4: Tests

`tests/routes/schedules/test_schedule_routes.py`, modeled on
`test_agent_routes.py` (`_authenticated_workspace` helper, `bearer_headers`,
`db_async_client`, problem+json assertions). Construct `Agent` +
`AgentSchedule` inline. Cover at minimum:

- create (cron) → 201, `next_run_at` populated, audit row
  `CREATE`/`agent_schedule`
- create with invalid cron / interval 0 / past `run_once_at` / blank
  `default_prompt` / cross-workspace `agent_id` → 400 problem+json
- read-only member create → 403; **member A cannot PATCH member B's
  schedule (403) but a workspace admin can (200)** — this is the
  authorisation.py contract, test it at the HTTP boundary
- list: excludes soft-deleted, excludes inactive by default, `agent_id`
  filter works, includes `health`/`latest_run` when a run row exists
- pause → `is_active` False + audit DISABLE (actor USER); enable → recomputed
  `next_run_at` ≥ now + audit ENABLE; enable on expired `once` → 400
- run-now on active → 202 + `next_run_at <= now()` + audit EXECUTE; on
  paused → 409
- runs history: seed runs incl. one `awaiting_approval` with `agent_run_id`
  set → response exposes it; `status` filter works; other-workspace schedule
  → 404
- preview: cron config returns N future datetimes in order; invalid timezone
  → 400

Extend `tests/contract/test_openapi_routes.py` with the new paths/methods in
its existing style.

**Verify**:
`uv run pytest tests/routes/schedules tests/services/agent_schedules tests/contract -q`
→ all pass, then `uv run pytest tests/routes/agents -q` → all pass.

## Test plan

Covered by Step 4 (~16–20 HTTP-boundary tests + contract additions). The
scheduling engine keeps its existing service tests untouched
(`tests/services/agent_schedules/`) — if any of those fail, that is a
baseline break, not your bug (STOP condition).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no new operations
- [ ] `uv run pytest tests/routes/schedules tests/services/agent_schedules tests/contract -q` exits 0
- [ ] `uv run pytest tests/routes/agents -q` exits 0 (no regression)
- [ ] All ten routes appear in the OpenAPI schema under `/api/v1/schedules`
- [ ] Audit rows written for create/update/delete/pause/enable/run-now
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `routes/schedules/` or `services/agent_schedules/schemas.py` already exists.
- The `AgentSchedule`/`AgentScheduleRun` columns or status vocabularies differ
  from "Current state" (the worker contract moved under you).
- `assert_can_create_schedule` / `assert_can_mutate_schedule` /
  `schedule_health_from_run` / `get_latest_runs_by_schedule_ids` are missing
  or have different signatures.
- You find yourself wanting to modify `runs.py`, `domain.py`, the
  prepare/finalize/reconcile services, or the worker — that means a design
  assumption failed; report instead.
- Existing `tests/services/agent_schedules/` tests fail before your changes.

## Maintenance notes

- Plan 022 builds the UI on exactly these routes; the `health` +
  `latest_run` + `agent_run_id` fields are its contract — treat them as
  stable from day one.
- Plan 040 adds `active_context` selection: it extends
  `AgentScheduleCreateRequest`/`UpdateRequest` and the read model, and
  wires consumption in `prepare_schedule_run_execution`. Nothing here should
  make that harder.
- Plan 026 (dispatch choke point) adds capability envelopes for
  non-interactive runs; schedule runs currently stall in `awaiting_approval`
  when a tool needs approval — 026 owns changing that, not this plan.
- Follow-up recorded (decision 5): approval visibility/decisions for
  schedule runs are limited to the run's owning user by the agent-runs
  endpoints; widening to workspace admins needs a deliberate authz change on
  `get_approval_state`/`resume`.
- Reviewers should scrutinize: workspace scoping on every query, the
  owner-vs-admin mutation matrix, run-now on paused (409), and that no
  service in the scheduling engine changed.
