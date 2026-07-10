# Plan 061: Integration provider packaging architecture (design note)

> **Executor instructions**: This is a design-note plan in the 029 mold —
> its deliverable is `docs/architecture/integration-packaging.md` plus
> reconciled sibling plans, not code. The code lands through the amended
> 037/041/042. When done, update the status row in
> `docs/plans/000_README.md`.

## Status

- **Priority**: P1
- **Effort**: S (documentation + plan amendments; the code cost is absorbed
  into 037/041/042 and is roughly neutral — the same modules, arranged
  behind a contract)
- **Risk**: LOW as a doc; it *removes* risk from Phase 4a by deciding
  packaging before any provider code exists
- **Depends on**: 029 (DONE). **Binds before 037 executes** — 037 lands the
  plugin contract + loader, and the fake provider becomes the first package
- **Category**: Phase 4a structural pre-decision (roadmap decision D10)
- **Planned at**: commit `71ef591`, 2026-07-07

## Decisions taken

1. **One registry, one dispatch choke point — modular population.** The
   roadmap's Target 1 (single typed registry, single audited choke point)
   stands. Packaging distributes *contribution*, never *enforcement*. The
   donor's failure was interconnection, not centralization.
2. **Backend: one package per provider under `apps/api/integrations/`**,
   each exporting a single `IntegrationProviderPlugin` (manifest +
   discovery function + tool definitions). A loader imports only the
   packages named in `INTEGRATIONS_ENABLED_PROVIDERS`, validates
   invariants at boot, and registers manifests/tools into the existing
   singular registries. Core never imports a specific provider; providers
   never import each other — enforced by an AST-walking test, not
   convention.
3. **Enablement is three-layered**: install-time (per-provider pyproject
   extras for SDK deps, storage-provider pattern), boot-time (the enabled
   list — an unlisted provider contributes nothing anywhere), runtime
   (manifest `enabled_setting` + the `is_tool_allowed` seam, with future
   per-workspace toggles on the same seam).
4. **Default-first tool UI.** Every provider tool must ship a complete
   server-declared `ToolPresentation`; the loader machine-checks it. The
   web default row renders any provider tool with zero provider frontend
   code. Custom web UI is opt-in polish, expected to be rare — this is the
   primary defense against a tool-UI registry monolith.
5. **Frontend: per-provider lazy modules under `apps/web/src/integrations/`**,
   one code-split chunk each, loaded only when the server catalog reports
   the provider (or its tools appear in a conversation). Progressive
   enhancement: the declarative default row renders until/unless a module
   arrives. Boundaries enforced with new dependency-cruiser rules;
   contract types published type-only via `src/integrations/contract.ts`.
6. **No pnpm workspace / separate npm packages for now** (rejected with a
   revisit trigger): workspace packages still land in the same SPA bundle,
   so they buy orchestration cost without runtime benefit. Directory law +
   dep-cruiser + lazy chunks deliver the actual goals. Revisit if provider
   UIs are ever distributed separately.
7. **No separate Python distributions for now** (same posture): the loader
   contract is entry-point-compatible, so externally installed provider
   wheels are a future additive change, not a v1 requirement.
8. **Graceful degradation**: write-time tool validation stays strict;
   run-time `build_runtime_tools` skips saved tool names absent from the
   catalog (logged + recorded in run metadata) instead of raising, so
   disabling a provider degrades agents rather than bricking every run
   that references its tools.

## Why this matters

The user-stated product reality: customers want disjoint provider subsets
(Google Ads + Meta; Gmail + Drive; Microsoft variants; everything). The
donor system forced everything on everyone and was retired partly for it.
Plans 037–042 as originally written put all provider code in shared
service/feature trees — correct engine design, but on the monolith
trajectory. Deciding packaging *now*, while zero provider code exists, is
free; deciding it after 041 lands three providers is a migration.

## Current state

Grounded by codebase exploration at `71ef591` (working tree):

- Backend seams that make this cheap: `@runtime_tool` +
  `RUNTIME_TOOL_CATALOG` with a `provider` namespace field and
  import-for-side-effects registration (`runtime/tools/registry.py`);
  `is_tool_allowed` permission stub (`runtime/tools/permissions.py`);
  `ToolPresentation` served via `GET /tools/presentations`; the storage
  package's optional-extras + guarded-import + factory pattern
  (`services/storage/providers/*`); `auto_mount` decoupling tool
  availability from agent config.
- Frontend seams: three-layer tool-row resolution (custom presenter
  registry → server-declared presentation → generic fallback) in
  `features/conversations/components/tool-call-row*.tsx`;
  `ToolPresentationEntry.provider` already flows to the client; route-level
  `lazyRouteComponent` is the only code-splitting today; **no pnpm
  workspace exists** (no root `pnpm-workspace.yaml` or `package.json`);
  dependency-cruiser rules are `^src/`-pathed and do not govern a
  `packages/` root.
- Phase 4a plans 037–042 are written, TODO, and place provider code in
  `services/integrations/providers/<key>/` +
  `runtime/tools/integrations/*.py` (api) and undifferentiated feature code
  (web).

## Scope

**In scope:**

- `docs/architecture/integration-packaging.md` (create — the design note)
- Amendment blocks in `docs/plans/{037,039,041,042}-*.md` binding their
  executors to the note (038/040 are engine-only and unaffected beyond
  their normal pre-flights)
- `docs/plans/000_README.md` row + dependency note;
  `docs/plans/000_MASTER_ROADMAP.md` decision D10 + Phase 4a note

**Out of scope:**

- Any code. The plugin contract, loader, settings, import-law test, web
  module registry, and dep-cruiser rules land inside 037/041/042 execution
  per their amendments.
- Re-packaging existing platform tools (files/planning/web_search/skills/
  delegation) — they are core harness, not integrations, and stay where
  they are.
- MCP tool packaging (deferred by D7; when it arrives it plugs into the
  same registry, not a second mechanism).

## Steps

1. Write `docs/architecture/integration-packaging.md` (§1–§8: problem,
   principles, centralized concerns, backend layout/contract/loader/
   import laws/degradation, frontend modules/boundaries, enablement
   matrix, donor-failure countermeasures, provider-N+1 checklist).
2. Add amendment blocks to 037, 039, 041, 042 naming the concrete deltas
   (fake provider location, plugin contract + loader in 037's engine,
   provider package paths in 041, web module seam + contract barrel in
   042, `discover_resources` reference in 039).
3. Update the roadmap (decision D10, Phase 4a lead-in) and the README
   table + dependency notes.

## Done criteria

- [ ] `docs/architecture/integration-packaging.md` exists and covers §1–§8
- [ ] 037/039/041/042 each carry an amendment block citing the note
- [ ] README row for 061 added; roadmap D10 recorded
- [ ] No code changed

## STOP conditions

- 037 (or any Phase 4a plan) has started executing — reconcile with the
  landed code first instead of amending plans that no longer match.

## Maintenance notes

- The note is living: 037/041/042 executors record deviations back into it
  in the same PR (029 rule).
- Future triggers recorded in the note: entry-point provider wheels
  (backend §4.3), pnpm workspace extraction (frontend §5.1), per-workspace
  provider toggles (§6).
