# Plan 063: Put a behavioral test net under the web's pure logic and the internal-token auth path

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat d326b68..HEAD -- apps/web/src/features/conversations/message-parts/ apps/web/src/features/agents/components/agent-form-model.ts apps/web/src/features/schedules/components/schedule-form-model.ts apps/web/src/features/conversations/approval-decisions.ts apps/web/src/lib/format.ts apps/api/core/dependencies.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (additive test files only)
- **Depends on**: 062 (for `make api-test`; soft — `TEST_DATABASE_URL` can be exported manually)
- **Category**: tests
- **Planned at**: commit `d326b68`, 2026-07-07

## Why this matters

Vitest is installed, wired into `pnpm check`, and gates CI — but only two test
files exist (`stream/reducer.test.ts`, `stream/sse.test.ts`). Meanwhile
~3–4k lines of pure, deterministic, high-churn logic have no behavioral
coverage: the message-parts parser that feeds the entire conversation render,
the agent and schedule form models (validation + payload serialization), the
approval-decision state helpers, and the shared formatters. TypeScript catches
shape changes, not behavior changes; refactors here currently ship regressions
that only manual clicking finds. This plan must land **before** the web
scaffolding consolidation (the next plan renumbers/moves exactly these form
models), so the refactor lands against a green behavioral baseline.

On the backend, one auth branch has zero coverage: the internal JWT session
token path in `core/dependencies.py` that pins scheduled-run tokens to a
workspace. It is the isolation boundary that would stop a scheduled agent's
token from acting against another workspace. A discovered fact the executor
must know: **no code in the repo currently mints these tokens** (`jwt.encode`
appears only in `services/auth/oauth/utils.py` and `services/assets/tokens.py`;
the worker executes runs in-process). The validator is a live acceptance path
on every request, so its rejection branches must be pinned by tests either
way; whether to keep or remove the path is a maintainer decision recorded as a
follow-up, not made here.

## Current state

### Frontend

- Test runner: Vitest 4 (`apps/web/package.json` → `"test": "vitest run"`,
  part of `pnpm check`). Config: `apps/web/vitest.config.ts`.
- Pattern exemplar: `apps/web/src/features/conversations/stream/reducer.test.ts`
  — plain `describe`/`it`/`expect` from `vitest`, literal fixture objects for
  API types, no DOM/react testing library (do not add one):

  ```ts
  import { describe, expect, it } from "vitest"
  import type { StreamEvent } from "@/features/conversations/stream/protocol"
  import { agentStreamReducer, initialAgentStreamState, ... } from "@/features/conversations/stream/reducer"
  ```

- Untested pure modules this plan covers (all export plain functions):
  - `src/features/conversations/message-parts/parse.ts` (429 lines) — single
    export `parseConversationMessages(...)`; siblings in the same package:
    `pair-tool-results.ts`, `delegation.ts`, `group-render-items.ts`,
    `pending-messages.ts` (exports via `message-parts/index.ts`).
  - `src/features/agents/components/agent-form-model.ts` (445 lines) — exports
    `initialAgentFormState`, `validateAgentFormState`, `buildAgentPayload`
    (returns `Payload | string`, string = form-level error),
    `isAgentFormDirty`, `buildModelOptions`.
  - `src/features/schedules/components/schedule-form-model.ts` (409 lines) —
    exported state/validate/build functions plus a private hand-rolled
    timezone round-trip (`toIsoDateTimeInTimeZone` at lines 266–299, DST-aware
    fixed-point iteration). Test the private tz logic **through the exported
    payload builders** with datetime+timezone inputs; do not export helpers
    just for tests (knip flags unused exports).
  - `src/features/conversations/approval-decisions.ts` (122 lines) — exports
    `approveDecision`, `denyDecision`, `DEFAULT_APPROVAL_DECISION`, summary
    helpers.
  - `src/lib/format.ts` (91 lines) — `formatDateTime`, `formatBytes`,
    `formatTime`, `pluralize`, `titleCaseToken`, `titleFromSegment`,
    `initials`, `normalize`, `normalizeOptionalText`, `truncateForPreview`.

### Backend

- `apps/api/core/dependencies.py` — `SessionAuth._validate_jwt_session_token`
  accepts an HS256 JWT with `type == "user_session_token"`, `jti`,
  `internal: True`, `user_id`, `workspace_id`, optional `schedule_run_id`.
  Rejection branches (each returns `None` → request is unauthenticated):

  ```python
  if payload.get("type") != "user_session_token": return None
  if not payload.get("jti") or payload.get("internal") is not True: return None
  ...
  if (
      schedule_run is None
      or schedule_run.deleted
      or schedule_run.workspace_id != internal_workspace_id
      or schedule_run.user_id != user_id
  ):
      return None
  ```

  and `_enforce_internal_token_workspace(user, workspace)` raises
  `AuthorizationError` when the resolved `X-Workspace` workspace differs from
  the token's pinned workspace. A grep of `apps/api/tests/` for
  `internal_token` / `_enforce_internal_token` returns nothing.
