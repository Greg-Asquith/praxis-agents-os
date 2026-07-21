# Plan 088: Applications catalogue, audience surface, and the reference application

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Design-note pre-flight**: implements
> `docs/architecture/internal-applications.md` §2 (catalogue rows), §10
> slice 6 (adopted 2026-07-20, D13). This plan closes the loop: when it is
> DONE, one real application has been built locally from the kit, pushed
> through the gates, published to an audience, opened from the catalogue,
> and has executed an approval-gated tool call with full audit
> attribution. Written at adoption time — re-anchor at execution.
>
> **Drift check (run first)**:
> `git diff --stat 1bc7c03..HEAD -- apps/web/src/ apps/api/routes/ apps/api/services/applications/`

## Status

- **Priority**: P1 (within Phase 7; the phase's acceptance test)
- **Effort**: L
- **Risk**: MED (mostly UI; the risk is honesty — shipping surfaces that
  imply capabilities the loop does not actually have)
- **Depends on**: hard — 083–087 all DONE. The target user constraint
  binds:
  the catalogue is for a non-technical operator; builder-facing
  complexity stays behind the application detail page's owner views.
- **Category**: Phase 7 internal applications (design note §10 slice 6)
- **Planned at**: commit `1bc7c03`, 2026-07-20

## Decisions taken

1. **Catalogue = a workspace list surface over application rows** (note
   §2): published apps the current user's role is audienced for; open →
   the frame host page (mints a frame token, renders the sandboxed
   frame, re-mints on expiry). Plain outcome language; no builder
   vocabulary on the operator path (target-user rule).
2. **Application detail page has two faces.** Everyone audienced: title,
   purpose, owner, "what this app can do" rendered from the contract
   (tools + effects + approval posture in outcome language). Owner/
   manager additionally: version history with publish/rollback, enable/
   disable, audience editing, dev-token management (084's routes), usage
   counters (086), and the machine-readable gate report for failed
   pushes.
3. **Generic approvals surface** (083 decision 6): if the minimal UI was
   deferred there, it lands here — pending app-originated approvals
   listed with the same card treatment as conversation approvals,
   origin-labeled, decided in place.
4. **The reference application is chosen by the maintainer at execution
   start** [STOP — note §11.2 decision]. Default candidate to propose:
   an internal read-mostly dashboard composing one integration read tool
   (e.g. an Airtable-backed team tracker or a Google Ads spend viewer)
   plus one collection — recognisable to a non-technical operator,
   exercising dispatch, approvals (one gated write), collections, files
   or agent-invoke optional. It is built **outside the monorepo from the
   template**, exactly as a real builder would; its source lives in a
   fixture archive under the template's gate fixtures (or a sibling
   repo — maintainer choice) and its walkthrough becomes the builder
   quickstart's worked example.
5. **Full-loop acceptance is a documented, repeatable script** — not CI
   (it needs a live instance + a provider connection): recorded in the
   plan completion notes with honest manual steps, mirroring how 041's
   provider QA is handled.
6. **Navigation**: Applications joins the primary sidebar work sections
   only when at least one app is published in the workspace; empty-state
   entry lives under a less prominent surface [default — confirm at
   review — the non-technical operator should not meet an empty
   developer-flavored section].

## Why this matters

Everything before this plan is architecture; this plan is the product.
It also functions as Phase 7's integration test: if the reference app
cannot be built with the kit's own documentation by a coding agent
without repo access, the tiering promise (§3) is not yet true — and that
finding goes back into the design note rather than being papered over.

## Current state (verify at execution)

- 083–087 as landed: dispatch outcomes + approval polling, token mint
  routes, application CRUD/lifecycle/serving, collections usage,
  gates + kit.
- Web shell conventions: TanStack Router routes, workspace-scoped query
  keys (064), shared form kit + wizard shell (UI-015/016), approvals
  card treatment (UI-027).

## Scope

**In scope:**

- Web: catalogue list, frame host page (token mint + refresh +
  sandboxed iframe), application detail (both faces), owner lifecycle
  controls, dev-token management UI, generic approvals wiring
- API: any thin read endpoints the UI needs that 085/086 did not expose
  (list-with-audience-filter, contract render model)
- The reference application (per decision 4) + the worked-example
  walkthrough in the builder quickstart
- Tests: web behavioral tests for catalogue/detail/host page states;
  API audience-filter tests; the documented full-loop script

**Out of scope (do NOT touch):**

- Capability-request intake/triage UX (product-brief territory; the
  note scopes it out) — a plain "request a capability" mailto/link at
  most
- Groups-based audiences; cross-workspace catalogues; any public/
  external exposure (note §9)
- In-Praxis app authoring

## Git workflow

- Branch: per operator direction (standing 2026-07-20 preference: `main`)
- Commit style: `Web - Applications Catalogue` / reference-app work per
  its own repo/fixture conventions
- Do NOT commit without explicit operator approval.

## Steps (coarse — refine at execution)

1. STOP-gate: confirm the reference application choice with the
   maintainer (decision 4).
2. Catalogue + host page (token lifecycle first — it is the risky bit).
3. Detail page, owner face, dev tokens, approvals wiring.
4. Build the reference app through the kit as an outsider; log every
   friction point; feed fixes back to 087's template/docs in the same
   pass.
5. Full-loop acceptance script + walkthrough docs; AGENTS.md "Current
   Shape" update (applications are now wired end to end).

## Test plan

Pinned invariants: **the catalogue never lists apps outside the user's
audience**, **the host page never renders a frame without a valid
token and re-mints on expiry**, **disabling an app removes it from the
catalogue and breaks open frames within TTL**, **the owner face is
role-gated**, **the reference app's approval-gated write round-trips
through the generic approvals surface with (user, via app, version)
audit attribution**.

## Done criteria

- [ ] Web + API suites green (`pnpm check`, DB-backed pytest for new
      endpoints)
- [ ] Full-loop script executed and recorded (honest manual steps)
- [ ] Reference app built from the template without monorepo access;
      friction findings folded back or filed
- [ ] AGENTS.md + design note updated: applications wired end to end;
      any deviations recorded back into the note (its adoption rule)
- [ ] `000_README.md` row updated; Phase 7 marked complete in the
      roadmap

## STOP conditions

- The maintainer has not chosen the reference application (decision 4).
- The kit cannot produce a working app without touching the monorepo —
  that is a Phase 7 architecture failure; report back to the design
  note, do not hack around it.
- Frame token UX forces lifetimes beyond 084's bounds or browser-side
  dev tokens — reconcile with 084 instead of loosening.
- Any surface would imply pending capability (groups, external sharing,
  capability-request workflow) — document as pending instead.

## Maintenance notes

- The friction log from step 4 is the seed for the follow-up lane:
  `praxis create-app` generator, shared UI package, richer gate
  feedback — file them, do not absorb them here.
- Catalogue growth features (search, categories, usage stats) wait for
  real multi-app workspaces.
