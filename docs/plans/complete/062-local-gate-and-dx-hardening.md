# Plan 062: Make the local quality gate trustworthy and fix daily-loop DX friction

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat d326b68..HEAD -- makefiles/ .github/workflows/ci.yml AGENTS.md apps/api/tests/support/database.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `d326b68`, 2026-07-07

## Why this matters

`make check` is the documented pre-push gate, but running it today produces a
**false green**: `api-test` invokes `pytest` without `TEST_DATABASE_URL`, and
every database-backed test module (roughly 57 of 84 — auth, workspaces,
approvals, schedules, files) silently `pytest.skip`s instead of running. CI
sets the variable, so regressions surface only after a push. Separately,
AGENTS.md — the steering document every coding agent reads — makes two claims
that are now false, the CI API job re-downloads its whole virtualenv on every
run, and the worker has no reload story while the API does. All of these are
small fixes with outsized daily payoff.

## Current state

- `makefiles/checks.mk:9-11` — the test target sets no database URL:

  ```make
  .PHONY: api-test
  api-test: ## Run backend tests
  	cd $(API_DIR) && uv run pytest
  ```

- `apps/api/tests/support/database.py:13-17` — the skip mechanism:

  ```python
  def require_test_database_url() -> str:
      """Return the configured PostgreSQL test database URL or skip the test."""
      database_url = os.getenv(TEST_DATABASE_URL_ENV_VAR)
      if not database_url:
          pytest.skip(f"Set {TEST_DATABASE_URL_ENV_VAR} to run database-backed API tests")
  ```

- `.github/workflows/ci.yml` sets
  `TEST_DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test`
  and creates the `praxis_test` database with an inline asyncpg script before
  running `uv run --locked pytest`. Local Postgres (docker-compose service
  `postgres`, image `pgvector/pgvector:pg17`) uses user/password/db
  `postgres`/`postgres`/`postgres` on `localhost:5432`; `makefiles/local.mk`
  already has `db-up` and `db-wait` targets that start it and wait for
  readiness, and `$(COMPOSE)` is the compose wrapper variable used throughout
  `makefiles/`.
- `.github/workflows/ci.yml:39-42` (api job) — uv is set up without caching,
  while the web job caches pnpm:

  ```yaml
  - uses: astral-sh/setup-uv@v8.2.0
    with:
      python-version: "3.12"
  ```

- `makefiles/local.mk:77-79` — the worker dev target has no reload, unlike
  `api-dev` which passes `--reload` to uvicorn:

  ```make
  .PHONY: worker-dev
  worker-dev: local-env ## Run the scheduled agent runner
  	cd $(API_DIR) && uv run python -m workers.main
  ```

- `AGENTS.md` contains two stale claims:
  - Line ~131: "There is no pytest config file and no `asyncio_mode`; async
    test modules must set `pytestmark = pytest.mark.asyncio` or they will not
    run." — false since CI/quality plan C01: `apps/api/pyproject.toml:41` sets
    `asyncio_mode = "auto"`.
  - Line ~229: "There is no frontend test framework; the quality gate is
    static." — false: `apps/web/package.json` has `"test": "vitest run"`
    wired into `pnpm check`, and tests exist under
    `apps/web/src/features/conversations/stream/`.
- There is no `.editorconfig` anywhere in the repo (polyglot monorepo: Python
  4-space via ruff, TS 2-space via prettier).

## Commands you will need

| Purpose | Command (from repo root unless noted) | Expected on success |
|---------|----------------------------------------|---------------------|
| Start local Postgres | `make db-up && make db-wait` | "Postgres is ready" |
| Backend tests (manual) | `cd apps/api && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run pytest` | exit 0 |
| Full gate | `make check` | exit 0 |
| Backend lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `makefiles/checks.mk`
- `makefiles/local.mk` (worker-dev target, new test-db target if placed here)
- `.github/workflows/ci.yml` (uv cache lines only)
- `.editorconfig` (create)
- `AGENTS.md` (the two stale claims only)
- `apps/api/pyproject.toml` (only if `watchfiles` must be added as a dev dependency)

**Out of scope** (do NOT touch, even though they look related):

- `apps/api/tests/support/database.py` — keep the skip behavior; tests must
  still skip cleanly for contributors without Docker.
- Any pre-commit hook setup — deliberately deferred (maintainer preference).
- `docker-compose.yml` — no service changes needed.
- The pytest suite itself.

## Git workflow

- Work directly on `main` unless the operator says otherwise (repo convention).
- Commit message style matches `git log`: `Cross - Local Gate & DX Hardening`
  (prefix `API -`, `Web -`, `Cross -`, or `Docs -` by area).
- Do NOT push unless the operator instructed it.

## Steps

### Step 1: Provision the test database in the make flow

In `makefiles/local.mk`, add a target that ensures Postgres is up and the
`praxis_test` database exists (idempotent):

```make
.PHONY: test-db
test-db: db-up db-wait ## Ensure the praxis_test database exists
	@$(COMPOSE) exec -T postgres psql -U postgres -tAc \
		"SELECT 1 FROM pg_database WHERE datname = 'praxis_test'" | grep -q 1 || \
		$(COMPOSE) exec -T postgres createdb -U postgres praxis_test
```

