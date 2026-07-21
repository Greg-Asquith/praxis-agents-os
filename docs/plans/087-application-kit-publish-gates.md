# Plan 087: Application kit, dev harness, and publish validation gates

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Design-note pre-flight**: implements
> `docs/architecture/internal-applications.md` §6 and §10 slice 5 (adopted
> 2026-07-20, D13). The two framing constraints are load-bearing here:
> builders work locally with their own coding tools and subscriptions;
> Praxis carries no build-time model spend; production CORS/CSRF is never
> loosened for the build loop — the dev proxy is the sanctioned path.
> Written at adoption time — re-anchor at execution.
>
> **Drift check (run first)**:
> `git diff --stat 1bc7c03..HEAD -- apps/api/routes/tools/ apps/api/routes/meta/ apps/api/services/applications/ package.json pnpm-workspace.yaml Makefile`

## Status

- **Priority**: P1 (within Phase 7)
- **Effort**: L
- **Risk**: MED (the gates are security-relevant; the kit itself is
  DX code outside the runtime)
- **Depends on**: hard — 082 (authenticated schema route + catalogue
  fields), 084 (dev tokens), 085 (contract, upload/publish pipeline).
  Soft — 086 (collections in the template examples), 078 (CI OpenAPI
  export precedent).
- **Category**: Phase 7 internal applications (design note §10 slice 5)
- **Planned at**: commit `1bc7c03`, 2026-07-20

## Decisions taken

1. **The kit is a template directory in this repo plus a tiny CLI**
   [default — confirm at review]. `templates/application/` holds a
   Vite + React + approved-UI-baseline scaffold, excluded from the app
   workspaces' build/check graph but exercised by its own smoke check in
   CI. The CLI (`praxis-app` — final name at execution) ships inside the
   template as a dev dependency (Node, no global install): commands
   `catalogue` (refresh snapshot), `client` (regenerate typed client),
   `push` (bundle + upload + publish request). A standalone
   `praxis create-app` generator is a follow-up; "clone the template" is
   the v1 on-ramp.
