# Plan C01: Stand up CI and complete the local quality gate

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/improvements/README.md`.
>
> **Drift check (run first)**: `git diff --stat a0eea1c..HEAD -- makefile/checks.mk apps/api/pyproject.toml apps/web/package.json .github`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `a0eea1c`, 2026-07-06
- **Status**: DONE, 2026-07-06

## Why this matters

There is no CI at all (`.github/workflows` does not exist), and the aggregate
local gate skips the backend test suite: `make check` runs lint, migration
check, and the web gate but never `pytest` or `ruff format --check`. Two quiet
amplifiers make regressions even easier to miss: there is no pytest
`asyncio_mode` config, so an async test module missing the `pytestmark`
boilerplate is collected as a never-awaited coroutine and passes as a green
no-op; and the frontend's most complex stateful code — the SSE
parser/reducer stack in `apps/web/src/features/conversations/stream/` — has
zero behavioral tests because no frontend test framework exists. Roughly 19
more implementation plans (`docs/plans/` 033–051) are queued for execution;
this gate protects all of them.

## Current state

- No `.github/` directory exists in the repo root.
- `makefile/checks.mk` (entire file):

  ```makefile
  .PHONY: api-lint
  api-lint: ## Run backend lint checks
  	cd $(API_DIR) && uv run ruff check .

  .PHONY: api-test
  api-test: ## Run backend tests
  	cd $(API_DIR) && uv run pytest

  .PHONY: api-migrations-check
  api-migrations-check: local-env ## Check Alembic migration drift
  	cd $(API_DIR) && $(API_ENV) uv run alembic check

  .PHONY: web-check
  web-check: ## Run the frontend local gate
  	cd $(WEB_DIR) && pnpm check

  .PHONY: check
  check: api-lint api-migrations-check web-check ## Run the main backend and frontend checks
  ```

  Note `api-test` exists but is not part of `check`. Variables come from
  `makefile/config.mk`: `API_DIR := apps/api`, `WEB_DIR := apps/web`,
  `API_ENV := set -a; . ./.env; set +a;`.

- `apps/api/pyproject.toml` has **no** `[tool.pytest.ini_options]` section.
  Dev deps already include `pytest>=8.0.0` and `pytest-asyncio>=0.24.0`.
- Async test modules currently carry `pytestmark = pytest.mark.asyncio` by
  convention (see any file under `apps/api/tests/services/`). DB-backed tests
  skip cleanly unless `TEST_DATABASE_URL` is set (fixtures in
  `apps/api/tests/conftest.py`: `test_database_url` at line 86 reads the env
  var, `migrated_test_database` at line 92 migrates it).
- `apps/web/package.json` scripts:

  ```json
  "check": "pnpm typecheck && pnpm lint && pnpm format:check && pnpm deadcode && pnpm arch && pnpm build",
  ```

  No test runner is installed (no vitest/jest anywhere in devDependencies).
- The SSE stream module to be tested:
  `apps/web/src/features/conversations/stream/` contains `sse.ts` (hand-written
  SSE parser that throws on unknown event names — deliberate), `protocol.ts`
  (typed versioned event protocol), `reducer.ts` (stream state reducer),
  `query-cache.ts`, `use-agent-stream.ts`. Read `sse.ts`, `protocol.ts`, and
  `reducer.ts` fully before writing tests.
- Local Postgres image used by the repo: `pgvector/pgvector:pg17`
  (`docker-compose.yml:15`). Node version used by the web Docker image is 24
  (`apps/web/Dockerfile`), pnpm is pinned via `"packageManager": "pnpm@10.12.2"`.
- Alembic has two branch heads (`core`, `app`); the upgrade command is
  `uv run alembic upgrade heads` (plural) and drift check is
  `uv run alembic check` (needs `DATABASE_URL` pointing at a migrated DB).

## Commands you will need

| Purpose | Command (run from repo root unless noted) | Expected on success |
|---------|-------------------------------------------|---------------------|
| Backend lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Backend format check | `cd apps/api && uv run ruff format --check .` | exit 0 |
| Backend tests | `cd apps/api && uv run pytest` | exit 0 (DB tests skip without `TEST_DATABASE_URL`) |
| Migrations | `cd apps/api && uv run alembic upgrade heads && uv run alembic check` | exit 0 (needs `DATABASE_URL`) |
| Web gate | `cd apps/web && pnpm check` | exit 0 |
| Full gate | `make check` | exit 0 |

## Scope

**In scope** (the only files you should create or modify):
- `.github/workflows/ci.yml` (create)
- `makefile/checks.mk`
- `apps/api/pyproject.toml` (pytest config section only)
- `apps/api/tests/**` (only if enabling `asyncio_mode = "auto"` surfaces
  previously-skipped tests that need trivial fixes; see STOP conditions)
- `apps/web/package.json`, `apps/web/pnpm-lock.yaml` (vitest dev dep + scripts)
- `apps/web/vitest.config.ts` (create)
- `apps/web/src/features/conversations/stream/*.test.ts` (create)
- `apps/web/knip.json` or knip config in `package.json` / `apps/web/eslint.config.js` — only if `pnpm deadcode` or `pnpm lint` flags the new test files/config, and only to register them, not to weaken rules

**Out of scope** (do NOT touch):
- Any Python type-checker adoption (mypy/pyright) — deferred, tracked in the index.
- Any deploy/build-push CI jobs — a separate decision (see plan 005 maintenance notes).
- `apps/web/src/features/conversations/stream/*.ts` source files — tests only; if a test reveals a bug, STOP and report it instead of fixing stream code in this plan.
- `.dependency-cruiser.cjs` rules.

## Git workflow

- Branch: `advisor/001-ci-and-quality-gate`
- Commit per step; message style matches `git log` (e.g. `Cross - CI & Quality Gate`, `API - Pytest Asyncio Mode`, `Web - Stream Unit Tests`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Enable pytest asyncio auto mode

Add to `apps/api/pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Do NOT remove existing `pytestmark = pytest.mark.asyncio` lines in this plan
(they are harmless under auto mode; removing them across ~70 files is noise —
note it as follow-up).

**Verify**: `cd apps/api && uv run pytest` → exit 0. Compare the collected
test count before and after the change (`uv run pytest --collect-only -q | tail -1`).
If the count rises, previously-silent tests are now running — they must pass.
Then run the DB-backed suite if a local Postgres is available:
`TEST_DATABASE_URL=<local test db url> uv run pytest` → exit 0.

### Step 2: Complete `make check`

Edit `makefile/checks.mk`:

1. Add a format-check target:

   ```makefile
   .PHONY: api-format-check
   api-format-check: ## Check backend formatting
   	cd $(API_DIR) && uv run ruff format --check .
   ```

2. Change the aggregate target to:

   ```makefile
   check: api-lint api-format-check api-migrations-check api-test web-check ## Run the main backend and frontend checks
   ```

**Verify**: `make check` from the repo root → exit 0. If
`api-format-check` fails on existing files, run
`cd apps/api && uv run ruff format .` in a separate commit first (formatting
only, no logic changes), then re-run.

### Step 3: Add Vitest and unit tests for the SSE stream module

1. `cd apps/web && pnpm add -D vitest`
2. Create `apps/web/vitest.config.ts`:

   ```ts
   import { defineConfig } from "vitest/config";

   export default defineConfig({
     test: {
       include: ["src/**/*.test.ts"],
       environment: "node",
     },
   });
   ```

3. Add scripts to `apps/web/package.json`: `"test": "vitest run"`, and insert
   `pnpm test` into the `check` chain after `pnpm lint`.
4. Read `src/features/conversations/stream/sse.ts`, `protocol.ts`, and
   `reducer.ts` fully. Write:
   - `src/features/conversations/stream/sse.test.ts` — parser cases: a single
     complete event; one event split across multiple chunks; multiple events
     in one chunk; CRLF vs LF separators if the parser handles both; keepalive/
     comment frames; and an **unknown event name throws** (this is documented
     intended behavior — assert the throw, do not "fix" it).
   - `src/features/conversations/stream/reducer.test.ts` — reducer transitions
     driven by protocol-shaped fixture events: stream start resets state;
     message/token accumulation; tool call + tool result pairing; approval-
     required state; terminal/error states. Derive fixture payloads from the
     types in `protocol.ts` so the compiler validates them.
5. If `pnpm deadcode` (knip) flags `vitest.config.ts` or the test files,
   register them in the knip config as entry/ignore patterns; if eslint flags
   them, extend the lint config's file globs. Do not disable rules.

**Verify**: `cd apps/web && pnpm test` → all tests pass; then `pnpm check` →
exit 0.

### Step 4: Create the CI workflow

Create `.github/workflows/ci.yml` with two jobs:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  api:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/api
    services:
      postgres:
        image: pgvector/pgvector:pg17
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: praxis
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/praxis
      TEST_DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run alembic upgrade heads
      - run: uv run alembic check
      - run: >
          PGPASSWORD=postgres psql -h localhost -U postgres
          -c 'CREATE DATABASE praxis_test'
      - run: uv run pytest

  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/web
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
          cache-dependency-path: apps/web/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm check
```