In `makefiles/checks.mk`, make `api-test` depend on it and export the URL:

```make
.PHONY: api-test
api-test: test-db ## Run backend tests against the local test database
	cd $(API_DIR) && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run pytest
```

Note `$(API_DIR)` and `$(COMPOSE)` are defined in the makefile config; reuse
them, do not hardcode paths.

**Verify**: `make api-test` → pytest runs; the summary line must NOT show a
large skip count with reason "Set TEST_DATABASE_URL". Compare against
`cd apps/api && uv run pytest` (no env), which skips those modules. A handful
of unrelated skips is acceptable; the DB-URL skip reason must be gone.

### Step 2: Cache uv in CI

In `.github/workflows/ci.yml`, extend the setup-uv step in the `api` job:

```yaml
  - uses: astral-sh/setup-uv@v8.2.0
    with:
      python-version: "3.12"
      enable-cache: true
      cache-dependency-glob: apps/api/uv.lock
```

**Verify**: `uvx yamllint .github/workflows/ci.yml` exits 0 (or, if yamllint
is unavailable, `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())"` from `apps/api` via `uv run`).

### Step 3: Add a root `.editorconfig`

Create `.editorconfig` at the repo root:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.py]
indent_style = space
indent_size = 4

[*.{ts,tsx,js,cjs,mjs,json,css,html,yml,yaml}]
indent_style = space
indent_size = 2

[{Makefile,makefile,*.mk,*.makefile}]
indent_style = tab

[*.md]
trim_trailing_whitespace = false
```

**Verify**: file exists; `make check` still exits 0 (prettier/ruff settings
already agree with these values, so no reformatting should occur —
`git status` shows only the intended new/changed files).

### Step 4: Give the worker a reload loop

First check whether `watchfiles` is already importable (it ships with
uvicorn's standard extras): `cd apps/api && uv run python -c "import watchfiles"`.
If it fails, add `watchfiles` to the dev dependency group in
`apps/api/pyproject.toml` and run `uv sync`.

Then change `worker-dev` in `makefiles/local.mk`:

```make
.PHONY: worker-dev
worker-dev: local-env ## Run the scheduled agent runner with auto-reload
	cd $(API_DIR) && uv run watchfiles "python -m workers.main" workers services models core utils
```

**Verify**: `make worker-dev` starts and logs a watchfiles banner; touching
`apps/api/workers/main.py` (e.g. `touch`) triggers a restart in the log output.
Ctrl-C to stop. If the environment cannot run Docker/Postgres for a live
check, verify at minimum that `uv run watchfiles --help` exits 0 and the
target's syntax passes `make -n worker-dev`.

### Step 5: Correct the two stale AGENTS.md claims

- Replace the sentence "There is no pytest config file and no `asyncio_mode`;
  async test modules must set `pytestmark = pytest.mark.asyncio` or they will
  not run." with wording that reflects reality: pytest is configured in
  `apps/api/pyproject.toml` with `asyncio_mode = "auto"`, so async test
  functions run without markers.
- Replace "There is no frontend test framework; the quality gate is static."
  with wording that reflects reality: Vitest is installed, `pnpm test` runs in
  `pnpm check` and CI, and unit tests live next to their modules
  (e.g. `src/features/conversations/stream/reducer.test.ts`); the rest of the
  gate is static analysis.
- While there, update the AGENTS.md "Tests" bullet that describes
  `TEST_DATABASE_URL` skipping to mention that `make api-test` now provisions
  the test database automatically.

**Verify**: `grep -n "no frontend test framework\|no pytest config" AGENTS.md`
returns no matches.

## Test plan

No new test files. The verification is behavioral:

- `make api-test` runs the DB-backed suite (Step 1 verify).
- `make check` exits 0 end to end.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make api-test` runs without any "Set TEST_DATABASE_URL" skips
- [ ] `make check` exits 0
- [ ] `.github/workflows/ci.yml` contains `enable-cache: true` in the api job
- [ ] `.editorconfig` exists at repo root
- [ ] `grep -rn "pytestmark = pytest.mark.asyncio.*or they will not run" AGENTS.md` returns nothing; the frontend-test claim is corrected
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] Status row updated in `docs/plans/000_README.md`

## STOP conditions

Stop and report back (do not improvise) if:

- The compose service name is not `postgres` or `$(COMPOSE)` is not defined in
  the makefiles (config drift).
- `make api-test` fails on real test failures (not skips) — the DB-backed
  suite may be red locally for reasons this plan must not paper over; report
  the failures instead of "fixing" tests.
- Adding `watchfiles` pulls in dependency resolution conflicts.
- AGENTS.md has been restructured such that the quoted sentences no longer
  exist.

## Maintenance notes

- Anyone adding CI env vars for tests must mirror them into the `api-test`
  make target (or a shared env file) to keep local == CI.
- Pre-commit hooks were considered and deferred — a maintainer decision, since
  they change contributor workflow. Revisit if formatting-only CI failures
  keep occurring.
- Do not reference this plan number in code or commit-adjacent comments
  (AGENTS.md rule); describe behavior instead.
