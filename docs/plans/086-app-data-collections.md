# Plan 086: App data collections on the `app` schema

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Design-note pre-flight**: implements
> `docs/architecture/internal-applications.md` §5.2 (app data row) and §10
> slice 4 (adopted 2026-07-20, D13; Gate G7 binds). This is the first use
> of the reserved `app` Alembic branch and `AppModel` base (D5). Written at
> adoption time — re-anchor at execution.
>
> **Drift check (run first)**:
> `git diff --stat 1bc7c03..HEAD -- apps/api/models/ apps/api/alembic/ apps/api/services/applications/ apps/api/core/settings/`

## Status

- **Priority**: P1 (within Phase 7)
- **Effort**: M
- **Risk**: MED (a bounded new storage surface; the risks are quota
  honesty and namespace isolation, not novel machinery)
- **Depends on**: hard — 085 (contracts declare collections), 084 (scope
  enforcement + the dev-namespace flag), 083 (approvals if a collection
  write is approval-gated). Gate G3 quotas/retention bind.
- **Category**: Phase 7 internal applications (design note §10 slice 4)
- **Planned at**: commit `1bc7c03`, 2026-07-20

## Decisions taken

1. **v1 is schemaless JSONB documents with quotas** [default — confirm at
   review; note §11.4]. One physical table on the `app` schema
   (`app.collection_documents`): workspace_id, application_id, collection
   name, namespace, document id, JSONB body (size-capped), timestamps,
   created/updated attribution (user via app). Typed/validated
   collections are a recorded follow-up, not v1 — the contract's
   collection declaration reserves a `schema` field as null.
2. **Collections exist only by contract declaration.** A request naming
   an undeclared collection fails uniformly; declarations create no rows
   (lazy). Collection names are contract-scoped identifiers; storage is
   keyed by (application, collection, namespace).
3. **Namespaces: `live` and `dev`.** Frame tokens resolve to `live`; dev
   tokens resolve to `dev` (084 decision 3) so builders never iterate
   against shared rows (note §4.2). A dev-namespace wipe operation is
   owner-callable; `live` has no bulk-wipe in v1.
4. **Quotas are enforced, counters are visible** (governance §4 model):
   per-application caps on document count and total bytes
   [default — confirm at review: 50k docs / 256 MiB per app, doc body ≤
   256 KiB], checked at write time; a usage read operation reports
   counters. Settings-configurable.
5. **Writes are audited as digests, not bodies.** Create/update/delete
   audit rows carry collection, document id, size — never content
   (consistent with tool-args digest practice). Reads are not audited
   (matches files-read posture).
6. **CRUD rides the app capability surface, not dispatch.** These routes
   are app-native storage (like files), token-scope-gated
   (`collections:read` / `collections:write` per declared collection),
   not registry tools — the dispatch boundary (083 maintenance note)
   stays clean. If an *agent* needs collection access later, that is a
   registry tool wrapping this service — a follow-up, not v1.
7. **Retention**: application retire/purge cascades to its collection
   rows under governance §3; the sweep rides the 030 jobs harness.

## Why this matters

The brief's worst observed failure mode is data embedded in generated
source or self-modified files. The countermeasure is a real write path:
bounded, namespaced, quota'd, audited collections that the validation
gates (087) can point builders at. It is also the first `app`-branch
schema user, proving the reserved seam D5 set aside.

## Current state (verify at execution)

- `alembic/versions/app/` exists with zero revisions; `AppModel`
  declarative base exists unused; the Makefile/CI migration-drift check
  covers both branches (confirm).
- 085's contract collection declarations; 084's namespace flag and scope
  vocabulary.
- Governance §4 soft-quota + visible-counter model (files usage endpoint
  is the precedent).

## Scope

**In scope:**

- `models/app_collections.py` on `AppModel` + first `app`-branch
  migration
- `services/app_data/` — read/list/create/update/delete/usage/wipe-dev
  operations (one per file), quota enforcement, audit digests
- Routes on the app capability surface behind the 084 dependency
- Retention sweep kind + wiring into application retire (085 seam)
- Tests: declaration gating, namespace isolation, quota enforcement +
  counters, audit digests, cascade, cross-workspace/app isolation

**Out of scope (do NOT touch):**

- Typed schemas, indexes-per-collection, or query languages beyond
  key/list + simple filters [follow-up]
- Registry-tool exposure of collections (follow-up per decision 6)
- Any UI (088 shows usage read-only at most)

## Git workflow

- Branch: per operator direction (standing 2026-07-20 preference: `main`)
- Commit style: `API - App Data Collections`
- Do NOT commit without explicit operator approval.

## Steps (coarse — refine at execution)

1. Model + first `app`-branch migration (verify the drift check and
   `make` targets exercise the branch; fix tooling gaps in the same
   change).
2. Services with declaration + quota + namespace enforcement.
3. Routes behind token scopes.
4. Retention cascade + sweep; tests.

## Test plan

Pinned invariants: **undeclared collections fail uniformly**, **dev and
live namespaces cannot see each other under either token kind**, **quota
breaches reject with visible counters intact**, **audit rows carry
digests, never bodies**, **retiring an application sweeps its rows**,
**cross-application access within a workspace fails** (audience is the
app, not just the workspace).

## Done criteria

- [ ] Ruff clean; `app`-branch migration applies + round-trips; alembic
      drift check covers it
- [ ] Declaration/namespace/quota invariants pinned by tests
- [ ] DB-backed suites pass
- [ ] Governance §4 counter cell updated if implemented
- [ ] `000_README.md` row updated

## STOP conditions

- The `app` branch has acquired tables since planning (coordinate — D5
  reserved it for verticals; first-use assumptions here break).
- 085's contract shape lacks collection declarations or 084 lacks the
  namespace flag — reconcile upstream plans first.
- Quota enforcement would require table scans on the write path — design
  the counter columns/rollups first; do not ship unenforced "quotas".

## Maintenance notes

- Typed collections (contract `schema` field) and registry-tool access
  are the two recorded follow-ups; both layer on this table without
  migration if document bodies stay JSONB.
- If per-collection secondary indexes become necessary, that is a tier-2
  (building-block) change under the packaging law — not builder-visible
  config.
