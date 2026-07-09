# Plan C05: Close the small production-readiness gaps (license, metrics, 403 bodies, README)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/improvements/README.md`.
>
> **Drift check (run first)**: `git diff --stat a0eea1c..HEAD -- apps/api/core/observability.py apps/api/core/exceptions/auth.py apps/api/main.py apps/api/core/settings README.md LICENSE`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs / security / tech-debt
- **Planned at**: commit `a0eea1c`, 2026-07-06
- **Completed**: 2026-07-09

## Completion notes

- Apache-2.0 `LICENSE` already existed in the live tree and the README license
  note now points to it.
- `/api/metrics` is settings-gated, token-protected outside disabled mode, and
  excluded from OpenAPI.
- Authorization problem details keep `allowed_roles` visible while filtering
  internal membership, user, and workspace identifiers at the exception
  boundary.
- README local-development copy now points to `make bootstrap` / `make dev` as
  the supported flow and lists Node.js 24.

## Why this matters

Four small, independent gaps undermine "open source, production-grade":
(1) there is **no LICENSE file**, so the legal default is all-rights-reserved
— which blocks the project's stated open-source goal outright; (2) Prometheus
metrics are recorded on every request but no `/metrics` endpoint exists, so
`prometheus-client` is shipped dead weight and any dashboard has no data
source; (3) 403 error bodies leak internal identifiers (`membership_id`,
`user_id`, `workspace_id`) to clients; (4) the README — the front door —
gives the wrong Node version, contains typos in its opening paragraph, and
steers contributors away from the now-working `make dev` flow.

## Current state

- **License**: no `LICENSE*` file exists at the repo root. The README itself
  says: "No license file has been committed yet. Add one before treating this
  repository as ready for public redistribution."
- **Metrics**: `apps/api/core/observability.py` (27 lines) defines
  `REQUEST_COUNT`, `REQUEST_DURATION`, `track_request(...)` (called per
  request from `apps/api/middleware/request_logging.py`), and:

  ```python
  def get_metrics() -> bytes:
      """Get current metrics in Prometheus format for the /metrics endpoint."""
      return generate_latest()
  ```

  `get_metrics` has zero callers — no `/metrics` route anywhere. Notably,
  `middleware/rate_limit.py:31-34` already excludes `"/api/metrics"` from
  rate limiting, which is the intended path. Routers: versioned API routes
  compose in `apps/api/routes/__init__.py` under `settings.API_V1_PREFIX`;
  `apps/api/main.py:115` does `app.include_router(api_router)`. A
  non-versioned operational endpoint belongs beside the health route in
  `main.py`, not in the v1 router (find the existing `/api/health` handler in
  `main.py` and place `/api/metrics` next to it).
- **403 bodies**: `apps/api/core/exceptions/auth.py` `AuthorizationError.
  to_problem_details` spreads `self.details` into the RFC 7807 body
  (filtering only `_PROBLEM_RESERVED_KEYS`). Raise sites pass internal IDs —
  e.g. `apps/api/services/files/utils.py:58-70`:

  ```python
  raise AuthorizationError(
      "Requires workspace write access",
      details={
          "allowed_roles": sorted(EDITOR_ROLES),
          "membership_id": str(membership.id),
          "membership_role": membership.role,
          "workspace_id": str(membership.workspace_id),
          "user_id": str(membership.user_id),
      },
  )
  ```

  The same pattern exists in `services/agents/utils.py`,
  `services/workspaces/**`, `services/skills/utils.py` (11 files raise
  `AuthorizationError` with details). The values belong to the caller (not a
  cross-tenant leak), but internal surrogate keys don't belong in client
  bodies. The frontend never reads them
  (`grep -rn "membership_id" apps/web/src` → no matches).
- **README** (`README.md`): line 6 has "The focus i on practical agent
  workflows" (missing "s") and "approvals, auditability notifications,
  schedules" (missing separator); line 65 says "Node.js 22" but
  `apps/web/Dockerfile` uses `node:24-slim` and `@types/node` is `^24`;
  lines 17 and 221 still say the Docker setup "is still being normalized …
  prefer the manual backend and frontend commands", contradicting the
  current Compose-based `make dev` flow (`Makefile` + `makefiles/local.mk`).
- Settings conventions: per-concern mixins under `apps/api/core/settings/`
  (e.g. `rate_limit.py`, `security.py`); the `model_validator` in
  `core/settings/__init__.py` rejects unsafe production combinations — read
  it before adding validation and match its style.

