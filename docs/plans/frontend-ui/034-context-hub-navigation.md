# Plan 034: Sidebar consolidation — the Context hub

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Status**: TODO
- **Written**: 2026-07-27 (anchors verified against the working tree at
  `87d4953`, which carries in-flight roadmap plan 049 changes — the Memory
  nav item, `/memories` route, and `src/features/memories/` exist only in
  that working tree. This plan builds on that working tree, not the bare
  commit; the live code wins on mechanics, this plan wins on structure and
  copy.)
- **Priority**: P1
- **Effort**: M
- **Risk**: LOW — navigation config, one new static route, breadcrumb
  cases, and tests. No backend changes, no URL changes to existing pages,
  no data fetching on the new page.
- **Depends on**: nothing in this series (001–033 all landed). Coordinate
  with the in-flight roadmap plan 049 working tree, which touches
  `src/app/router.tsx`, `src/config/navigation.ts`, and
  `tests/config/navigation.test.ts` — the same files this plan edits. Do
  not run concurrently with any plan editing those files.

## Goal

The sidebar stops being a catalogue of system nouns. Eight entries (Home,
Agents, Skills, Memory, Knowledge Base, Files, Schedules, Integrations)
become five:

**Home · Agents · Context · Schedules · Integrations**

Skills, Memory, Knowledge Base, Files — and Context Groups, today buried
under Integrations — move behind a new **Context** hub page. The hub is
not just a link farm: each section gets a plain-language explanation of
*what it is* and *when to use it*, because the average non-technical
operator cannot be expected to know what a "Skill" is versus a
"Knowledge Base" — and today the sidebar demands they already do.
(Maintainer direction, 2026-07-27; Context Groups inclusion confirmed
2026-07-27 — "it all falls under context".)

After this plan:

1. **The sidebar reads as verbs of running the place, not features.**
   Home (what needs me), Agents (who works here), Context (what they
   know), Schedules (when they run), Integrations (what they can reach).
2. **`/context` is a calm explainer list** — one row per section in
   mental-model order (Skills, Knowledge Base, Memory, Files, Context
   Groups), each with its icon, name, a one-line "what it is", and a
   muted "Use it when…" line. The whole row is the link. Same calm-list
   shape plan 033 gave the integrations index.
3. **Existing URLs do not change.** `/skills`, `/memories`,
   `/knowledge`, `/files`, and `/integrations/context-groups` stay
   exactly where they are — bookmarks, in-app links, and OAuth-adjacent
   flows are untouched. `/context` is purely additive.
4. **The sidebar knows where you are.** Context highlights while on the
   hub *or* any of its five sections — including
   `/integrations/context-groups`, which highlights Context, not
   Integrations (most-specific match wins).
5. **Breadcrumbs re-parent.** The five sections crumb as
   `Context > {Section}` with Context linked back to the hub, replacing
   today's generic `Home > {Segment}` fallback (which also mislabels
   Knowledge Base as "Knowledge" and Memory as "Memories").

Schedules and Integrations remain two separate sidebar entries
(maintainer confirmation, 2026-07-27).

## Current state (verified 2026-07-27 at `87d4953` + plan-049 working tree)

- `src/config/navigation.ts` (89 lines): `mainNavigation` array of eight
  items at lines 31–80; `NavigationItem` union (enabled/disabled shapes,
  optional `managerOnly`) at lines 15–29; `navigationItemsForRole` filter
  at lines 82–84. No item currently uses `disabled: true` or
  `managerOnly`.
- `src/components/shell/primary-navigation.tsx`: renders the filtered
  items; `isNavigationActive` at lines 58–64 does exact-match for `/` and
  prefix-match for everything else. Both the desktop sidebar
  (`app-shell.tsx` line 46) and the mobile drawer (`mobile-menu.tsx`
  line 105, `density="comfortable"`) render `PrimaryNavigation`, so both
  inherit the change with no extra work.
- `src/components/shell/app-breadcrumbs.tsx`: `getBreadcrumbs` has
  explicit cases for agents, conversations, schedules, integrations,
  workspaces, workspace-settings, and profile; **skills, memories,
  knowledge, and files fall through** to the generic
  `[Home, titleFromSegment(section)]` fallback at lines 207–210 —
  producing "Knowledge" and "Memories" rather than the pages' actual
  titles ("Knowledge Base", "Memory").
- `src/app/router.tsx`: the four section routes — `skillsRoute` +
  new/detail (lines 223–248), `memoriesRoute` (lines 250–267, plan-049
  working tree), `filesRoute` (lines 269–274), `knowledgeRoute` +
  document detail (lines 276–292). `homeRoute` (lines 107–111) is the
  precedent for a static shell-level page whose component lives in
  `src/routes/` rather than a feature directory.
