# Plan 004: Rate limiter — bounded key cardinality, retention sweep, and tests

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/improvements/README.md`.
>
> **Drift check (run first)**: `git diff --stat a0eea1c..HEAD -- apps/api/core/rate_limiting.py apps/api/middleware/rate_limit.py apps/api/models/rate_limiting.py apps/api/services/jobs/handlers apps/api/workers/job_runner.py apps/api/core/settings/rate_limit.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (auth brute-force protection — behavior must not weaken)
- **Depends on**: none (001 recommended first for the test gate)
- **Category**: security / perf / tests
- **Planned at**: commit `a0eea1c`, 2026-07-06

## Why this matters

The Postgres-backed rate limiter is the login/registration/password-reset
brute-force defense, and it has three compounding problems. It keys buckets on
the raw URL path, so every distinct path-parameter URL
(`/api/v1/conversations/<uuid>/messages`, …) mints a new row per IP per
window — unbounded key cardinality. Nothing ever deletes
`rate_limit_attempts` rows (the model even declares
`Index("ix_rate_limit_cleanup", "created_at")  # For cleanup queries`, but no
cleanup exists), so the table the hot-path upsert touches on every request
grows forever. And no test in the repo exercises any of it — window math, the
upsert counter, invalid-IP handling, or the fail-closed-on-auth-paths
behavior can all regress silently.

## Current state

Relevant files (under `apps/api/`):

- `core/rate_limiting.py` — `RateLimiter` (window math in `_window_start`,
  line 258; upsert in `_check_rate_limit_db`, lines 152-188; invalid-IP
  most-restrictive branch at lines 96-109; `default_limits` at lines 59-65:
  `requests_per_minute` (60s), `requests_per_hour` (3600s), `login_attempts`
  (3600s), `registration` (86400s), `password_reset` (86400s)); module-global
  `rate_limiter = RateLimiter()` (line 269); `get_client_ip` with
  trusted-proxy handling (line 356); `require_rate_limit` dependency
  (line 414, also uses `request.url.path` as the endpoint key at line 430).
- `middleware/rate_limit.py` — `RateLimitMiddleware`; the bucket key:

  ```python
  client_ip = get_client_ip(request)
  endpoint = request.url.path          # line 55 — raw path, unbounded cardinality
  method = request.method
  limit_type = self._get_limit_type(endpoint, method)
  ```

  Fail-closed set: `{"login_attempts", "registration", "password_reset"}`
  (lines 35-39); on any limiter exception those types get a 503 while general
  traffic passes through (lines 104-124). Uses a dedicated committed session
  so >=400 responses don't roll back the counter (comment at lines 89-94 —
  keep this).
  **Important**: this is Starlette `BaseHTTPMiddleware` — it runs BEFORE
  routing, so `request.scope["route"]` is NOT available; route-template
  normalization must be regex-based, not router-based.
- `models/rate_limiting.py` — `RateLimitAttempt`: unique bucket constraint
  `(ip_address, endpoint, limit_type, window_seconds, window_start)`, index
  `ix_rate_limit_cleanup` on `created_at` (line 38).
- `core/settings/rate_limit.py` — existing rate-limit settings mixin (add the
  new retention setting here, following its Field style).
- Sweep-job pattern to copy — `services/jobs/handlers/sweep_terminal_jobs.py`
  (entire shape: `@job_handler(kind=..., timeout=...)` handler that deletes
  past a cutoff then re-enqueues itself via `enqueue_job(..., run_after=now +
  timedelta(seconds=settings.JOBS_SWEEP_INTERVAL_SECONDS))`, plus an
  `ensure_*` function that checks `IN_FLIGHT_JOB_STATUSES` before enqueueing).
  Handlers are registered by import in `services/jobs/handlers/__init__.py`;
  `ensure_sweep_job(db)` / `ensure_files_sweep_job(db)` are called at
  `workers/job_runner.py:47-48`.
