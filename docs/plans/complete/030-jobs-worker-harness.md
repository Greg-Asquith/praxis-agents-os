# Plan 030: Generic jobs table and SKIP-LOCKED worker harness

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G3 pre-flight (run before Step 1)**: this plan was written BEFORE
> plan 029 executed, by explicit operator instruction overriding the
> roadmap's write-order guidance. If `docs/architecture/governance.md`
> exists, re-verify every governance citation below against it (the note
> wins over this plan; reconcile any changed default before coding). If it
> does NOT exist, get explicit operator confirmation before proceeding.
> Governance defaults below are cited as "plan 029 Step N defaults" from
> `docs/plans/029-governance-lifecycle-design-note.md`.
>
> **Drift check (run first)**: `git diff --stat 9208c47..HEAD -- apps/api/workers/ apps/api/models/ apps/api/core/settings/ apps/api/services/agent_schedules/runs.py apps/api/services/notifications/ docker-compose.yml makefile/local.mk`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (changes the deployed worker entrypoint; the existing
  schedule loop must keep running unchanged)
- **Depends on**: none hard — this is the Phase 3 substrate. Soft: plan 029
  (Gate G3 pre-flight above); does not depend on any other Phase 3 plan.
- **Category**: shared substrate (roadmap `000_MASTER_ROADMAP.md` §4
  Phase 3; donor `DONOR_PORT_ROADMAP.md` §3.4 / §6 row B1)
- **Planned at**: commit `9208c47`, 2026-07-03

## Decisions taken

1. **One worker process, two loops.** The harness runs *beside* the
   schedule loop inside the same container: a new `workers/job_runner.py`
   polling loop plus a thin `workers/main.py` supervisor that runs
   `agent_runner.run_forever` and `job_runner.run_forever` as sibling
   asyncio tasks under one shutdown event. `docker-compose.yml` defines
   exactly one `worker` service (line 57) and `make dev` starts exactly one
   worker (`makefile/local.mk:77-79`) — a second service doubles the ops
   surface for zero isolation benefit at this scale. `agent_runner.py`
   itself is untouched; its `--once` CLI stays for tests.
2. **Jobs rows are not soft-deleted.** `Job` uses `Base + UUIDMixin +
   TimestampMixin` (the `RateLimitAttempt` precedent,
   `models/rate_limiting.py:16`), not `BaseModel`. Lifecycle lives in
   `status`; the sweeper hard-deletes terminal rows after 30 days (plan 029
   Step 4 defaults: "Jobs + payloads … terminal rows kept … 30 d …
   counters only"). Soft-delete columns on an operational queue are dead
   weight and would poison every claim predicate.
3. **Lease pattern with explicit expiry**, mirroring the schedule runner:
   `locked_by`/`locked_at`/`lock_expires_at`, matching
   `AgentScheduleRun.claim_token/claimed_at/claim_expires_at`
   (`models/agent.py:194-196`). Stale reclaim treats an expired lease as
   a failed attempt: attempts were already consumed at claim, so reclaim
   uses the same finalization path as handler failures, either backing off
   to `pending` or marking `failed` when `max_attempts` is exhausted.
4. **Handler registration is a decorator with import-time uniqueness**,
   exactly the plan 025 tool-registry shape: `@job_handler(kind=...)` into
   a module-level dict; a duplicate kind raises `RuntimeError` at import
   (fail the process, not the job). Handlers are async, receive
   `(db, job)`, run inside their own session, and are wrapped in
   `asyncio.wait_for` with a per-kind timeout override.
5. **In-flight dedup only, via a partial unique expression index** on
   `(coalesce(workspace_id::text,''), kind, coalesce(subject_type,''),
   coalesce(subject_id::text,''), content_hash) WHERE status IN
   ('pending','running')`. Workspace jobs dedup only inside their tenant;
   system jobs with `workspace_id IS NULL` dedup globally. Enqueue catches
   only this unique violation and returns the existing row. Terminal rows
   never block re-enqueue — re-running a failed extraction is a feature.
   `content_hash` defaults to sha256 of the canonical JSON payload,
   caller-overridable.
6. **The retention sweeper lives here** — recording plan 029's maintenance
   note verbatim: "plan 030's worker harness is its natural home (one
   sweep job kind per resource); record that in 030's plan when written."
   This plan ships the sweep-job *pattern* plus one built-in kind
   (`jobs.sweep_terminal`, self-rescheduling, deletes terminal job rows
   older than 30 d per 029 Step 4). Each later plan registers its own
   sweep kind: 032 (files/blobs), 044 (KB documents), 051 (artifact
   shares). The harness does not sweep anyone else's tables.