## Commands you will need

| Purpose | Command (from `apps/api/` unless noted) | Expected on success |
|---------|----------------------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Tests | `uv run pytest tests/middleware tests/contract -q` (plus `TEST_DATABASE_URL` variants if touched areas have DB tests) | all pass |
| Full gate | `make check` (repo root) | exit 0 |

## Scope

**In scope**:
- `LICENSE` (create, repo root)
- `README.md` (the specific corrections listed; nothing else)
- `apps/api/main.py` (one route)
- `apps/api/core/settings/` (metrics settings — put them in the settings
  mixin that best fits; `app.py` or a new small mixin following the existing
  pattern; plus the production validator in `__init__.py`)
- `apps/api/core/exceptions/auth.py`
- `apps/api/tests/**` (tests for the new route and the 403 body shape)

**Out of scope**:
- The 11 `AuthorizationError` raise **sites** — do NOT edit them. The fix is
  one filter at the choke point (`to_problem_details`); the rich details keep
  flowing to server-side logs/handlers.
- CI deploy/build-push jobs, image publishing, hosting decisions — recorded
  as a follow-up decision in Maintenance notes, deliberately not in scope.
- The OTel work (`docs/plans/014-*.md`) — the metrics route must not
  preempt or duplicate it; this is only exposing what is already collected.
- `middleware/request_logging.py` and what gets tracked.

## Git workflow

- Branch: `advisor/005-production-readiness-gaps`
- Commit per step; message style e.g. `API - Metrics Endpoint`, `Docs - README Fixes`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the license (maintainer decision required)

Ask the operator which license to use before writing anything. If this plan
is being executed non-interactively and no license was specified in your
dispatch instructions, SKIP this step and mark it BLOCKED in the index —
do not choose a license yourself. (Advisor recommendation for the
maintainer: Apache-2.0 — permissive with an explicit patent grant, the common
choice for infrastructure projects; MIT if minimalism is preferred.)

Once specified: add the standard `LICENSE` file verbatim from the official
text, and remove/replace the README closing note that says no license has
been committed.

**Verify**: `test -s LICENSE && head -3 LICENSE` → shows the chosen license
header.

### Step 2: Expose `/api/metrics`, gated by settings

1. Add settings (following the existing mixin style):

   ```python
   METRICS_ENABLED: bool = Field(default=False, description="Expose /api/metrics")
   METRICS_TOKEN: str | None = Field(default=None, description="Bearer token required by /api/metrics")
   ```

2. In `core/settings/__init__.py`'s production `model_validator`, reject
   `METRICS_ENABLED=True` with no `METRICS_TOKEN` outside local/dev
   environments — match exactly how the validator expresses its existing
   local-only rejections.

3. In `apps/api/main.py`, next to the existing health route, add:

   ```python
   @app.get("/api/metrics", include_in_schema=False)
   async def metrics(request: Request) -> Response:
       if not settings.METRICS_ENABLED:
           raise NotFoundError("Not found")
       if settings.METRICS_TOKEN:
           auth = request.headers.get("Authorization", "")
           if not secrets.compare_digest(auth, f"Bearer {settings.METRICS_TOKEN}"):
               raise AuthenticationError("Invalid metrics credentials")
       return Response(content=get_metrics(), media_type=CONTENT_TYPE_LATEST)
   ```

   Import `get_metrics` from `core.observability`, `CONTENT_TYPE_LATEST` from
   `prometheus_client`, `secrets` from stdlib, and the exception types from
   `core.exceptions` (the repo forbids ad-hoc `HTTPException`). Read the
   middleware-ordering comment in `main.py` first — adding a route does not
   reorder middleware, but confirm the route sits outside any auth
   dependencies (metrics scrapers have no session).

**Verify**:
`uv run uvicorn main:app --port 8001` with `METRICS_ENABLED=true` env, then
`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/api/metrics` →
`200` (and `404` when the flag is off; `401`/`403` problem response when a
token is set and absent). Then the automated tests in the Test plan.

### Step 3: Stop leaking internal IDs in 403 bodies

In `core/exceptions/auth.py`, add a module-level constant and filter it in
`AuthorizationError.to_problem_details` (leave `AuthenticationError` alone —
its callers don't pass internal IDs; verify with a quick grep and extend the
filter to it only if they do):