- Test conventions: DB-backed tests live under `tests/services/<domain>/` and
  skip without `TEST_DATABASE_URL`; fixtures `db_session`,
  `db_session_factory`, `committed_db_session_factory`, `async_client`,
  `db_async_client` are in `tests/conftest.py`. Middleware test pattern:
  `tests/middleware/test_csrf.py`. Async modules need
  `pytestmark = pytest.mark.asyncio` (unless plan 001's auto mode landed).

## Commands you will need

| Purpose | Command (from `apps/api/`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| New tests | `TEST_DATABASE_URL=<url> uv run pytest tests/services/rate_limiting tests/middleware -q` | all pass |
| Jobs tests | `TEST_DATABASE_URL=<url> uv run pytest tests/services/jobs -q` | all pass |
| Worker smoke | `DATABASE_URL=<url> uv run python -m workers.job_runner --once` | exit 0 |

## Scope

**In scope**:
- `apps/api/core/rate_limiting.py` (add `normalize_endpoint`; use it in `require_rate_limit`)
- `apps/api/middleware/rate_limit.py` (use `normalize_endpoint` for the bucket key)
- `apps/api/core/settings/rate_limit.py` (one retention setting)
- `apps/api/services/jobs/handlers/sweep_rate_limit_attempts.py` (create)
- `apps/api/services/jobs/handlers/__init__.py` (register import)
- `apps/api/workers/job_runner.py` (ensure call, beside lines 47-48)
- `apps/api/tests/services/rate_limiting/` (create)
- `apps/api/tests/middleware/` (add rate-limit middleware test)

**Out of scope**:
- The rate-limit *policy* itself — limits, windows, fail-closed set, and the
  `_get_limit_type` classification logic stay exactly as they are.
  (`_get_limit_type` keeps matching on the RAW path — only the storage bucket
  key is normalized.)
- `get_client_ip` / trusted-proxy logic — audited separately; do not touch.
- Any Redis migration — the docstring mentions an upgrade path; not now.
- Schema changes to `rate_limit_attempts` — the existing indexes suffice.

## Git workflow

- Branch: `advisor/004-rate-limiter-hardening`
- Commit per step; message style e.g. `API - Rate Limit Key Normalization`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Normalize the bucket key

In `core/rate_limiting.py`, add a module-level helper (near `get_client_ip`):

```python
_UUID_SEGMENT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_NUMERIC_SEGMENT = re.compile(r"^\d+$")


def normalize_endpoint(path: str) -> str:
    """Collapse path-parameter segments so rate-limit buckets stay bounded."""
    segments = [
        "{id}" if _UUID_SEGMENT.match(seg) or _NUMERIC_SEGMENT.match(seg) else seg
        for seg in path.split("/")
    ]
    return "/".join(segments)
```

Use it for the **storage key only**:

- `middleware/rate_limit.py` dispatch: keep `endpoint = request.url.path` for
  `_get_limit_type(...)` and for the security-event `endpoint=` detail
  (operators want the real URL there), but pass
  `endpoint=normalize_endpoint(request.url.path)` into
  `rate_limiter.check_rate_limit(...)`.
- `core/rate_limiting.py` `require_rate_limit` dependency (line 430): same —
  normalize what goes into `check_rate_limit`.

**Verify**: `uv run ruff check .` → exit 0, and the unit test from the Test
plan (`normalize_endpoint` cases) passes.

### Step 2: Add the retention sweep job

1. In `core/settings/rate_limit.py`, add (matching the mixin's Field style):

   ```python
   RATE_LIMIT_RETENTION_SECONDS: int = Field(
       default=172800,
       ge=86400,
       description="Age after which rate-limit attempt rows are deleted (min: the longest window, 1 day)",
   )
   ```

   The floor matters: rows must outlive the longest window (86400s) or
   active buckets could be deleted mid-window.

2. Create `services/jobs/handlers/sweep_rate_limit_attempts.py`, copying the
   `sweep_terminal_jobs.py` shape exactly: kind
   `"rate_limits.sweep_attempts"`, a `@job_handler(kind=..., timeout=120.0)`
   handler that runs

   ```python
   delete(RateLimitAttempt).where(
       RateLimitAttempt.created_at < now - timedelta(seconds=settings.RATE_LIMIT_RETENTION_SECONDS)
   )
   ```

   then re-enqueues itself with
   `run_after=now + timedelta(seconds=settings.JOBS_SWEEP_INTERVAL_SECONDS)`,
   plus an `ensure_rate_limit_sweep_job(db)` mirroring `ensure_sweep_job`
   (check `IN_FLIGHT_JOB_STATUSES` first; `content_hash="rate-limit-sweep:ensure"`).

3. Register the module import in `services/jobs/handlers/__init__.py` and add
   `await ensure_rate_limit_sweep_job(db)` beside the two existing ensure
   calls at `workers/job_runner.py:47-48`.

**Verify**: `DATABASE_URL=<url> uv run python -m workers.job_runner --once` →
exit 0, and `TEST_DATABASE_URL=<url> uv run pytest tests/services/jobs -q` →
all pass.

## Test plan

Create `tests/services/rate_limiting/test_rate_limiter.py` (new directory;
DB-backed via the `db_session` fixture; module-level
`pytestmark = pytest.mark.asyncio` unless auto mode landed):

- `normalize_endpoint`: `/api/v1/conversations/9b2f.../messages` →
  `/api/v1/conversations/{id}/messages`; numeric segments collapse; paths
  without params are unchanged. (Pure unit test, no DB.)
- Counter increments: two `check_rate_limit` calls for the same
  ip/endpoint/type in one window → `attempts == 2`, one row.
- Deny at the boundary: with `custom_limit=3, custom_window=60`, the 4th call
  has `allowed is False` and a positive `retry_after`.
- Window rollover: monkeypatch/freeze `datetime.now` (or use
  `custom_window=1` and sleep past it) → counter resets in the next window.
- Invalid IP → most-restrictive: `check_rate_limit(ip="not-an-ip", ...)` →
  `allowed is False`, `limit == 1`.
- Disabled limiter: with `RATE_LIMIT_ENABLED=False` (settings override
  fixture, matching how other tests override settings), everything allowed,
  `limit is None`.
- Sweep: insert one `RateLimitAttempt` with `created_at` older than retention
  and one fresh; run the sweep handler; only the fresh row survives, and a
  follow-up sweep job row exists (mirror the self-reschedule assertions in
  `tests/services/jobs/`).

Add to `tests/middleware/` (model after `test_csrf.py`, driving the app via
the client fixtures):

- Fail-closed: patch `rate_limiter.check_rate_limit` to raise; a POST to a
  login path returns 503; a GET to a general path passes through (200/404 —
  anything but 503).
- Blocked response: patch `check_rate_limit` to return a denied
  `RateLimitResult`; response is 429 with `Retry-After` and
  `X-RateLimit-Limit` headers.

**Verification**: `TEST_DATABASE_URL=<url> uv run pytest tests/services/rate_limiting tests/middleware tests/services/jobs -q` → all pass, ≥9 new tests.

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] `grep -n "normalize_endpoint" apps/api/middleware/rate_limit.py apps/api/core/rate_limiting.py` shows the storage key normalized in both call sites
- [ ] `grep -rn "rate_limits.sweep_attempts" apps/api/services/jobs/handlers/ apps/api/workers/job_runner.py` shows handler + ensure wired
- [ ] `TEST_DATABASE_URL=<url> uv run pytest tests/services/rate_limiting tests/middleware tests/services/jobs -q` exits 0 with the new tests
- [ ] `DATABASE_URL=<url> uv run python -m workers.job_runner --once` exits 0
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/improvements/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `_get_limit_type` turns out to depend on segments that normalization would
  alter for the *storage* key in a way that changes which limit applies —
  it must not; classification stays on the raw path by design here.
- The jobs registry rejects the new kind name pattern
  (`rate_limits.sweep_attempts`) — check the existing kinds
  (`jobs.sweep_terminal`, `files.sweep_deleted`) and match their naming rules.
- Freezing/patching time for the rollover test proves flaky — replace with a
  direct unit test of `_window_start` boundary math instead of skipping it.
- Any existing auth-flow test starts failing (the normalization must be
  invisible to auth paths, which have no path parameters).

## Maintenance notes

- If a Redis limiter ever replaces the Postgres one (the module docstring's
  stated upgrade path), `normalize_endpoint` and the retention policy carry
  over; the sweep job gets deleted.
- New route families with non-UUID, non-numeric path params (e.g. slugs) will
  reintroduce cardinality — a reviewer adding such routes should extend
  `normalize_endpoint`.
- Reviewers should scrutinize: that the raw path still reaches
  `_get_limit_type` and the security event, and that the retention floor
  (≥ longest window) holds if someone later adds a longer window type.