- Existing per-page `PageHeader` descriptions — the tone the hub copy
  must match:
  - Skills: "Package reusable instructions and reference documents for
    agents."
  - Memory: "Review, correct, and remove durable details agents have
    saved while working."
  - Knowledge Base: "Build a searchable source of truth that agents can
    retrieve and cite."
  - Files: "Upload, inspect, and restore durable files shared with
    agents."
- Tests: `tests/config/navigation.test.ts` asserts the eight-item list
  per role; `tests/app/router.test.ts` is a route-registration smoke
  test.
- **Context Groups** — the hub's fifth destination — lives at
  `/integrations/context-groups` (`integrationContextGroupsRoute`,
  router.tsx lines 319–333) and is also surfaced as
  `ContextGroupsSection` on the integrations index (plan 033). Its
  breadcrumb currently reads `Integrations > Context Groups` via the
  generic integrations-detail case.

## Design decisions

1. **Hub route is `/context`**, component at `src/routes/context.tsx`
   (precedent: `home.tsx`). It is static — no loader, no queries, no
   counts in v1. It must render instantly; it is a signpost, not a
   dashboard. Counts ("12 skills") are a possible later garnish, not
   part of this plan.
2. **Nav active-state**: extend the enabled `NavigationItem` shape with
   an optional `activeWhen?: readonly string[]` (extra path prefixes
   that light the item up). The Context item sets `activeWhen:
   ["/skills", "/memories", "/knowledge", "/files",
   "/integrations/context-groups"]`. Because that last prefix nests
   under the Integrations item's `/integrations`, per-item prefix
   matching would light both — so the active item becomes a single
   selection: compute the longest matching prefix across all items
   (`item.to` plus `activeWhen`, `pathname === prefix ||
   pathname.startsWith(`${prefix}/`)`) and highlight only that item's
   entry. `/` keeps its exact-match special case. Keep the logic in
   `primary-navigation.tsx`; do not build a matcher abstraction.
3. **Context icon**: `LibraryBigIcon` (lucide). Distinct from the
   section icons, which keep their identities *inside the hub rows*:
   Skills `SparklesIcon`, Knowledge Base `LibraryIcon`, Memory
   `BrainIcon`, Files `FilesIcon`, Context Groups `LayersIcon`. Remove
   the now-unused icon imports from `navigation.ts`.
4. **Hub rows, not cards** (plan 011 de-carded pages; plan 033's app
   list is the pattern). Each row: section icon in a muted well, name,
   the "what it is" line, a second muted "Use it when…" line, and a
   right-aligned chevron. The full row is a `Link`. Rows are
   divider-separated, keyboard-focusable with a visible ring, and read
   correctly in both themes.
