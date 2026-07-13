# Plan 067: OAuth connect-flow hardening — PKCE and single-use state (amendment to 038)

> **Executor instructions**: This is an amendment plan in the 061 mold —
> its deliverable is a clearly-marked amendment block appended to
> `docs/plans/complete/038-integration-oauth-connect-flows.md`, not code. The code
> lands when 038 executes. The full amendment text is drafted verbatim in
> the "Amendment text" section below; paste it, add the one-line pointer,
> and reconcile — do not redesign. When done, update the status row in
> `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c770a1c..HEAD -- docs/plans/complete/038-integration-oauth-connect-flows.md apps/api/services/auth/oauth/utils.py apps/api/core/settings/ apps/api/middleware/csrf.py`
> and `ls apps/api/routes/integrations 2>/dev/null`. If the 038 plan file
> changed, re-verify the "Current state" quotes below against its live
> text before pasting. If `routes/integrations/` exists or 038's README
> row is no longer TODO, 038 has started executing — STOP (see STOP
> conditions). `services/integrations/` appearing is 037 landing, not
> drift.

## Status

- **Priority**: P1
- **Effort**: S (plan amendment; the code cost is absorbed into 038)
- **Risk**: LOW as a doc — it removes an authorization-code-injection
  risk from Phase 4a before any OAuth code exists
- **Depends on**: 038 (written, TODO). **Binds before 038 executes.**
- **Category**: Lane B — best-practice amendments (067–074, added
  2026-07-07)
- **Planned at**: working tree at commit `c770a1c`, 2026-07-07
- **Completed**: 2026-07-10

## Decisions taken

The full normative text lives in the amendment (its decisions 13–17);
summarized here:

1. **PKCE (S256) is mandatory on every integration authorization-code
   flow.** RFC 9700 (OAuth 2.0 Security Best Current Practice) and
   OAuth 2.1 require PKCE for authorization-code flows *including
   confidential clients* — it defends against authorization-code
   injection. It matters more than usual here because 038's callback is
   deliberately not session-bound, so no session check ties a stolen
   `code` to the browser that started the flow. Google supports S256;
   Airtable's OAuth requires PKCE outright (038 ships Airtable
   api-key-only, but the engine must be ready).
2. **A short-lived server-side pending-OAuth-state row solves both
   findings with one table.** Keyed by the state JWT's `jti`, it stores
   the `code_verifier` and is consumed atomically on callback: single-
   use state plus server-side verifier custody. The signed JWT stays;
   038's `jti` ("for log correlation") becomes the row key.
3. **Verifier-inside-the-state-JWT rejected.** The state transits the
   browser (location bar, referrers, proxy logs, history sync) and the
   JWT is signed, not encrypted — an attacker who steals state+code
   would also hold the verifier, defeating PKCE. RFC 9700's
   code-injection defense depends on the verifier staying confidential
   to the client.
4. **Session-binding the callback remains rejected.** 038 decision 2's
   rationale (single API-side redirect URI, server-side transaction,
   SPA-independent console config) stands; single-use consumption plus
   PKCE close the leak/replay window without it.
5. **`INTEGRATIONS_OAUTH_REDIRECT_URI` must be `https` outside
   `ENVIRONMENT=local`**, enforced in the production-safety
   `model_validator` (the `local_fs`/`console` pattern,
   `core/settings/__init__.py:66-70`). Empty stays allowed (provider
   simply disabled, per 038 Step 1).
6. **The row means a migration, which 038 currently forbids** — the
   amendment supersedes 038's "no new migration" language for exactly
   this one table.

## Why this matters

038 is written but not executed, so this hardening is free. Executed as
written, its state JWT is a replayable bearer for its 10-minute TTL —
anyone holding a leaked callback URL can complete the connect — and an
injected code exchanges successfully because nothing proves it belongs
to the flow that started. Both are named attacks in RFC 9700 with named
fixes (PKCE, single-use state). Amending the plan now is a few lines;
retrofitting the executed flow later is a migration plus a security
advisory.

## Current state

All quotes verified against `docs/plans/complete/038-integration-oauth-connect-flows.md`
at `c770a1c` (2026-07-07). 038 is TODO in `000_README.md` (row 124).

- **No PKCE anywhere in 038.** Step 3's `build_authorization_url` param
  list is `client_id`, `redirect_uri`, `response_type=code`, `scope`,
  `state`, `access_type=offline`, `prompt=consent`,
  `include_granted_scopes=false` — no `code_challenge` /
  `code_challenge_method`; `exchange_authorization_code` sends no
  `code_verifier`.