```python
_INTERNAL_DETAIL_KEYS = {"membership_id", "user_id", "workspace_id", "membership_role"}
```

```python
problem.update(
    {
        k: v
        for k, v in self.details.items()
        if k not in _PROBLEM_RESERVED_KEYS and k not in _INTERNAL_DETAIL_KEYS
    }
)
```

`allowed_roles` stays client-visible (it is genuinely useful to callers).
The full `details` dict remains on the exception object for server-side
logging.

**Verify**: `uv run ruff check .` → exit 0; the new body-shape test passes.

### Step 4: Fix the README front door

In `README.md` only:

1. Line 6: "The focus i on" → "The focus is on"; "approvals, auditability
   notifications, schedules" → "approvals, auditability, notifications,
   schedules".
2. Line 65 (prerequisites): "Node.js 22" → "Node.js 24".
3. Lines 17 and 221: rewrite the two "Docker setup is still being
   normalized… prefer the manual commands" passages to reflect reality:
   `make bootstrap` + `make dev` is the supported local flow (Compose runs
   Postgres; see `makefiles/local.mk`), with the manual per-app commands as
   the alternative. Keep the edits surgical — do not restructure the README.
4. If Step 1 ran: update the license note; if Step 1 was skipped/BLOCKED,
   leave the license note in place.

**Verify**: `grep -n "focus i \|Node.js 22\|still being normalized" README.md`
→ no matches.

## Test plan

- New route tests (place under `tests/routes/` or beside the health-route
  tests if any exist — search `grep -rn "api/health" apps/api/tests` and
  co-locate): metrics 404 when disabled; 200 with Prometheus content type
  when enabled (settings override fixture); 401/403 when a token is
  configured and the header is wrong. Use the `async_client` fixture from
  `tests/conftest.py`.
- 403 body shape test (put beside existing exception/contract tests — see
  `tests/contract/` and `tests/middleware/test_csrf.py` for patterns): raise
  path via any RBAC-gated route or directly unit-test
  `AuthorizationError(..., details={...}).to_problem_details()` → result
  contains `allowed_roles` but none of `membership_id`, `user_id`,
  `workspace_id`, `membership_role`.
- Settings validator test if the existing validator has tests (search
  `grep -rn "model_validator\|unsafe" apps/api/tests` and extend the same
  file): production env + `METRICS_ENABLED=True` + no token → rejected.

**Verification**: `uv run pytest tests -q` (with `TEST_DATABASE_URL` if
available) → all pass including the new tests.

## Done criteria

- [x] `LICENSE` exists (or the step is explicitly marked BLOCKED in the index awaiting the maintainer's choice)
- [x] `curl` checks in Step 2 behave as specified, and the route tests pass
- [x] Unit test proves 403 bodies exclude `membership_id`/`user_id`/`workspace_id`/`membership_role` and include `allowed_roles`
- [x] `grep -n "focus i \|Node.js 22\|still being normalized" README.md` → no matches
- [x] `uv run ruff check .` exits 0; `make check` exits 0
- [x] `git status` shows no modified files outside the in-scope list
- [x] `plans/improvements/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- No license was specified and you cannot ask — mark Step 1 BLOCKED, finish
  the rest, and say so in your report.
- Any client/test turns out to depend on the internal keys in 403 bodies
  (a failing existing test on Step 3 means exactly that).
- The settings production validator's structure makes the METRICS rule
  awkward to express in its existing style — report rather than restructuring
  the validator.
- `main.py`'s middleware-ordering comment implies the new route would be
  affected in a way you did not expect (e.g. body-size or auth middleware
  interactions).

## Maintenance notes

- **Deferred decision (deliberately not in this plan)**: the commit → image →
  deploy pipeline. The Dockerfiles are production-shaped (Cloud Run-ready API,
  unprivileged nginx web) but nothing builds/pushes/deploys them, and no
  hosting target is decided. When decided, extend plan 001's CI with
  build/push + deploy jobs, and pair with a backup/restore (PITR) runbook —
  Postgres holds the audit trail the product's governance story depends on.
- The `/api/metrics` route intersects the planned OTel work
  (`docs/plans/014-*.md`): if OTel later exports metrics, decide whether
  Prometheus scraping stays or the collector becomes the single pipe — don't
  run both silently.
- Reviewers should scrutinize: `compare_digest` usage (constant-time compare
  against the full header), and that `/api/metrics` never appears in the
  OpenAPI schema.