7. **Jobs quota counter, minimal.** Per plan 029 Step 5 defaults ("job
   concurrency 4/workspace with global worker cap; counters + admin
   visibility first, hard enforcement second" — 030 named as the plan
   adding the jobs counter): this plan ships `count_in_flight_jobs()` (a
   count query grouped by workspace) and a claim-time warning log when a
   workspace exceeds `JOBS_WORKSPACE_CONCURRENCY_LIMIT` (default 4). The
   global cap is the worker's own batch/concurrency settings. **Hard
   per-workspace enforcement is deferred to plan 033** (the first
   high-volume producer); the admin-visible counter *route* is deferred to
   033's status surface. No quota service is built here.
8. **Notification policy** per plan 029 Step 7 defaults: job pipelines
   notify **only after the final retry is exhausted**, to the initiator
   (`initiated_by_user_id`), via the existing
   `services/notifications/service.py::create_notification`
   (verified at `service.py:105-158`). Success, intermediate retries, and
   initiator-less system jobs (sweeps) log only. No per-job audit rows —
   029 Step 4 says jobs survive in audit as "counters only".
9. **Gaps-doc questions resolved or deferred**
   (`docs/legacy/ROADMAP_QUESTIONS_GAPS.md`): "jobs and failed job
   payloads" retention (§Data Lifecycle) — resolved here (decision 2/6);
   "per-workspace embedding/job budgets" (§Quotas) — jobs counter here,
   embedding budgets deferred to plan 043; "are job failures shown only on
   detail pages, or also as notifications" (§Notifications) — resolved
   here (decision 8); job-status UI feedback — deferred to plan 033
   (file processing status lifecycle) and 039 (discovery runs).

## Why this matters

Every Phase 3+ pipeline is a background job: file extraction→markdown
(033), integration resource discovery (039), KB ingestion/chunking/
embedding (044) — plus the retention sweepers 029 assigns to this harness
(032 files, 044 KB, 051 shares). The donor built exactly this table
(`knowledge_model_jobs`) and then undermined it with a second parallel
queue; the roadmap's contract (donor §3.4, roadmap D-spine) is that we
build it **once** and everything queue-shaped rides it. The codebase
already proves the pattern at small scale — the schedule runner does
SKIP-LOCKED claiming, TTL leases, bounded retries, and terminal states —
but that machinery is welded to `AgentSchedule`/`AgentScheduleRun`. This
plan generalizes it into a `jobs` table and a kind-keyed handler registry
so 033/039/044 ship handlers, not infrastructure.

## Current state

All anchors verified at `9208c47`. Nothing jobs-shaped exists yet; the
closest machinery is schedule-specific:

- `apps/api/workers/agent_runner.py` — the only worker process:
  `run_forever` polls on `settings.AGENT_SCHEDULE_WORKER_POLL_SECONDS`
  (lines 127–152), `main()` has a `--once` CLI flag (155–172), signal
  handlers set a shared `asyncio.Event` (378–382), worker identity is
  `f"{os.uname().nodename}:{os.getpid()}"` (385–386).
- `apps/api/services/agent_schedules/runs.py` — the claiming precedent:
  `claim_due_schedule_runs` (256–328) uses
  `.with_for_update(skip_locked=True, of=AgentSchedule)` (line 277);
  `_claim_run` stamps token/claimed_at/expiry and increments
  `attempt_count` (154–168); `mark_run_retryable_failure` returns True
  when attempts exhaust `max_attempts` (331–351);
  `sanitize_error_message` caps stored errors at 1000 chars (84–92).
  Stale recovery lives in `reconcile_schedule_run_execution.py`.
- `apps/api/models/agent.py:168` `AgentScheduleRun`: lease columns
  `claim_token`/`claimed_at`/`claim_expires_at` (194–196), status CHECK
  constraint and partial indexes (e.g.
  `ix_agent_schedule_runs_claim_expiry` on `(status, claim_expires_at)
  WHERE status = 'claimed'`, ~245).
