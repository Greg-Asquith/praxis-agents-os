# Plan 084: Scoped application tokens — frame and development mint paths

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Design-note pre-flight**: implements
> `docs/architecture/internal-applications.md` §4 and §10 slice 2 (adopted
> 2026-07-20, D13; Gate G7 binds). The §4 non-goals are load-bearing: no
> OIDC/OAuth2 provider, no PATs-as-API, no service accounts, no machine
> principals. Written at adoption time — re-anchor all excerpts at
> execution.
>
> **Drift check (run first)**:
> `git diff --stat 1bc7c03..HEAD -- apps/api/core/dependencies.py apps/api/core/settings/ apps/api/utils/security.py apps/api/middleware/ apps/api/models/`

## Status

- **Priority**: P1 (within Phase 7)
- **Effort**: M-L
- **Risk**: HIGH (a new credential type; scoping and revocation are the
  product)
- **Depends on**: hard — 083 (the entrypoint these tokens authorize), 085's
  application rows for audience binding (see decision 6 for the stub
  option), 037's `derive_purpose_key` helper (DONE). AGENTS.md security
  constraints bind: production CORS/cookie/CSRF posture is not loosened.
- **Category**: Phase 7 internal applications (design note §10 slice 2)
- **Planned at**: commit `1bc7c03`, 2026-07-20

## Decisions taken

1. **One verifier, two mint paths.** A single verification function
   resolves any app token to `(user, workspace, application_id,
   application_version, scopes, kind ∈ {frame, dev})`. Frame and dev
   tokens differ only in mint path, lifetime, and storage — never in
   verification or scope semantics.
2. **Frame tokens are stateless-signed, short-lived.** Minted by an
   authenticated, workspace-resolved route when the shell opens an app.
   HMAC-signed (key: `derive_purpose_key(SECRET_KEY,
   "praxis:app-frame-token:v1")` — the 068 pattern; never raw
   `SECRET_KEY`), versioned scheme (`v1.` prefix; unknown versions
   rejected uniformly). Payload: user id, workspace id, application id +
   version, scope digest, expiry. TTL default **15 minutes**, shell
   re-mints on expiry [default — confirm at review]. Verification also
   checks the live application row (published, not disabled/retired) —
   the row flag is the revocation lever (note §2), so signed statelessness
   does not weaken disable.
3. **Dev tokens are DB rows, hashed at rest.** Created by the
   application's owner from its page; stored via `hash_token` (only the
   hash persists), displayed once. Lifetime default **30 days, max 90**
   [default — confirm at review]; revocable (row delete/flag), listed
   with prefix + created/last-used metadata, audited on create/revoke.
   **Read-scoped by default; write scopes are an explicit per-token
   toggle** [default — confirm at review, note §4.2]. Data-collection
   access under a dev token resolves to the dev/scratch namespace (086
   implements the namespace; this plan carries the flag).
4. **Bearer transport, outside the cookie path.** Tokens travel as
   `Authorization: Bearer` (the `X-Praxis-App-Frame-Token` CORS header
   already allowlisted is kept as an accepted alias for the frame path).
   Bearer requests carry no session cookie semantics: CSRF enforcement
   does not apply to them by design, and nothing about cookie CSRF or
   CORS configuration changes. Production posture untouched (AGENTS.md).
5. **Scope enforcement is a dependency, not per-route code.** A FastAPI
   dependency (`AppTokenDep(scope="...")`-style) verifies the token,
   checks audience against the requested resource, and asserts the
   required scope; every app-capability route (083 dispatch route, 086
   data routes, file/agent extensions) declares it. Scopes are the
   contract-declared building-block identifiers (085 defines the
   vocabulary; until then, tool names + coarse `collections:read/write`,
   reconciled when 085 lands).
6. **Sequencing vs 085.** Preferred order is 085 → 084 execution (real
   application rows to bind audience to). If executed first, bind to the
   id+version stub from 083 and add a STOP: no dev-token creation surface
   ships until a real application row exists to own it.
7. **Rate limiting**: token-authenticated routes get their own rate-limit
   key class (token id), bounded per C04's cardinality rules.

## Why this matters