- Test conventions: async tests run without markers
  (`asyncio_mode = "auto"` in `apps/api/pyproject.toml`); DB-backed tests call
  helpers from `tests/support/database.py` and skip without
  `TEST_DATABASE_URL`; factories live in `tests/factories/`
  (`users.py`, `workspaces.py`, `sessions.py`, …), request/auth helpers in
  `tests/support/auth.py` and `tests/support/requests.py`. Route tests live
  under `tests/routes/<domain>/`; an existing exemplar directory is
  `tests/routes/auth/`.
- Token forging in tests: sign with
  `settings.SECRET_KEY.get_secret_value()` and `algorithm="HS256"` via the
  same `jwt` import used in `core/dependencies.py` (PyJWT).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Web tests | `cd apps/web && pnpm test` | all pass, new files listed |
| Web full gate | `cd apps/web && pnpm check` | exit 0 (zero eslint warnings, knip clean) |
| API tests (focused) | `cd apps/api && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run pytest tests/routes/auth -q` | all pass |
| API lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |

(Start Postgres first if needed: `make db-up && make db-wait`; after plan 062,
`make api-test` provisions `praxis_test` automatically.)

## Scope

**In scope** (create only; plus reading anything):

- `apps/web/src/features/conversations/message-parts/parse.test.ts`
- `apps/web/src/features/conversations/message-parts/pair-tool-results.test.ts`
- `apps/web/src/features/agents/components/agent-form-model.test.ts`
- `apps/web/src/features/schedules/components/schedule-form-model.test.ts`
- `apps/web/src/features/conversations/approval-decisions.test.ts`
- `apps/web/src/lib/format.test.ts`
- `apps/api/tests/routes/auth/test_internal_token_auth.py`

**Out of scope** (do NOT touch):

- Any production source file. This plan is 100% additive test files. If a test
  reveals a real bug, record it in your report — do not fix it here.
- No new test libraries (no @testing-library, no jsdom config changes).
- `apps/web/src/components/ui/` and the already-tested `stream/` modules.

## Git workflow

- Work on `main` unless told otherwise; commit style: `Cross - Behavioral Test Safety Net`.
- Do NOT push unless instructed.

## Steps

### Step 1: Message-parts parser tests

Create `parse.test.ts`. Build literal `ConversationMessage` fixtures (see
`src/features/conversations/types.ts` for the shape; copy the fixture style
from `reducer.test.ts`). Cover at minimum:

1. A plain user + assistant text exchange parses into the expected render
   items.
2. A tool call followed by its result pairs into one tool row
   (exercise `pair-tool-results.ts` both via `parse.test.ts` and directly in
   its own file for the unpaired-result and orphan-call cases).
3. A `capability-load` tool kind produces the skill-activation presentation
   item, not a generic tool row.
4. Delegation call/return parts group under the delegation item.
5. Unknown/unhandled part kinds do not throw and do not produce empty
   crash-prone items (assert the documented fallback behavior — read the code
   first and pin what it actually does).
6. Message ordering is stable for identical timestamps (sequence fallback).

**Verify**: `cd apps/web && pnpm test -- parse` → new tests pass.

### Step 2: Form-model tests

`agent-form-model.test.ts`:

- `initialAgentFormState(null, catalog)` produces the documented defaults
  (`maxSteps: "20"`, `isActive: "true"`, …).
- `initialAgentFormState(agent, catalog)` round-trips an existing agent.
- `validateAgentFormState` returns entries for: empty name, empty
  instructions, non-integer/out-of-range maxSteps; and returns `[]` on a valid
  state.
- `buildAgentPayload(state, "create")` and `("edit")` — assert full payload
  shape for a valid state, and assert the `string` error return for the
  invalid states the function guards.
- `isAgentFormDirty` — false for untouched state, true after one field change.

`schedule-form-model.test.ts` (same structure), plus timezone behavior through
the exported payload builder:

- A wall-clock datetime in `Europe/London` across a DST boundary serializes to
  the correct UTC instant.
- A nonexistent wall time (spring-forward gap) and an invalid datetime string
  return the model's documented failure value rather than a wrong instant
  (read `toIsoDateTimeInTimeZone`'s fallback: it returns `null` when the
  fixed-point iteration cannot land on an equal wall time — pin whatever the
  exported builder surfaces for that case).