- **State is a pure bearer.** Decision 1: "ONE HS256 JWT carried
  entirely in the OAuth `state` parameter — no cookies, no server-side
  state row." Step 2: "`jti` for log correlation." Nothing enforces
  single use within the TTL (`INTEGRATIONS_OAUTH_STATE_TTL_MINUTES`,
  default 10).
- **Callback is not session-bound by design.** Step 4 route table:
  callback has "**no session dependency** — identity comes from the
  signed state (decision 1/2)". Correct posture — but it removes the
  incidental session check that would otherwise blunt a leaked
  state+code URL.
- **Redirect URI scheme unvalidated.** Scope adds
  `INTEGRATIONS_OAUTH_REDIRECT_URI: str = ""`; Step 1 says "No
  production-safety validator change."
- **Migrations are forbidden in 038.** Out of scope: "Any Alembic
  migration — 037 owns the schema; if you need a column, STOP." Done
  criteria: "no new migration in this plan". The amendment must delta
  both or 038's executor deadlocks.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 038 unexecuted | `ls apps/api/routes/integrations 2>/dev/null` | no such directory |
| Amendment landed | `grep -c "Amendment (plan 067" docs/plans/complete/038-integration-oauth-connect-flows.md` | `2` (pointer + block) |
| Doc-only diff | `git status --porcelain` | only the two plan docs + this file's README row |

## Scope

**In scope:**

- `docs/plans/complete/038-integration-oauth-connect-flows.md` — append the
  amendment block; add one pointer line to the executor-instructions
  blockquote
- `docs/plans/000_README.md` — add the 067 row; note the 038 amendment

**Out of scope:**

- Any code, migration, or test — all of it lands inside 038's execution
  per the amendment
- Rewriting 038's existing body text (the amendment supersedes by
  reference; inline edits would hide the history)
- The login OAuth flow (`services/auth/oauth/`) — different threat
  model (SPA-received callback, session established after)
- Plans 039–042

## Git workflow

- Branch: `advisor/067-oauth-pkce-state-hardening`
- Commit: `Docs - OAuth PKCE & State Hardening Amendment`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Pointer line in 038

After running the drift check, add to 038's executor-instructions
blockquote, after the governance pre-flight paragraph:

> **Amendment (plan 067) pre-flight**: the "Amendment (plan 067,
> 2026-07-07)" block at the end of this file amends decisions 1/9 and
> Steps 1/2/3/7; where it conflicts with the body above, the amendment
> wins.

**Verify**: the blockquote renders as one quote; no other body line
touched.

### Step 2: Append the amendment block to 038

Paste the "Amendment text" section below verbatim at the end of the
file.

**Verify**: `grep -c "Amendment (plan 067"` returns 2.

### Step 3: Update the README

Add the 067 row and a dated note that 038 carries a 067 amendment
(PKCE + single-use state).

**Verify**: table renders; `git status` shows only in-scope files.

## Amendment text

Paste into 038 verbatim:

```markdown
## Amendment (plan 067, 2026-07-07): PKCE + single-use state

Written before this plan executed; where this block conflicts with the
body above, this block wins. Grounding: RFC 9700 (OAuth 2.0 Security
BCP) and OAuth 2.1 require PKCE (S256) on authorization-code flows
including confidential clients, and require state/code replay defenses.
Both matter doubly here because the callback is deliberately not
session-bound (decision 1/2).

### New decisions

13. **PKCE S256 on every authorization-code connect.**
    `start_oauth_connect` generates a `code_verifier` per RFC 7636
    (43–128 chars from a CSPRNG) and sends
    `code_challenge=BASE64URL(SHA256(verifier))` +
    `code_challenge_method=S256` on the authorization URL;
    `exchange_authorization_code` sends the `code_verifier` in the token
    POST. Applies to the Google family AND the fake provider (which must
    verify challenge↔verifier so tests pin the relation). Any future
    OAuth-mode provider (e.g. Airtable, whose OAuth requires PKCE)
    inherits this unconditionally.
14. **Server-side pending-OAuth-state row, single-use.** New table
    `integration_oauth_states`: `jti` (PK, from the state JWT),
    `connection_id`, `code_verifier` (encrypted at rest with the same
    symmetric primitive 037 uses for token columns — reuse its helper;
    if 037 delivered no reusable helper, record the deviation and the
    fallback in the PR description), `created_at`, `expires_at` (same
    TTL as the JWT). Created in `start_oauth_connect`'s existing
    transaction; consumed in `complete_oauth_callback` by a single
    atomic `DELETE ... WHERE jti = :jti RETURNING ...` BEFORE the token
    exchange. No row (expired, swept, or replayed) → the existing
    invalid-state path: `IntegrationAuthError` +
    `INTEGRATION_OAUTH_STATE_INVALID` security event + error redirect.
    This amends decision 1's "no server-side state row"; the signed JWT
    stays (authenticity, claims, cross-flow `type` pinning) and its
    `jti` — previously log-correlation only — becomes the row key.
15. **Verifier-in-JWT rejected.** The state transits the browser and
    the JWT is signed, not encrypted; an attacker who steals state+code
    would also hold the verifier, defeating PKCE. The verifier never
    leaves the server.
16. **One migration allowed.** This supersedes "Any Alembic migration —
    037 owns the schema; if you need a column, STOP" and the
    "no new migration in this plan" done criterion, for exactly the
    `integration_oauth_states` table, on the same Alembic
    branch/version-path 037 used for the integration tables. Anything
    beyond that table remains a STOP.
17. **`INTEGRATIONS_OAUTH_REDIRECT_URI` must be `https` outside
    `ENVIRONMENT=local`** — enforced in the production-safety
    `model_validator` (`core/settings/__init__.py`, the
    `local_fs`/`console` pattern); empty remains allowed (provider
    disabled). This amends Step 1's "No production-safety validator
    change".

### Step deltas

- **Step 1**: add the decision 17 validator clause + a settings test.
- **Step 2**: unchanged shape; note in `utils.py` that `jti` keys the
  pending row (decision 14).
- **Step 3**: `start_oauth_connect` mints verifier/challenge and
  persists the pending row in its transaction; `build_authorization_url`
  gains `code_challenge`/`code_challenge_method=S256`;
  `exchange_authorization_code` gains `code_verifier`;
  `complete_oauth_callback` consumes the row first (decision 14). Fake
  provider verifies the S256 relation and rejects a wrong verifier.
- **New step (before Step 1)**: the `integration_oauth_states`
  migration per decision 16; `uv run alembic check` clean afterwards.
- **Step 7 / test plan additions**: authorization URL carries
  `code_challenge` + `method=S256`; the fake exchange fails on a
  mismatched verifier and succeeds on the real one; **replay** — a
  second callback with the same valid state → error redirect, security
  event, no second credential, connection state unchanged; expired
  pending row → same rejection even with a not-yet-expired JWT;
  validator test — non-local env + `http://` redirect URI raises.
- **Done criteria deltas**: replace the "(no new migration in this
  plan)" criterion with "exactly one migration: `integration_oauth_states`";
  add "[ ] state replay rejected (test green)" and "[ ] PKCE pinned on
  auth URL + token exchange (tests green)".

### Maintenance

039's sweep should purge expired `integration_oauth_states` rows
alongside stale `auth_pending` connections (inert until then).
```

## Test plan

None here — doc-only. The behavioral tests (PKCE pinning, replay
rejection, expired-row rejection, https validator) are specified in the
amendment's Step 7 deltas and land with 038's execution.

## Done criteria

- [x] `docs/plans/complete/038-integration-oauth-connect-flows.md` ends with the
      "Amendment (plan 067, 2026-07-07)" block, pasted verbatim
- [x] 038's executor-instructions blockquote carries the plan 067
      pre-flight pointer line
- [x] `git diff docs/plans/038-*.md` shows only the pointer line and
      the appended block — no other body edits
- [x] `docs/plans/000_README.md` row for 067 added and 038's amendment
      noted; 038's row itself stays TODO
- [x] No code, migration, or test files changed; roadmap bookkeeping and
      the required move to `plans/complete/` are the only additional changes

## STOP conditions

Stop and report back (do not improvise) if:

- **038 has started or finished executing** (`routes/integrations/`
  exists, or its README row is not TODO) — the amendment target is now
  live code; this becomes a code-hardening plan with a migration
  against real rows, which needs replanning, not pasting.
- 038's plan text has drifted such that the "Current state" quotes no
  longer match (e.g. PKCE or a state row was already added) — reconcile
  before pasting a stale amendment.
- An "Amendment (plan 067" marker already exists in 038 — a previous
  run landed; verify rather than duplicate.

## Maintenance notes

- 038's executor owns reconciling the amendment against 037's *actual*
  deliverables (encryption helper, Alembic branch); the two open
  latitudes are named inside the amendment (decisions 14 and 16) so
  deviations get recorded in 038's PR, not silently taken.
- If a later plan adds an OAuth mode for Airtable (or any provider),
  PKCE is already unconditional via decision 13 — only endpoint wiring
  is new.
- The login OAuth flow is deliberately out of scope; if it is ever
  hardened to match, keep the flows' state `type` claims distinct (038
  decision 1) so replay stays impossible across them.
