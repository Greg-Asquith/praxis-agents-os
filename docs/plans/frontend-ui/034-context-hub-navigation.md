# Plan 034: Sidebar consolidation — the Context hub

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Status**: TODO
- **Written**: 2026-07-27; re-verified and updated 2026-07-28 against
  HEAD `c65f946` (clean web working tree). Roadmap plan 049 (Memory) has
  landed and is committed; roadmap plans 050/051 (Artifacts) also landed
  after this plan was first written and added a ninth sidebar item —
  Artifacts is now part of this consolidation (maintainer decision,
  2026-07-28: Artifacts moves into the Context hub).
- **Priority**: P1
- **Effort**: M
- **Risk**: LOW — navigation config, one new static route, breadcrumb
  cases, and tests. No backend changes, no URL changes to existing pages,
  no data fetching on the new page.
- **Depends on**: nothing in this series (001–033 all landed). 049–051
  have landed, so no working-tree coordination is needed. Do not run
  concurrently with any plan editing `src/app/router.tsx`,
  `src/config/navigation.ts`, or `tests/config/navigation.test.ts`.

## Goal

The sidebar stops being a catalogue of system nouns. Nine entries (Home,
Agents, Skills, Memory, Knowledge Base, Files, Artifacts, Schedules,
Integrations) become five:

**Home · Agents · Context · Schedules · Integrations**

Skills, Memory, Knowledge Base, Files, Artifacts — and Context Groups,
today buried under Integrations — move behind a new **Context** hub page.
The hub is not just a link farm: each section gets a plain-language
explanation of *what it is* and *when to use it*, because the average
non-technical operator cannot be expected to know what a "Skill" is
versus a "Knowledge Base" — and today the sidebar demands they already
do. (Maintainer direction, 2026-07-27; Context Groups inclusion confirmed
2026-07-27 — "it all falls under context"; Artifacts inclusion confirmed
2026-07-28.)

After this plan:

1. **The sidebar reads as verbs of running the place, not features.**
   Home (what needs me), Agents (who works here), Context (what they
   know), Schedules (when they run), Integrations (what they can reach).
2. **`/context` is a calm explainer list** — one row per section in
   mental-model order (Skills, Knowledge Base, Memory, Files, Artifacts,
   Context Groups), each with its icon, name, a one-line "what it is",
   and a muted "Use it when…" line. The whole row is the link. Same
   calm-list shape plan 033 gave the integrations index.
3. **Existing URLs do not change.** `/skills`, `/memories`,
   `/knowledge`, `/files`, `/artifacts`, and
   `/integrations/context-groups` stay exactly where they are —
   bookmarks, in-app links, share links, and OAuth-adjacent flows are
   untouched. `/context` is purely additive.
4. **The sidebar knows where you are.** Context highlights while on the
   hub *or* any of its six sections — including
   `/integrations/context-groups`, which highlights Context, not
   Integrations (most-specific match wins).
5. **Breadcrumbs re-parent.** The six sections crumb as
   `Context > {Section}` with Context linked back to the hub, replacing
   today's generic `Home > {Segment}` fallback (which also mislabels
   Knowledge Base as "Knowledge" and Memory as "Memories", and drops the
   detail segment on `/artifacts/{id}`).

Schedules and Integrations remain two separate sidebar entries
(maintainer confirmation, 2026-07-27).

## Current state (verified 2026-07-28 at `c65f946`)

- `src/config/navigation.ts` (95 lines): `mainNavigation` array of nine
  items at lines 32–87 — Home (`LayoutDashboardIcon`), Agents
  (`BotIcon`), Skills (`SparklesIcon`), Memory (`BrainIcon`), Knowledge
  Base (`LibraryIcon`), Files (`FilesIcon`), Artifacts
  (`FileStackIcon`), Schedules (`CalendarClockIcon`), Integrations
  (`PlugIcon`); `NavigationItem` union (enabled/disabled shapes,
  optional `managerOnly`) at lines 16–30; `navigationItemsForRole`
  filter at lines 89–91. No item currently uses `disabled: true` or
  `managerOnly`; no `activeWhen` field exists anywhere yet.
- `src/components/shell/primary-navigation.tsx`: renders the filtered
  items; `isNavigationActive` at lines 58–64 does exact-match for `/` and
  prefix-match for everything else. Both the desktop sidebar
  (`app-shell.tsx` line 46) and the mobile drawer (`mobile-menu.tsx`
  line 105, `density="comfortable"`) render `PrimaryNavigation`, so both
  inherit the change with no extra work.
- `src/components/shell/app-breadcrumbs.tsx`: `getBreadcrumbs`
  (lines 116–212) has explicit cases for agents, conversations,
  schedules, integrations, workspaces, workspace-settings, and profile;
  **skills, memories, knowledge, files, and artifacts fall through** to
  the generic `[Home, titleFromSegment(section)]` fallback at
  lines 208–211 — producing "Knowledge" and "Memories" rather than the
  pages' actual titles ("Knowledge Base", "Memory"), and dropping the
  detail segment on `/artifacts/{id}`. The `BreadcrumbRoute` union
  (lines 17–24) will need `/context` added. `getIntegrationProviderKey`
  (lines 241–252) already special-cases `context-groups` at line 246.
