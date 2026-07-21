# Plan 085: Application model, contract, versioned bundles, and sandboxed serving

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Design-note pre-flight**: implements
> `docs/architecture/internal-applications.md` §2, §5.1, §7, and §10
> slice 3 (adopted 2026-07-20, D13; Gate G7 binds). Depends structurally on
> plan 050's serving substrate and its 2026-07-20 amendment
> (parameterized `connect-src`, credential-agnostic renderer seam,
> preserved `/apps/{id}/frame` scaffolding) — verify the amendment was
> honored when 050 executed. Written at adoption time — re-anchor at
> execution.
>
> **Drift check (run first)**:
> `git diff --stat 1bc7c03..HEAD -- apps/api/models/ apps/api/services/files/ apps/api/services/artifacts/ apps/api/middleware/ apps/api/routes/ apps/api/core/settings/`

## Status

- **Priority**: P1 (within Phase 7)
- **Effort**: L
- **Risk**: HIGH (a new content-serving surface executing builder-authored
  JS against the Praxis API; the sandbox + CSP + token scoping ARE the
  deliverable)
- **Depends on**: hard — 031/032 (Files), 050 (serving substrate, incl.
  the D13 amendment), 083 (dispatch), 084 (tokens; see 084 decision 6 for
  order). Gate G3 (governance) and G7 bind.
- **Category**: Phase 7 internal applications (design note §10 slice 3)
- **Planned at**: commit `1bc7c03`, 2026-07-20

## Decisions taken

1. **Applications are core-schema platform rows; only app *data* lives on
   the `app` branch.** The `applications` (+ versions) tables go on the
   core Alembic branch per D5 — they are platform infrastructure like
   agents and skills. 086's collection tables are what the reserved `app`
   schema is for. This resolves the apparent D5 tension explicitly.
2. **An application version = contract + bundle, both immutable.**
   `application_versions` rows carry the validated contract (JSONB) and
   reference bundle content stored through Files (`FileRevision`
   immutability, provenance, retention — note §2). The application row
   holds `current_version_id` (publish pointer), status
   (`draft/published/disabled/retired`), owner + fallback owner, audience
   (workspace roles v1).
3. **Bundle layout** [default — confirm at review]: a pushed bundle is an
   archive validated and expanded at publish time into per-entry objects
   under a versioned storage prefix
   (`workspaces/{ws}/apps/{app}/{version}/...`), with an entry manifest
   (paths, sizes, content types, hashes) stored on the version row. The
   archive itself is retained as the canonical `FileRevision`; expanded
   entries are write-once serving copies. Serving never reads archives on
   the request path.
4. **The contract is machine-enforced** (note §7): id, version, title,
   purpose, owner + fallback, audience, requested building blocks (tool
   `name@version` pins, collection declarations, file namespace,
   agent/schedule references), effect expectations + approval posture per
   declared write, storage/retention expectations, support class
   [default — confirm at review: best-effort v1]. Publish-time scope-diff:
   changes that widen audience, add write scopes, or add sensitive
   resources re-enter validation (note §7).
5. **Serving rides the 050 substrate with one deliberate difference.**
   `/apps/{id}/frame` (the dormant middleware scaffolding, now claimed)
   serves the shell entry; asset paths serve manifest entries. Same
   opaque-origin sandbox + strict CSP discipline as artifacts, but
   `connect-src` = **the Praxis API origin only** (via 050's
   parameterized builder) instead of `'none'`. `frame-ancestors` limited
   to app origins; no cookies on serving responses (the 050 carve-out
   pattern); `Referrer-Policy: no-referrer`, `no-store`.
6. **Frame mint checks everything the token cannot re-check cheaply**:
   membership, audience/role, published + enabled. Verify-time re-checks
   the row flags (084 decision 2). Disable is therefore immediate for new
   loads and ≤ frame-TTL for open ones.
7. **Lifecycle operations are CRUD + audit, not machinery** (note §2
   table): publish = pointer + status change (audited), rollback =
   pointer to a prior version (audited), disable = flag, retire = soft
   delete under governance §3 retention. Owner/manager-gated per
   governance §1 [default — confirm at review: MANAGER to publish].
8. **Upload path reuses the signed two-phase upload seam** (032/asset
   tokens) for the archive; validation gates themselves are 087's — this
   plan enforces only the structural minimum at publish (archive sanity,
   size caps, contract schema validity, scope-diff) so 087 can layer the
   full gate set without reshaping storage.