- `apps/api/models/base.py`: `BaseModel` (130–138) carries soft-delete;
  `UUIDMixin` (18–21), `TimestampMixin` (24–30), `CreatedAtMixin`
  (124–127). `models/rate_limiting.py:16` shows the non-soft-delete
  composition this plan copies. New models must be imported in
  `models/__init__.py` (registry comment, lines 1–12).
- Migrations: `apps/api/alembic/versions/core/` holds `core_0001` …
  `core_0006` (head `core_0006` in
  `0006_rename_agent_call_conversation_source.py`). Roadmap decision D5:
  all roadmap tables go on the **core** branch.
- Settings: `core/settings/agents.py:8-73` `AgentRunSettingsMixin` is the
  worker-settings precedent; mixins compose in
  `core/settings/__init__.py` (imports lines 13–27, class bases 32–45).
- Wiring: `docker-compose.yml:57-76` `worker` service, command
  `["python", "-m", "workers.agent_runner"]` (line 63);
  `makefile/local.mk:77-79` `worker-dev` runs
  `uv run python -m workers.agent_runner`.
- `apps/api/services/notifications/service.py:105-158`
  `create_notification(db, *, notification_type, title, ..., recipient_user_id, workspace_id, source, ...)` —
  exists and is already used by invites; decision 8 targets it.
- Tests precedent: `tests/services/agent_schedules/test_agent_runner.py`
  exercises the worker loop; DB-backed tests gate on `TEST_DATABASE_URL`
  via `conftest.py` fixtures.
- Will exist after other plans (do not assume now): tool dispatch audit
  (026), file processing job kinds (033), discovery kinds (039), KB
  ingestion kinds (044), per-resource sweep kinds (032/044/051).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations after Step 2 |