- `src/app/router.tsx`: the five section routes — `skillsRoute` +
  new/detail (lines 225–250), `memoriesRoute` (lines 252–269),
  `filesRoute` (lines 271–276), `artifactsRoute` +
  `artifactDetailRoute` (lines 278–300, paths `/artifacts` and
  `/artifacts/$artifactId`), `knowledgeRoute` + document detail
  (lines 302–318). `homeRoute` (lines 109–113) is the precedent for a
  static shell-level page whose component lives in `src/routes/` rather
  than a feature directory. Route registration is at lines 462–493.
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
  - Artifacts: "Preview, revise, restore, and share durable work created
    by your agents."
- Tests: `tests/config/navigation.test.ts` asserts the nine-item list
  (label + `to` only, `it.each` over null/member/admin/owner);
  `tests/app/router.test.ts` asserts conversation-route pending
  behavior and that `routesByPath["/integrations"]` is defined.
- **Context Groups** — the hub's sixth destination — lives at
  `/integrations/context-groups` (`integrationContextGroupsRoute`,
  router.tsx lines 345–363). `ContextGroupsSection` is consumed only by
  that page's route (`context-groups-route.tsx`); the integrations
  index (`integrations-route.tsx` lines 21–24) links to it via a
  `PageHeader` action button with `Layers3Icon`. Its breadcrumb
  currently reads `Integrations > Context Groups` via the generic
  integrations-detail case.

## Design decisions

1. **Hub route is `/context`**, component at `src/routes/context.tsx`
   (precedent: `home.tsx`). It is static — no loader, no queries, no
   counts in v1. It must render instantly; it is a signpost, not a
   dashboard. Counts ("12 skills") are a possible later garnish, not
   part of this plan.