- Interval validation: non-integer and `< 1` minutes rejected.

**Verify**: `cd apps/web && pnpm test -- form-model` → all pass.

### Step 3: Approval-decision and formatter tests

`approval-decisions.test.ts`: `approveDecision`/`denyDecision` preserve
own-field state and reset the other field (e.g. approving a previously denied
decision clears `message`); the summary helper counts
approved/denied/pending and `allDecided` correctly.

`format.test.ts`: `formatBytes` boundaries (1023 B, 1 KB, 1 MB),
`pluralize`, `titleCaseToken` (underscores, hyphens, empty → fallback),
`initials` (name, email, null), `normalizeOptionalText`,
`truncateForPreview` (null, under-limit, over-limit). For `formatDateTime`,
assert only the `"Never"` null branch and that a valid ISO string returns a
non-empty string — locale-dependent output must not be snapshot.

**Verify**: `cd apps/web && pnpm test` → suite green; `pnpm check` → exit 0.

### Step 4: Internal-token confinement tests (backend)

Create `apps/api/tests/routes/auth/test_internal_token_auth.py`. Use the
existing factories to create a user, two workspaces with memberships, and an
`AgentScheduleRun` row (see `tests/factories/workspaces.py` and how
schedule-run rows are built in `tests/services/agent_schedules/`). Forge
tokens locally in the test file:

```python
import jwt
from core.settings import settings

def _forge_internal_token(**claims) -> str:
    payload = {"type": "user_session_token", "jti": "test-jti", "internal": True, **claims}
    return jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm="HS256")
```

Drive a cheap authenticated GET route (e.g. `/api/v1/auth/me` — confirm the
exact path in `routes/auth/`) with `Authorization: Bearer <token>` and the
`X-Workspace` header, via the app client fixture used by other
`tests/routes/` modules. Cases, each asserting the response status:

1. Happy path: valid claims, matching workspace → 200.
2. `type` wrong → 401. `internal` missing/False → 401. `jti` missing → 401.
3. `schedule_run_id` set, run's `workspace_id` differs from token
   `workspace_id` → 401.
4. `schedule_run_id` set, run's `user_id` differs → 401.
5. `schedule_run_id` set, run soft-deleted → 401.
6. Valid token pinned to workspace A, request `X-Workspace` header for
   workspace B the user is also a member of → 403
   (`_enforce_internal_token_workspace` raises `AuthorizationError`).
7. Expired token (`exp` in the past) → 401.

**Verify**:
`cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/routes/auth/test_internal_token_auth.py -q`
→ all pass. Then run the full auth+middleware slice:
`uv run pytest tests/routes/auth tests/middleware -q` → all pass.

## Test plan

This plan *is* the test plan; the new files and cases are enumerated in the
steps. Structural patterns: `reducer.test.ts` (web),
`tests/routes/` modules + `tests/factories/` (api).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `cd apps/web && pnpm check` exits 0 (includes the new tests, zero lint warnings, knip clean)
- [ ] Six new `.test.ts` files exist at the in-scope paths and contain ≥ 30 assertions total
- [ ] `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/routes/auth -q` exits 0 and collects the 7+ new cases
- [ ] `git status` shows only new test files (no production source modified)
- [ ] Status row updated in `docs/plans/000_README.md`

## STOP conditions

Stop and report back (do not improvise) if:

- Any test reveals a genuine production bug (wrong tz conversion, parser
  crash, auth branch not rejecting). Write the failing test, mark it
  `it.skip`/`pytest.mark.xfail` with a one-line reason, and report — do not
  change production code.
- `parseConversationMessages`' signature or the form-model export names don't
  match this plan (drift — the scaffolding-consolidation plan may have run
  first; if so, report and re-anchor).
- The forged-token tests pass without the DB fixtures (would mean the
  validator no longer checks schedule runs — auth behavior changed).
- Vitest needs config changes to pick up the new files.

## Maintenance notes

- The web scaffolding-consolidation plan (064) moves/merges the form-model
  plumbing these tests cover; the tests are the safety net for that refactor
  and must be updated (imports only, not assertions) as part of it.
- Follow-up recorded for the maintainer: no code mints internal
  `user_session_token` JWTs today. Decide whether to (a) keep the acceptance
  path for the planned schedules HTTP surface, or (b) remove it until a minter
  exists (smaller auth surface). These tests pin behavior for either decision.
- Deliberately deferred: migration data-transform/downgrade tests (repair
  migrations `core/0006`, `core/0011`) and a backend↔frontend enum-drift
  guard. Both remain open findings in `docs/plans/000_README.md`.