This is the entire identity story for internal applications — deliberately
small. The app is a narrower principal than its user; the token is the
narrowing. Getting lifetime, revocation, and scope checks right here means
085–088 never handle credentials at all.

## Current state (verify at execution)

- `core/dependencies.py` — session-cookie auth resolution; the 063-pinned
  internal `user_session_token` branch is adjacent precedent for
  non-cookie principals (maintainer keep/remove decision recorded there —
  do not silently repurpose it; this plan adds its own dependency).
- `utils/security.py` — `create_hmac_signature`/`verify_hmac_signature`
  (constant-time), `hash_token`/`verify_token_hash`; `derive_purpose_key`
  landed with 037 (068 amendment).
- `middleware/` — CORS allowlist already carries
  `X-Praxis-App-Frame-Token`; CSRF enforcement fires on unsafe methods
  with cookies; the app-frame path scaffolding (`_is_app_frame_path`)
  exists dormant.
- No token models beyond sessions/asset-upload tokens exist.

## Scope

**In scope:**

- Frame-token mint service + route (`POST
  /api/v1/apps/{id}/frame-token` — final path set by 085's router);
  verify function; settings mixin (TTLs, max dev lifetime)
- `models/app_dev_tokens.py` (create) + core migration; dev-token
  create/list/revoke services + owner-gated routes; audit rows
- The shared `AppToken` dependency + scope assertion helpers
- Rate-limit key wiring for token-authenticated routes
- Tests: mint/verify round-trip, expiry, tamper, disabled-app rejection,
  scope assertion matrix, dev-token hash-at-rest + revoke + once-only
  display, no-cookie/no-CSRF interaction pinning

**Out of scope (do NOT touch):**

- Any OAuth/OIDC surface, service accounts, or general-purpose PATs
  (note §9 non-goals — STOP if scope drifts there)
- The serving route itself (085); collections namespaces (086); the dev
  proxy that keeps tokens out of browsers (087)
- CORS origin lists, cookie flags, CSRF exempt lists

## Git workflow

- Branch: per operator direction (standing 2026-07-20 preference: `main`)
- Commit style: `API - Scoped Application Tokens`
- Do NOT commit without explicit operator approval.

## Steps (coarse — refine at execution)

1. Settings + purpose key + token codec (sign/verify with versioned
   scheme, constant-time, uniform failure).
2. Frame mint route (authenticated, workspace-resolved, app
   published/enabled check, audience+scope stamping).
3. Dev-token model/migration/services/routes (owner-gated, hashed,
   display-once, audit).
4. The verification dependency + scope helpers; wire onto 083's dispatch
   route as the first consumer.
5. Rate-limit keys; tests.

## Test plan

Pinned invariants: **a tampered/expired token fails uniformly** (no
oracle), **a disabled application's tokens stop verifying** (both kinds),
**scopes are enforced by the dependency** (a token without a scope cannot
reach a route requiring it), **dev tokens persist only as hashes**,
**revocation is immediate**, **no `Set-Cookie` and no CSRF interaction on
bearer routes**.

## Done criteria

- [ ] Ruff + alembic clean; migration round-trips
- [ ] One verify function serves both mint paths; kind never widens scope
- [ ] 083's route enforces via the shared dependency
- [ ] DB-backed token/route suites pass
- [ ] No change under `middleware/` beyond what the drift check justifies;
      production CORS/CSRF posture untouched
- [ ] `000_README.md` row updated

## STOP conditions

- 083 is not DONE (nothing to authorize).
- No application row exists and the execution order was not consciously
  chosen per decision 6.
- Any step would loosen CORS/cookie/CSRF/rate-limit posture (AGENTS.md) —
  including "temporarily" for local dev; the dev proxy (087) is the
  sanctioned local path.
- You are adding refresh tokens, offline grants, or non-user principals —
  that is the external-identity architecture the note explicitly rejects.

## Maintenance notes

- The scope vocabulary is contract-derived (085); when 085 lands, replace
  any interim coarse scopes in one sweep and add a contract→scope
  round-trip test.
- Token scheme versioning (`v1.`) exists so rotation/algorithm changes are
  additive; never verify an unversioned payload.
- If a future need for genuinely external callers appears, that is a new
  architecture decision (note §4.1) — not an extension of this token.