| Apply migration | `uv run alembic upgrade heads` | `jobs` table created |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/jobs -q` | all pass |
| Schedule-loop regression | `uv run pytest tests/services/agent_schedules -q` | all pass, untouched behavior |
| Worker smoke | `uv run python -m workers.job_runner --once` | one pass, exit 0 |

## Scope

**In scope:**

- `apps/api/models/jobs.py` (create — `Job` model) +
  `apps/api/models/__init__.py` (register import)
- `apps/api/alembic/versions/core/0007_*.py` (create — core branch, D5)
- `apps/api/core/settings/jobs.py` (create — `JobsSettingsMixin`) +
  `apps/api/core/settings/__init__.py` (compose it)
- `apps/api/services/jobs/` (create): `__init__.py`, `domain.py`,
  `registry.py`, `enqueue_job.py`, `claim_jobs.py`, `finalize_job.py`,
  `reclaim_stale_jobs.py`, `count_jobs.py`, `utils.py`,
  `handlers/sweep_terminal_jobs.py`
- `apps/api/workers/job_runner.py`, `apps/api/workers/main.py` (create)
- `docker-compose.yml` (worker command → `workers.main`),
  `makefile/local.mk` (`worker-dev` → `workers.main`)
- `apps/api/tests/services/jobs/` (create), `tests/factories/` (job
  factory helper)

**Out of scope (do NOT touch):**

- ANY real job kinds beyond `jobs.sweep_terminal` — 033/039/044 register
  theirs.
- HTTP routes and UI. Jobs have **no public surface** in this plan; per
  AGENTS.md, document it as pending (033 adds the first user-visible
  status surface). Do not add a routes package.
- Hard per-workspace concurrency enforcement (deferred to 033, decision 7)
  and any quota service.
- The schedule runner's own tables/services — the schedule loop keeps its
  domain-specific machinery; migrating schedules onto `jobs` is explicitly
  not this plan (they have UI-facing semantics `jobs` must not grow).
- Sweeping non-job tables (files, KB, shares — decision 6).
- `services/agents/**` — no runtime changes.

## Git workflow

- Branch: `advisor/030-jobs-worker-harness`
- Commit style: `API - Add Generic Jobs Worker Harness`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

Create `core/settings/jobs.py` with `JobsSettingsMixin` (shape of
`AgentRunSettingsMixin`, `core/settings/agents.py:8`):

```python
JOBS_WORKER_POLL_SECONDS: float = 5.0          # loop cadence
JOBS_WORKER_BATCH_SIZE: int = 10               # global cap per pass (029 Step 5 "global worker cap")
JOBS_LOCK_TTL_SECONDS: int = 300               # lease before stale reclaim
JOBS_HANDLER_TIMEOUT_SECONDS: float = 600.0    # default per-job timeout
JOBS_DEFAULT_MAX_ATTEMPTS: int = 5             # bounded retries
JOBS_RETRY_BACKOFF_BASE_SECONDS: int = 30      # backoff = base * 2**(attempts-1)
JOBS_RETRY_BACKOFF_CAP_SECONDS: int = 3600     # backoff ceiling
JOBS_TERMINAL_RETENTION_DAYS: int = 30         # 029 Step 4 default
JOBS_SWEEP_INTERVAL_SECONDS: int = 3600        # sweep self-reschedule cadence
JOBS_WORKSPACE_CONCURRENCY_LIMIT: int = 4      # 029 Step 5 default; observed, not enforced (plan 033)
```

All `Field(..., gt=0, description=...)`. Compose the mixin into
`Settings` in `core/settings/__init__.py` alongside the others; no
production-safety validator change is needed (no local-only values here).

**Verify**: `uv run python -c "from core.settings import settings; print(settings.JOBS_WORKER_POLL_SECONDS)"`
→ `5.0`, and `uv run ruff check .` → exit 0.

### Step 2: Model + core migration

Create `models/jobs.py` with `Job(Base, UUIDMixin, TimestampMixin)`
(decision 2), `__tablename__ = "jobs"`:

- `workspace_id` UUID FK `workspaces.id`, nullable (system jobs like
  sweeps carry NULL), indexed
- `kind` String(64) not null; `subject_type` String(64) nullable;
  `subject_id` UUID nullable; `content_hash` String(64) not null,
  server_default `''`
- `payload` JSONB not null, server_default `'{}'::jsonb` — ids and small
  parameters only, never blobs
- `priority` Integer not null, server_default `100` (lower runs sooner)
- `status` String(16) not null, server_default `'pending'`, CHECK in
  `('pending','running','succeeded','failed','cancelled')`
- `run_after` DateTime(tz) not null, server_default `now()` (scheduling +
  backoff target)
- `attempts` Integer not null server_default `0`; `max_attempts` Integer
  not null server_default `5`; CHECK `attempts >= 0` and
  `max_attempts > 0`
- `locked_by` String(255) nullable; `locked_at`, `lock_expires_at`
  DateTime(tz) nullable (decision 3)
- `initiated_by_user_id` UUID FK `users.id`, nullable (decision 8 target)
- `last_error_code` String(64), `last_error_message` Text, `finished_at`
  DateTime(tz) — all nullable

Indexes (mirror the `AgentScheduleRun` style, `models/agent.py:230-248`):

- claim: `(status, run_after, priority)` partial
  `WHERE status = 'pending'`
- reclaim: `(status, lock_expires_at)` partial `WHERE status = 'running'`
- counters: `(workspace_id, status)`
- dedup (decision 5, expression index — declare in the migration with
  `sa.text(...)` columns, mirror it in `__table_args__` via `Index` with
  text expressions):

```sql
CREATE UNIQUE INDEX uq_jobs_in_flight ON jobs
  (
    coalesce(workspace_id::text, ''),
    kind,
    coalesce(subject_type, ''),
    coalesce(subject_id::text, ''),
    content_hash
  )
  WHERE status IN ('pending', 'running');
```

Import `Job` in `models/__init__.py`. Generate the migration on the core
branch (D5): `uv run alembic revision --autogenerate --head core@head
--version-path alembic/versions/core -m "add jobs table"`, then
hand-check the expression index made it in (autogenerate often misses
expression indexes — add it manually with a matching `downgrade`).

**Verify**: `uv run alembic upgrade heads` → applies cleanly, then
`uv run alembic check` → no pending operations, and downgrade/upgrade
round-trips (`uv run alembic downgrade core@-1 && uv run alembic upgrade heads`).

### Step 3: Handler registry + domain

`services/jobs/domain.py`: status constants
(`JOB_STATUS_PENDING = "pending"`, …), `TERMINAL_JOB_STATUSES`
frozenset (`succeeded/failed/cancelled`), kind-name rule
`^[a-z][a-z0-9_.]*$` (dotted namespaces: `files.extract`,
`jobs.sweep_terminal`).

`services/jobs/registry.py` (the plan 025 shape):

```python
JOB_HANDLERS: dict[str, JobHandlerDefinition] = {}

def job_handler(*, kind: str, timeout: float | None = None, max_attempts: int | None = None):
    # validates kind pattern; duplicate kind -> RuntimeError at import time
    ...
```

`JobHandlerDefinition` is a frozen dataclass: `kind`, `function`
(async `(db, job) -> None`), `timeout`, `max_attempts` (enqueue-time
default for that kind; falls back to settings). `registry.py` imports
`services.jobs.handlers` for registration side effects, with a comment
naming it as the assembly point plans 032/033/039/044/051 extend.

`services/jobs/utils.py`: `compute_content_hash(payload)` (sha256 of
canonical `json.dumps(..., sort_keys=True, separators=(",", ":"))`),
`retry_backoff(attempts)` (base × 2^(attempts−1), capped, ±20% jitter),
and re-use of the sanitize-message rule (1000-char cap, same as
`agent_schedules/runs.py:84-92` — copy the tiny helper, do not import
across service packages).

**Verify**: `uv run python -c "from services.jobs.registry import JOB_HANDLERS; print(sorted(JOB_HANDLERS))"`
→ `['jobs.sweep_terminal']` (after Step 5; before it, `[]`), ruff exit 0.

### Step 4: Service operations (one per file)

- `enqueue_job.py` — `enqueue_job(db, *, kind, workspace_id=None,
  subject_type=None, subject_id=None, payload=None, content_hash=None,
  priority=100, run_after=None, max_attempts=None,
  initiated_by_user_id=None) -> Job`. Validates the kind is registered
  (raise `AppValidationError` from `core/exceptions` otherwise — typed
  RFC 7807, no ad-hoc HTTPException), computes `content_hash` when absent,
  inserts, and on the partial-unique `IntegrityError` rolls back to a
  SAVEPOINT and returns the existing in-flight row (decision 5). Use
  `db.begin_nested()` around the insert so dedup does not poison the
  caller's transaction.
- `claim_jobs.py` — the SKIP-LOCKED core, modeled on
  `claim_due_schedule_runs`:

  ```python
  select(Job)
      .where(Job.status == JOB_STATUS_PENDING, Job.run_after <= now)
      .order_by(Job.priority, Job.run_after, Job.created_at)
      .limit(batch_size)
      .with_for_update(skip_locked=True)
  ```

  Claiming stamps `status='running'`, `locked_by` (the
  `hostname:pid` identity, same scheme as `agent_runner.py:385-386`),
  `locked_at=now`, `lock_expires_at=now+ttl`, `attempts += 1`. After
  claiming, call `count_in_flight_jobs` and log a warning per workspace
  over `JOBS_WORKSPACE_CONCURRENCY_LIMIT` (decision 7 — observe, don't
  enforce).
- `reclaim_stale_jobs.py` — select expired `running` jobs with
  `lock_expires_at < now()` under `FOR UPDATE SKIP LOCKED`, then route
  each through `finalize_job_failure(code="lease_expired")`. Retryable
  rows return to `pending` with backoff and cleared locks; exhausted rows
  become terminal `failed` rows and follow the final-failure notification
  policy. Returns count; called at the top of each polling pass (the
  `reconcile_schedule_run_execution` slot in the loop shape).
- `finalize_job.py` — `finalize_job_success` (status `succeeded`,
  `finished_at`, clear lock/error columns) and `finalize_job_failure`:
  if `attempts >= max_attempts` → `failed`, `finished_at`, and — only
  when `initiated_by_user_id` is set — `create_notification(db,
  notification_type="job_failed", title=..., recipient_user_id=...,
  workspace_id=..., source="jobs")` (decision 8; final-retry-exhausted
  only, per 029 Step 7). Otherwise → back to `pending` with
  `run_after = now + retry_backoff(attempts)`, lock cleared, error
  columns stamped.
- `count_jobs.py` — `count_in_flight_jobs(db, *, workspace_id=None)`:
  grouped count of `pending`+`running` rows; the 029 Step 5 jobs counter.
  No route (decision 7 defers the surface to 033) — the docstring must
  say exactly that.

`services/jobs/__init__.py` only re-exports operation functions
(AGENTS.md service-package rule).

**Verify**: `uv run ruff check .` → exit 0;
`uv run pytest tests/services/agent_schedules -q` → still green
(nothing schedule-side touched).

### Step 5: The sweep pattern + built-in kind

`services/jobs/handlers/sweep_terminal_jobs.py`:

```python
@job_handler(kind="jobs.sweep_terminal", timeout=120.0)
async def sweep_terminal_jobs(db, job):
    # hard-delete terminal job rows older than JOBS_TERMINAL_RETENTION_DAYS (029 Step 4: 30 d)
    # then self-reschedule: enqueue same kind, run_after = now + JOBS_SWEEP_INTERVAL_SECONDS
```

Plus `ensure_sweep_job(db)` (in the same file): enqueue the kind with
`run_after=now` if no in-flight row exists — the dedup index makes this
idempotent, so the worker calls it once per polling pass, cheaply. This
file IS the pattern later sweepers copy: one kind per resource, the
owning plan registers it (032 files/blobs, 044 KB, 051 shares —
decision 6, recording 029's maintenance note).

**Verify**: Step 3's registry print now shows
`['jobs.sweep_terminal']`.

### Step 6: Worker loop + supervisor + wiring

`workers/job_runner.py` — clone the `agent_runner.py` skeleton
(127–172), not its schedule logic: `run_once` opens a session, runs
`reclaim_stale_jobs` + `ensure_sweep_job`, claims a batch, commits, then
executes each job in its own session with
`asyncio.wait_for(handler(db, job), timeout=definition.timeout or
settings.JOBS_HANDLER_TIMEOUT_SECONDS)`; success/failure/timeout route
through `finalize_job.py` (a timeout is an ordinary retryable failure).
Unknown persisted kind (handler removed since enqueue) → immediate
terminal failure with code `unknown_kind`. `run_forever` polls on
`JOBS_WORKER_POLL_SECONDS`; `main()` gets the same `--once` flag.

`workers/main.py` — the supervisor (decision 1): install the signal
handlers (same pattern as `agent_runner.py:378-382`), start both
`run_forever` coroutines as named tasks sharing the shutdown event,
`asyncio.wait(..., return_when=FIRST_COMPLETED)`; if either loop exits
unexpectedly, set the shutdown event, drain the other within
`AGENT_SCHEDULE_WORKER_SHUTDOWN_SECONDS`, exit non-zero (compose
`restart: unless-stopped` handles the restart). Call
`close_db_connections()` in `finally`.

Update `docker-compose.yml:63` command to
`["python", "-m", "workers.main"]` and `makefile/local.mk:79` to
`uv run python -m workers.main`.

**Verify**: `uv run python -m workers.job_runner --once` → exits 0 and
logs one pass (sweep enqueued + executed);
`uv run python -m workers.agent_runner --once` → still exits 0.

### Step 7: Tests

`tests/services/jobs/` (all modules set
`pytestmark = pytest.mark.asyncio`; DB-backed tests use the
`conftest.py` fixtures and skip cleanly without `TEST_DATABASE_URL`):

- `test_job_registry.py` (no DB): decorator registers; duplicate kind
  raises `RuntimeError`; invalid kind pattern rejected; backoff grows,
  caps, and jitters within bounds; `compute_content_hash` is
  key-order-independent.
- `test_enqueue_job.py`: unknown kind → `AppValidationError`; in-flight
  dedup returns the existing row (same kind/subject/hash); terminal row
  does NOT block re-enqueue; NULL-subject jobs dedup against each other
  (the coalesce index working).
- `test_claim_jobs.py`: priority then run_after ordering; future
  `run_after` not claimed; two concurrent sessions claiming split the
  batch without overlap (SKIP LOCKED pinned); claim increments
  `attempts`; over-limit workspace logs the decision-7 warning
  (caplog).
- `test_finalize_and_reclaim.py`: failure below `max_attempts` → pending
  with backoff `run_after`; final failure → `failed` + notification row
  for the initiator, none without an initiator; success clears lock and
  errors; expired lease records `lease_expired` and either backs off to
  pending or fails terminally when attempts are exhausted, unexpired left
  alone.
- `test_sweep_terminal_jobs.py`: old terminal rows deleted, fresh
  terminal and in-flight rows kept; handler re-enqueues itself;
  `ensure_sweep_job` is idempotent.
- `test_job_runner.py` (pattern of
  `tests/services/agent_schedules/test_agent_runner.py`): `run_once`
  executes a registered test kind end to end; handler exception →
  retry path; handler timeout → retryable failure with code recorded.
  Register throwaway kinds via the decorator inside a fixture and remove
  them from `JOB_HANDLERS` in teardown — do not leak test kinds.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/jobs tests/services/agent_schedules -q`
→ all pass; without the env var the jobs DB tests skip, not fail.

## Test plan

Covered by Step 7 (~18–22 tests). The pinned invariants: **no double
execution** (SKIP-LOCKED split + dedup index), **bounded retries with a
terminal state** (a crash loop cannot run forever), **the schedule loop
is behaviorally untouched** (its existing suite green with zero edits),
and **notification fires exactly once, only on final failure, only to an
initiator** (029 Step 7).

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `uv run alembic check` reports no pending operations;
      migration is on the **core** branch (D5) and downgrade round-trips
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/jobs tests/services/agent_schedules -q` exits 0
- [ ] `uv run python -m workers.job_runner --once` and
      `uv run python -m workers.agent_runner --once` both exit 0
- [ ] `docker-compose.yml` + `makefile/local.mk` run `workers.main`;
      `make dev` starts one worker process running both loops
- [ ] No routes package added; `count_in_flight_jobs` docstring names 033
      as the surface owner
- [ ] Grep shows exactly one registered kind (`jobs.sweep_terminal`)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated (add the 030 row if
      absent)

## STOP conditions

Stop and report back (do not improvise) if:

- The Gate G3 pre-flight fails: `docs/architecture/governance.md` exists
  and contradicts a cited 029 default (the note wins — reconcile first),
  or it does not exist and the operator has not confirmed proceeding.
- A `jobs` table, `models/jobs.py`, `services/jobs/`, or `workers/main.py`
  already exists (someone started the substrate first).
- The core migration head is not `core_0006` at execution time — renumber
  against the real head, and re-verify no landed migration created a
  conflicting index name.
- `agent_runner.py` no longer matches the "Current state" shape (loop/
  shutdown/`--once` structure changed) — the supervisor design in Step 6
  assumed it.
- The expression-based partial unique index cannot be expressed in your
  SQLAlchemy/Alembic versions without raw DDL beyond
  `op.execute`/`sa.text` — report rather than silently dropping dedup.
- Existing `tests/services/agent_schedules` tests fail before your
  changes.
- You feel the need to add HTTP routes, a quota service, or a second
  compose service — scope leaking in (033 / later plans).

## Maintenance notes

- **Consumers**: 033 (file extraction→markdown kinds), 039 (integration
  resource discovery kinds), 044 (KB ingestion/chunking/embedding kinds)
  each register handlers at the Step 3 assembly point; 032/044/051 each
  register one sweep kind per resource (decision 6). Handlers MUST be
  idempotent — stale reclaim means at-least-once execution; that
  requirement belongs in every consumer plan's review checklist.
- **Payload discipline**: ids and small parameters only. A reviewer who
  sees document text or file bytes in `payload` should block the PR —
  029 Step 4 keeps terminal rows 30 days, and blobs belong in storage.
- **Enforcement second**: when per-workspace job concurrency graduates
  from counter to hard limit (033), the seam is `claim_jobs.py` — add a
  per-workspace cap to the claim query, do not bolt a check onto
  enqueue (enqueue-time checks race).
- **Schedules stay separate** deliberately: `AgentScheduleRun` carries
  UI-facing states (`awaiting_approval`) and audit semantics the generic
  table must not grow. If a future plan proposes merging them, it must
  answer for those states first.
- If plan 026's dispatch audit lands columns that make per-job audit rows
  cheap, revisit decision 8's "counters only" — update
  `docs/architecture/governance.md` §Retention, not just this plan.
- Reviewers should scrutinize: the coalesce dedup index (NULL subjects
  must dedup), SAVEPOINT handling in `enqueue_job` (dedup must not poison
  the caller's transaction), reclaim-vs-attempts interaction (claim
  increments, reclaim finalizes a failure without incrementing again), and
  that `workers/main.py` exits non-zero when either loop dies.