5. **Row order is the operator's mental model, not the old sidebar
   order**: Skills (how agents work), Knowledge Base (what they can look
   up), Memory (what they've learned), Files (what you share with them),
   Context Groups (which connected accounts they work with — last, as
   the most advanced and only meaningful once integrations are
   connected). The Context Groups row links to the existing
   `/integrations/context-groups` page; the page itself is not moved or
   changed by this plan.
6. **Breadcrumbs**: add explicit cases to `getBreadcrumbs`:
   - `/context` → `Context`
   - `/skills` → `Context > Skills`; `/skills/new` →
     `Context > Skills > New Skill`; `/skills/$skillId` →
     `Context > Skills > Skill`
   - `/knowledge` → `Context > Knowledge Base`;
     `/knowledge/$documentId` → `Context > Knowledge Base > Document`
   - `/memories` → `Context > Memory`
   - `/files` → `Context > Files`
   - `/integrations/context-groups` → `Context > Context Groups`
     (an explicit case *before* the generic integrations-detail case,
     which currently produces `Integrations > Context Groups`)
   Intermediate crumbs link (`Context` → `/context`, section → its
   list); the last crumb never links, matching existing behavior. Do
   not add name-fetching for skill/document details — static labels
   match today's depth of information; entity-name crumbs are a
   follow-up if ever wanted.
7. **The four section pages keep their own `PageHeader`s unchanged.**
   The hub explains; the pages still introduce themselves. No copy churn
   inside the sections.

## Copy (authoritative baseline)

Plain outcome language, per the target-user decision (plans 015–018). Do
not say "retrieval", "vector", "durable", or "context window" anywhere on
this page.

**Page header** — title `Context`, description:

> Everything your agents can draw on — how to do the work, what to look
> up, what they've learned, the files you share, and which accounts
> they work with.

**Skills**
- What: Step-by-step instructions that teach agents how to do a
  repeatable job your way.
- When: Use it when an agent should do a task the same way every time —
  like producing the weekly report in your format.

**Knowledge Base**
- What: A searchable library of reference documents agents look up and
  cite when they answer.
- When: Use it for facts agents should check rather than guess —
  policies, product details, pricing.

**Memory**
- What: Details agents have saved while working, so they don't ask
  twice.
- When: Come here to review what agents have remembered, correct
  anything wrong, and remove what no longer applies.

**Files**
- What: Documents you and your agents share — things you upload and
  things agents produce.
- When: Use it for working documents — a spreadsheet to process, or a
  report an agent wrote for you.

**Context Groups**
- What: Named sets of connected accounts and resources that tell an
  agent exactly which ones to work with.
- When: Use it when different agents or schedules should use different
  accounts — like one agent per client.

Wording may be polished during review, but the register (plain, outcome,
second person) and the what/when structure are fixed.

## Steps

1. **`src/config/navigation.ts`** — replace the eight-item array with
   the five items; add `activeWhen` to the enabled `NavigationItem`
   shape; Context points to `/context` with the five `activeWhen`
   prefixes; prune unused icon imports, add `LibraryBigIcon`.
2. **`src/components/shell/primary-navigation.tsx`** — replace per-item
   `isNavigationActive` with the single longest-prefix-wins selection
   (decision 2).
3. **`src/routes/context.tsx`** — the hub page (decisions 4–5, Copy
   section). `PageHeader` + the five link rows. No feature directory, no
   API module, no loader.
4. **`src/app/router.tsx`** — add `contextRoute`
   (`getParentRoute: appRoute`, `path: "/context"`,
   `lazyRouteComponent` like `homeRoute`) and register it in
   `appRoute.addChildren`.
5. **`src/components/shell/app-breadcrumbs.tsx`** — the explicit cases
   from decision 6, placed before the generic fallback.
6. **Tests** —
   - `tests/config/navigation.test.ts`: update the expected list to the
     five items; add coverage that the Context item carries the five
     `activeWhen` prefixes.
   - Active-state coverage for the longest-prefix selection (extend or
     add a test beside the existing navigation test): `/skills/abc` and
     `/memories` activate Context; `/integrations/context-groups`
     activates Context and not Integrations; `/integrations/gmail`
     activates Integrations; `/agents` does not activate Context;
     `/context` does.
   - `tests/app/router.test.ts`: assert `routesByPath["/context"]` is
     defined.
7. **Sweep** — `grep -rn '"/skills"\|"/memories"\|"/knowledge"\|"/files"'
   src/` and confirm every remaining link still makes sense now that the
   sections are one level deeper in the IA (they all keep working —
   URLs are unchanged — this is a copy/UX sanity check, not a rewrite).
   Expect hits in feature routes, home quick actions, and tool-outcome
   presenters; change nothing unless a label literally says "in the
   sidebar".

## Verification

- `cd apps/web && pnpm check` passes (typecheck, eslint zero-warnings,
  vitest, prettier, knip, depcruise, build).
- Visual QA against `pnpm dev` (API up via `make dev`), **both themes**:
  - Sidebar shows exactly Home, Agents, Context, Schedules,
    Integrations — desktop and mobile drawer.
  - `/context` renders the five rows with the plan copy; every row
    navigates; focus rings visible; row contrast ≥ 4.5:1 in both
    themes.
  - Context is highlighted on `/context`, `/skills`, `/skills/new`,
    `/memories`, `/knowledge`, `/knowledge/{id}`, `/files`, and
    `/integrations/context-groups`; it is not highlighted on `/`,
    `/agents`, `/integrations`, or `/integrations/{providerKey}`.
    Integrations is highlighted on `/integrations` and provider detail
    pages but not on `/integrations/context-groups`.
  - Breadcrumbs on `/skills` read `Context > Skills` with Context
    linking to the hub; `/knowledge` says "Knowledge Base", `/memories`
    says "Memory"; `/integrations/context-groups` reads
    `Context > Context Groups`.

## STOP conditions

- `router.tsx`, `navigation.ts`, or the navigation test have drifted
  beyond the plan-049 working-tree shape described above in a way that
  conflicts structurally (not just line numbers) — reconcile against
  live code first; stop if the reconciliation would change this plan's
  decisions. (Plan 049 lands before this plan runs — maintainer,
  2026-07-27.)
- You find yourself renaming Context Groups, moving its route, or
  editing the Context Groups page itself — the hub row links to the
  page as it stands; stop and report instead.

## Non-goals / out of scope

- **No URL changes or redirects** for any section, Context Groups
  included — its route stays `/integrations/context-groups` and this
  plan only links to it.
- **No changes to the Context Groups page or the Integrations index.**
  The `ContextGroupsSection` on the integrations index (plan 033) stays
  where it is; Context Groups being reachable from both surfaces is
  accepted for now. If the double placement proves confusing, removing
  the integrations-index section — or moving the route under
  `/context` — is a follow-up plan.
- **No counts or live data on the hub** (v1 is static; counts are a
  possible follow-up).
- **No entity-name breadcrumbs** for skill/document details.
- **No sidebar reordering beyond the consolidation** — Home, Agents,
  Context, Schedules, Integrations, in that order (Schedules and
  Integrations confirmed as separate entries), and the user-menu
  contents (plan 009) are untouched.