## Why this matters

This is the slice where "applications are workspace content, not
deployments" becomes literal: rows, revisions, pointers. Everything the
brief's lifecycle workstream wanted (deploy, version, roll back, disable,
own, audit) collapses into existing primitives — provided bundles are
immutable, serving is sandboxed, and the contract actually drives token
scopes and validation rather than being documentation.

## Current state (verify at execution)

- Dormant scaffolding: `middleware/utils.py` `_is_app_frame_path`
  matching `/apps/{id}/frame`, the security-headers branch,
  `X-Praxis-App-Frame-Token` in CORS — reserved for exactly this plan.
- 050 (must be DONE): serving pipeline, CSP builders with parameterized
  `connect-src` (D13 amendment), cookie-free carve-outs keyed on serving
  prefixes.
- 031/032: File/FileRevision immutability, two-phase signed upload,
  storage key validation; 034 scratch conventions.
- `app` Alembic branch exists with zero tables; `AppModel` base exists —
  NOT used by this plan (decision 1); confirm 086 still owns first use.
- 083/084 contracts as landed.

## Scope

**In scope:**

- `models/applications.py` (+ versions) on core; migrations; settings
  mixin (bundle size caps, entry caps)
- `services/applications/` — contract schema + validation, scope-diff,
  create/list/get, upload/publish/rollback/disable/retire operations,
  entry-manifest builder, storage expansion
- Serving routes on the 050 substrate (`/apps/{id}/frame`, asset
  entries) with the decision 5 CSP; frame-token mint route (084's, wired
  to real rows if 084 landed on the stub)
- Owner/manager management routes (CRUD + lifecycle)
- Tests: contract validation + scope-diff, immutability end to end,
  serving headers exact-match, disable/rollback semantics, workspace
  isolation

**Out of scope (do NOT touch):**

- The full publish validation-gate set (secret scan, budgets, CSP asset
  scan) — 087; only decision 8's structural minimum here
- Collections (086), the kit/CLI (087), catalogue UI (088)
- Artifacts behavior — the substrate is shared; artifact CSP stays
  `connect-src 'none'`

## Git workflow

- Branch: per operator direction (standing 2026-07-20 preference: `main`)
- Commit style: `API - Application Model & Serving`
- Do NOT commit without explicit operator approval.

## Steps (coarse — refine at execution)

1. Models + migrations + settings.
2. Contract schema + validation + scope-diff (pure, heavily unit-tested).
3. Upload → validate → expand → version row pipeline.
4. Lifecycle operations + audit.
5. Serving routes + CSP + middleware claim of the dormant scaffolding.
6. Management routes; tests.

## Test plan

Pinned invariants: **serving responses byte-match the decision 5 CSP and
carry no cookies**, **`connect-src` on app serving is exactly the API
origin while artifacts remain `'none'`** (one test pins both, against the
shared builder), **bundles are immutable once published**, **rollback
repoints without mutation**, **a widened contract re-enters validation**,
**disabled apps stop minting and stop verifying**, **cross-workspace
access 404s uniformly**.

## Done criteria

- [ ] Ruff + alembic clean; migrations round-trip (core branch only)
- [ ] Contract validation + scope-diff pinned by unit tests
- [ ] Serving headers exact; cookie-free; sandbox attributes present
- [ ] Lifecycle ops audited; governance cells flipped if implemented
- [ ] DB-backed suites pass; artifact serving suite untouched and green
- [ ] `000_README.md` row updated

## STOP conditions

- 050 executed without the D13 amendment (hard-coded `connect-src
  'none'`, renderer coupled to artifact signatures) — reconcile the
  substrate first; do not fork a second serving pipeline.
- The dormant `/apps/{id}/frame` scaffolding was removed or repurposed.
- Contract fields cannot map onto 082's tool `name@version` or the 084
  scope vocabulary — reconcile the three plans before coding.
- You feel the need to execute anything server-side from a bundle, host
  non-static content, or widen `connect-src` beyond the API origin —
  note §5/§9 forbid all three.

## Maintenance notes

- The contract is the single source for token scopes (084), validation
  (087), and the catalogue (088) — schema changes must version.
- Audience groups (beyond workspace roles) are a recorded future
  extension (note §2); the audience column should not preclude them.
- Retention: retired applications follow governance §3; expanded serving
  copies must be swept with their version rows (add the sweep kind here
  or record it for 087's gate work — decide at execution and document).