2. **UI component baseline** [default — confirm at review; note §11.7]:
   copied scaffold, not a shared published package — the template
   vendors the token/theme baseline so builders have zero coupling to
   the monorepo. A shared package is the recorded revisit (same trigger
   discipline as D10's pnpm-workspace rejection).
3. **The dev harness keeps tokens out of the browser.** The template's
   Vite dev server serves the bundle in a shell-emulating frame and
   proxies `/api/*` to the configured Praxis instance, attaching the dev
   token **server-side** from `.env.local` (note §6.2). The browser only
   talks to localhost; no CORS change anywhere; the token never appears
   in client code — and the secret-scan gate rejects it in bundles as
   defense in depth.
4. **Coding-agent instructions are first-class kit content.** The
   template ships `AGENTS.md`/`CLAUDE.md` (what the capability surface
   is, how approvals behave, what the gates reject and what to do
   instead) plus a machine-readable catalogue snapshot
   (`praxis-catalogue.json`: tool names, versions, input/output schemas,
   effects, approval defaults, example calls — from 082's catalog
   fields), refreshed via `praxis-app catalogue` with the dev token.
5. **Typed client generation** consumes 082's authenticated schema route
   (dev token auth), filtered to the app capability surface; committed
   into the builder's repo so their coding agent can read it.
6. **Server-side validation gates run at push, results are
   machine-readable** (note §6.3). Gate set v1
   [default — confirm at review; note §11.6]:
   - secret/credential scan (entropy + known patterns, incl. dev-token
     format);
   - inline-dataset budget and generated-binary budget;
   - manifest ↔ requested-scope consistency; every requested building
     block exists, is enabled, and version-pins resolve (082);
   - CSP compatibility: no external asset references, no forbidden
     directives, bundle entries within size caps;
   - ownership + audience declared.
   Failures return a structured report naming the violated rule and the
   supported replacement pattern — feedback a coding agent can apply
   directly. Gates are code in `services/applications/gates/` (one gate
   per file), run inside 085's publish pipeline seam.
7. **Runtime-vs-publish enforcement split is explicit** (note §11.6):
   anything the browser/CSP or token scopes enforce structurally is NOT
   duplicated as a blocking gate (advisory warnings at most); gates own
   what runtime cannot see (secrets, budgets, declarations).
8. **CI seam**: `push` is non-interactive (token + flags), making
   builder-side CI possible without new server surface.

## Why this matters

This slice is the product promise: a builder with Claude Code/Codex/
Cursor and a dev token gets a working local loop against real workspace
capabilities, and the publish path converts "generated code" into
"governed content" mechanically. The gates encode the brief's failure
catalogue as machine-checkable rules with agent-actionable feedback.

## Current state (verify at execution)

- 082's catalog (`version`, `input_schema`) + authenticated schema
  route; 084's dev tokens; 085's upload/publish pipeline with the
  decision 8 structural-minimum checks and the gate seam.
- Repo tooling: pnpm workspace covers `apps/web`; `make check` runs both
  apps' gates — the template must join CI without joining the app
  dependency graph (confirm approach against live tooling).

## Scope

**In scope:**

- `templates/application/` — scaffold (Vite + React + vendored UI
  baseline), dev-server proxy config, `AGENTS.md`/`CLAUDE.md`,
  `.env.example`, example feature exercising dispatch + a collection
- The CLI (catalogue / client / push) inside the template
- `services/applications/gates/` + wiring into publish; the structured
  failure-report schema
- Catalogue snapshot export route or reuse of the existing catalog route
  (decide at execution; prefer reuse)
- CI: template smoke check (install, build, gate dry-run against
  fixtures)
- Tests: each gate positive/negative fixtures; report shape; proxy
  config sanity (unit-level; no live-instance tests in CI)

**Out of scope (do NOT touch):**

- The catalogue/audience UI and reference app (088)
- Publishing template packages to npm; a hosted "create" service;
  in-Praxis building (note §1 — possible later on-ramp, never required)
- Any CORS/cookie/CSRF change (STOP condition, not scope)

## Git workflow

- Branch: per operator direction (standing 2026-07-20 preference: `main`)
- Commit style: `Cross - Application Kit & Publish Gates`
- Do NOT commit without explicit operator approval.

## Steps (coarse — refine at execution)

1. Gate framework + gate set + fixtures (server-side; independent of the
   kit).
2. Template scaffold + dev proxy + agent instructions.
3. CLI: catalogue snapshot, typed client generation, push.
4. CI smoke wiring; docs (root AGENTS.md "Current Shape" + a builder
   quickstart under `docs/`).

## Test plan

Pinned invariants: **every gate has a fixture that fails it and a
near-miss that passes**, **a bundle containing a dev-token-shaped string
is rejected**, **the failure report is stable machine-readable JSON**,
**the template builds and passes its own gate dry-run in CI**, **the dev
proxy config sends the token only from the server side** (asserted by
config shape test).

## Done criteria

- [ ] Gates wired into publish; fixture suite green
- [ ] Template builds in CI without joining app workspaces
- [ ] CLI round-trip documented and smoke-tested against a local
      instance (manual step recorded honestly if not CI-able)
- [ ] Root AGENTS.md updated in the same change (repo shape changed)
- [ ] `000_README.md` row updated

## STOP conditions

- 082/084/085 contracts diverge from what the CLI/gates assume —
  reconcile before building on them.
- The template cannot be excluded from the workspace graph without
  tooling surgery — surface the options; do not silently add it to the
  pnpm workspace (D10 rejected that coupling for integrations; same
  logic).
- Any pressure to loosen CORS or accept browser-side dev tokens "just
  for local" — AGENTS.md forbids it; the proxy is the answer.
- Gate feedback would leak other workspaces'/apps' existence or
  server internals — reports name rules and the builder's own content
  only.

## Maintenance notes

- Gate set growth is a reviewed code change with fixtures — mirror the
  ARTIFACT_CSP_CDN_HOSTS discipline (050): no config-driven gates.
- The catalogue snapshot format is consumed by coding agents; version it
  (a `format` field) so refreshes are self-describing.
- Revisit triggers recorded: shared UI package (when the template's
  vendored baseline drifts painfully), `praxis create-app` generator
  (when clone-the-template friction is reported), builder-side CI recipe
  docs (first real external builder).