Adjust the two DSN scheme strings to match what `apps/api/core/settings/database.py`
and `apps/api/tests/conftest.py` actually expect (check whether they want
`postgresql+asyncpg://` or plain `postgresql://` before committing —
`alembic/env.py` and the `migrated_test_database` fixture are the sources of
truth). Also confirm whether app settings require more mandatory env vars to
boot for `alembic upgrade` (read `apps/api/.env.example`; add the minimal safe
values as workflow `env`, never real secrets).

**Verify**: `git push` the branch (only if the operator allows pushing) and
confirm both jobs green in the Actions tab; otherwise validate locally with
`act` if available, or at minimum run every command in the workflow locally in
order → all exit 0.

## Test plan

- Step 1's verification (collected-count comparison) is the test that auto
  mode did not silently change suite behavior.
- New frontend tests: `sse.test.ts` (≥5 cases incl. the unknown-event throw)
  and `reducer.test.ts` (≥5 transition cases). No existing frontend test file
  exists to model after; follow the structure in this plan.
- `make check` and the CI workflow are themselves the deliverable-level tests.

## Done criteria

- [x] `make check` exits 0 and its recipe includes `api-test` and `api-format-check`
- [x] `apps/api/pyproject.toml` contains `asyncio_mode = "auto"`
- [x] `cd apps/web && pnpm test` exits 0 with new stream tests
- [x] `cd apps/web && pnpm check` exits 0 (test step included in the chain)
- [x] `.github/workflows/ci.yml` exists; every command in it has been run successfully locally
- [x] `git status` shows no modified files outside the in-scope list except the Step 2 required Ruff formatting-only API pass
- [x] `plans/improvements/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Enabling `asyncio_mode = "auto"` causes test failures that are not trivially
  explained as "this test was silently skipped before" — that is a real,
  previously-hidden bug and needs its own review.
- A stream test reveals a genuine parser/reducer bug — report it; source fixes
  are out of scope here.
- `alembic upgrade heads` in CI needs settings/env values you cannot supply
  without inventing secrets.
- knip/eslint cannot be satisfied by registering the new files and would
  require weakening a rule.

## Maintenance notes

- Plan C04 (rate limiter) and C02 (files vertical) have landed; their tests
  run under this gate automatically, with no CI change needed.
- Follow-up (deferred): remove now-redundant `pytestmark = pytest.mark.asyncio`
  lines; adopt a Python type checker (pyright/mypy) as a ratcheted CI step;
  extend CI with image build/push once a deploy target is decided (see plan
  005 maintenance notes).
- Reviewers should scrutinize: the collected-test-count delta from Step 1, and
  that the CI Postgres DSNs match the settings module rather than being
  copy-pasted.