2. **Nav active-state**: extend the enabled `NavigationItem` shape with
   an optional `activeWhen?: readonly string[]` (extra path prefixes
   that light the item up). The Context item sets `activeWhen:
   ["/skills", "/memories", "/knowledge", "/files", "/artifacts",
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
   `BrainIcon`, Files `FilesIcon`, Artifacts `FileStackIcon`, Context
   Groups `Layers3Icon` (the icon the integrations index already uses
   for its Context Groups button). Remove the now-unused icon imports
   from `navigation.ts`.
4. **Hub rows, not cards** (plan 011 de-carded pages; plan 033's app
   list is the pattern). Each row: section icon in a muted well, name,
   the "what it is" line, a second muted "Use it when…" line, and a
   right-aligned chevron. The full row is a `Link`. Rows are
   divider-separated, keyboard-focusable with a visible ring, and read
   correctly in both themes.
5. **Row order is the operator's mental model, not the old sidebar
   order**: Skills (how agents work), Knowledge Base (what they can look
   up), Memory (what they've learned), Files (what you share with them),
   Artifacts (what they produce), Context Groups (which connected
   accounts they work with — last, as the most advanced and only
   meaningful once integrations are connected). The Context Groups row
   links to the existing `/integrations/context-groups` page; the page
   itself is not moved or changed by this plan.
6. **Breadcrumbs**: add explicit cases to `getBreadcrumbs`:
   - `/context` → `Context`
   - `/skills` → `Context > Skills`; `/skills/new` →
     `Context > Skills > New Skill`; `/skills/$skillId` →
     `Context > Skills > Skill`
   - `/knowledge` → `Context > Knowledge Base`;
     `/knowledge/$documentId` → `Context > Knowledge Base > Document`
   - `/memories` → `Context > Memory`
   - `/files` → `Context > Files`
   - `/artifacts` → `Context > Artifacts`; `/artifacts/$artifactId` →
     `Context > Artifacts > Artifact`
   - `/integrations/context-groups` → `Context > Context Groups`
     (an explicit case *before* the generic integrations-detail case,
     which currently produces `Integrations > Context Groups`)
   Intermediate crumbs link (`Context` → `/context`, section → its
   list); the last crumb never links, matching existing behavior. Do
   not add name-fetching for skill/document/artifact details — static
   labels match today's depth of information; entity-name crumbs are a
   follow-up if ever wanted.
7. **The five section pages keep their own `PageHeader`s unchanged.**
   The hub explains; the pages still introduce themselves. No copy churn
   inside the sections.

## Copy (authoritative baseline)

Plain outcome language, per the target-user decision (plans 015–018). Do
not say "retrieval", "vector", "durable", or "context window" anywhere on
this page.

**Page header** — title `Context`, description:

> Everything your agents can draw on — how to do the work, what to look
> up, what they've learned, the files you share, the work they produce,
> and which accounts they work with.

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
- What: Working documents you and your agents share — things you upload
  for agents to read and use.
- When: Use it for the raw materials of a task — like a spreadsheet to
  process or a brief to work from.

**Artifacts**
- What: Finished work agents produce, kept in versions you can review,
  restore, and share.
- When: Come here to find what agents have made — like a report you can
  send on with a share link.

**Context Groups**
- What: Named sets of connected accounts and resources that tell an
  agent exactly which ones to work with.
- When: Use it when different agents or schedules should use different
  accounts — like one agent per client.

Wording may be polished during review, but the register (plain, outcome,
second person) and the what/when structure are fixed.

## Steps

1. **`src/config/navigation.ts`** — replace the nine-item array with
   the five items; add `activeWhen` to the enabled `NavigationItem`
   shape; Context points to `/context` with the six `activeWhen`
   prefixes; prune unused icon imports, add `LibraryBigIcon`.
2. **`src/components/shell/primary-navigation.tsx`** — replace per-item
   `isNavigationActive` with the single longest-prefix-wins selection
   (decision 2).
3. **`src/routes/context.tsx`** — the hub page (decisions 4–5, Copy
   section). `PageHeader` + the six link rows. No feature directory, no
   API module, no loader.
4. **`src/app/router.tsx`** — add `contextRoute`
   (`getParentRoute: appRoute`, `path: "/context"`,
   `lazyRouteComponent` like `homeRoute`) and register it in
   `appRoute.addChildren`.
5. **`src/components/shell/app-breadcrumbs.tsx`** — the explicit cases
   from decision 6, placed before the generic fallback; add `/context`
   to the `BreadcrumbRoute` union.
6. **Tests** —
   - `tests/config/navigation.test.ts`: update the expected list to the
     five items; add coverage that the Context item carries the six
     `activeWhen` prefixes.
   - Active-state coverage for the longest-prefix selection (extend or
     add a test beside the existing navigation test): `/skills/abc`,
     `/memories`, and `/artifacts/abc` activate Context;
     `/integrations/context-groups` activates Context and not
     Integrations; `/integrations/gmail` activates Integrations;
     `/agents` does not activate Context; `/context` does.
   - `tests/app/router.test.ts`: assert `routesByPath["/context"]` is
     defined.
7. **Sweep** — `grep -rn
   '"/skills"\|"/memories"\|"/knowledge"\|"/files"\|"/artifacts"' src/`
   and confirm every remaining link still makes sense now that the
   sections are one level deeper in the IA (they all keep working —
   URLs are unchanged — this is a copy/UX sanity check, not a rewrite).
   Expect hits in feature routes and tool-outcome presenters; change
   nothing unless a label literally says "in the sidebar".

## Verification

- `cd apps/web && pnpm check` passes (typecheck, eslint zero-warnings,
  vitest, prettier, knip, depcruise, build).
- Visual QA against `pnpm dev` (API up via `make dev`), **both themes**:
  - Sidebar shows exactly Home, Agents, Context, Schedules,
    Integrations — desktop and mobile drawer.
  - `/context` renders the six rows with the plan copy; every row
    navigates; focus rings visible; row contrast ≥ 4.5:1 in both
    themes.
  - Context is highlighted on `/context`, `/skills`, `/skills/new`,
    `/memories`, `/knowledge`, `/knowledge/{id}`, `/files`,
    `/artifacts`, `/artifacts/{id}`, and
    `/integrations/context-groups`; it is not highlighted on `/`,
    `/agents`, `/integrations`, or `/integrations/{providerKey}`.
    Integrations is highlighted on `/integrations` and provider detail
    pages but not on `/integrations/context-groups`.
  - Breadcrumbs on `/skills` read `Context > Skills` with Context
    linking to the hub; `/knowledge` says "Knowledge Base", `/memories`
    says "Memory"; `/artifacts` reads `Context > Artifacts`;
    `/integrations/context-groups` reads `Context > Context Groups`.

## STOP conditions

- `router.tsx`, `navigation.ts`, or the navigation test have drifted
  beyond the `c65f946` shape described above in a way that conflicts
  structurally (not just line numbers) — e.g. a tenth sidebar item has
  appeared. Reconcile against live code first; stop if the
  reconciliation would change this plan's decisions.
- You find yourself renaming Context Groups or Artifacts, moving their
  routes, or editing those pages themselves — the hub rows link to the
  pages as they stand; stop and report instead.

## Non-goals / out of scope

- **No URL changes or redirects** for any section, Context Groups
  included — its route stays `/integrations/context-groups` and this
  plan only links to it.
- **No changes to the Context Groups page or the Integrations index.**
  The integrations index keeps its Context Groups header button
  (`integrations-route.tsx`); Context Groups being reachable from both
  surfaces is accepted for now. If the double placement proves
  confusing, removing the integrations-index button — or moving the
  route under `/context` — is a follow-up plan.
- **No counts or live data on the hub** (v1 is static; counts are a
  possible follow-up).
- **No entity-name breadcrumbs** for skill/document details.
- **No sidebar reordering beyond the consolidation** — Home, Agents,
  Context, Schedules, Integrations, in that order (Schedules and
  Integrations confirmed as separate entries), and the user-menu
  contents (plan 009) are untouched.
