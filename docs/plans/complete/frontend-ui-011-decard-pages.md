# Plan 011: De-card pages — plain content surfaces

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Priority**: P1
- **Effort**: M
- **Risk**: MED — visual only, no data or routing changes, but one shared
  primitive (`responsive-list.tsx`) feeds eleven feature tables, so the
  mobile flattening needs a per-feature QA sweep.
- **Depends on**: 001, 002, 007 (all DONE). Disjoint from 010's shell
  files; safe to run in parallel with it.

## Goal

Two symptoms, one root cause (maintainer, 2026-07-16, with screenshots):

1. **Every list page says its name twice.** The `PageHeader` renders
   "Schedules / Create and monitor unattended agent runs across this
   workspace." — and immediately below it a `Card` renders "Workspace
   schedules" with the *identical* description. The card adds chrome and
   repetition, no information.
2. **Card-in-card hell on mobile.** Inside that page `Card`, the mobile
   table branch renders each row as `ResponsiveListItem` — itself a
   `bg-card rounded-lg border` box. Bordered box inside bordered box,
   with badges as a third layer of pills.

Fix: kill the wrapper cards and display content plainly. The `PageHeader`
is the only page title; tables and lists sit directly in the page flow;
the mobile list flattens to divider-separated rows. `Card` remains for
surfaces that genuinely group (auth card, dialogs, detail forms) — this
plan removes only page-level content wrappers.

## Current state (verified 2026-07-16 at `d1c4a89`)

- `src/components/shell/page-header.tsx:11-23` — `PageHeader` renders
  `h1` (`font-heading text-2xl font-semibold`) + muted description +
  `actions` slot. Every page below already uses it.
- Five list pages wrap their table in a `Card` whose `CardHeader`
  restates the page header (none of these five has a `CardAction`):
  - `src/features/schedules/routes/schedules-route.tsx:33-43` —
    "Workspace schedules" + description identical to line 29.
  - `src/features/agents/routes/agents-route.tsx:33-43` — "Workspace
    agents" + near-duplicate description.
  - `src/features/skills/routes/skills-route.tsx:31-41` — "Workspace
    skills" + near-duplicate description.
  - `src/features/files/routes/files-route.tsx:38-54` — "Workspace
    files" + near-duplicate description.
  - `src/features/workspaces/routes/workspaces-route.tsx:22-34` —
    "{n} workspace(s)" + near-duplicate description.
- `src/features/conversations/routes/conversations-route.tsx:46-68` —
  `Card size="sm"` with a count title ("{n} conversations"), "Sorted by
  recent activity.", and a `CardAction` "Start new" button that
  *duplicates* the PageHeader's "New conversation" action (line 36).
- `src/routes/home.tsx:117-138` — `DashboardPanel` wraps each dashboard
  section ("Needs attention", "Recent conversations") in
  `Card size="sm"` with a `border-b` header, count description, and
  optional `CardAction`. These titles are *not* duplicates — the
  sections keep their headings, just without card chrome.
- `src/components/ui/responsive-list.tsx:18-30` — `ResponsiveListItem`
  is `bg-card text-card-foreground rounded-lg border p-3` (the inner
  card); `ResponsiveList` (line 7) is `flex flex-col gap-3 md:hidden`.
  Consumers (all eleven): `schedules-table.tsx:60`,
  `schedule-run-history.tsx:62`, `agents-table.tsx:56`,
  `skills-table.tsx:46`, `skill-documents-section.tsx:260`,
  `files-table.tsx:133`, `workspaces-table.tsx:47`,
  `members-table.tsx:42`, `invitations-table.tsx:55`,
  `audit-events-table.tsx:58`, `security-events-table.tsx:55`.
- Already plain (leave untouched): `workspace-settings-route.tsx`
  (Tabs) and `profile-route.tsx` (bare forms).

## Steps

### 1. Unwrap the five list pages

In each of the five routes, delete the `Card`/`CardHeader`/`CardTitle`/
`CardDescription`/`CardContent` wrapper and render the table component
directly in the existing `flex flex-col gap-6` stack. Remove the now-unused
card imports. The duplicated titles and descriptions are deleted outright —
nothing in those headers is preserved. If a route's card block contains
real content beyond the duplicate header (e.g. files' upload toolbar),
keep that content in the page flow; only the chrome and the repetition die.

The workspaces count title ("{n} workspace(s)") is dropped, not relocated —
the table shows its rows; a count adds nothing.

### 2. Unwrap the conversations page

`conversations-route.tsx`: delete the card. The count title, "Sorted by
recent activity.", and the duplicate "Start new" `CardAction` all go —
the PageHeader's "New conversation" button is the one action. Render
`ConversationList` (or the empty state) directly. `ConversationList`
rows already carry their own hover/rounded styling and remain readable
on the plain canvas.

### 3. Flatten the dashboard panels

`home.tsx`: replace `DashboardPanel`'s card with a plain section — keep
the component boundary and the two-column grid at line 52. Each section
renders a slim heading row (title as `h2` `text-sm font-medium`, the
count description muted beside or below it, `action` right-aligned) and
its content directly beneath. No border, no card background. Keep the
existing empty states.

### 4. Flatten the mobile list primitive

`src/components/ui/responsive-list.tsx` — one change, eleven consumers:

- `ResponsiveListItem`: drop `bg-card text-card-foreground rounded-lg
  border`, keep the padding as vertical rhythm (`py-3` — first/last
  spacing per visual QA) and keep the
  `[contain-intrinsic-size:auto_96px] [content-visibility:auto]`
  perf classes.
- `ResponsiveList`: switch `gap-3` to `divide-y` so rows separate by
  hairline dividers instead of boxes.

Then QA every consumer at a mobile width. Watch for: full-width
`outline` buttons inside rows (e.g. schedules' "Configure",
`schedules-table.tsx:117`) still reading as controls; badge rows not
colliding with dividers; the `sm:grid-cols-2` meta grids still aligned.
Per-consumer padding fixes are fine; do not reintroduce borders.

### 5. Sweep for stragglers

Grep `features/` and `routes/` for remaining `Card` imports. Any card
whose header merely restates the page or section it sits in gets the
same treatment. Cards that genuinely group content — the auth card,
dialog bodies, detail-page form sections — stay. When in doubt, the
test is: does the card's title tell the user something the page header
did not?

### 6. Verify

- `cd apps/web && pnpm check` passes (knip will flag unused card imports
  if any were missed).
- Visual QA against `pnpm dev`, both themes, desktop and ~375px mobile:
  every list page shows exactly one title; no bordered box wraps the
  tables; mobile rows are flat divider-separated blocks (one visual
  layer, badges included); dashboard sections keep their headings and
  actions; empty states still centered and legible on the plain canvas.
- Confirm no page scrolls horizontally at mobile widths — the tables'
  `hidden md:block` desktop branch must stay hidden and the mobile
  branch must contain its content.

## STOP conditions

- A table turns out to depend on `CardContent` padding or overflow
  behavior for horizontal containment, and fixing it needs more than a
  local `overflow-x-auto`/padding wrapper — stop and report.
- Flattening `ResponsiveListItem` makes any of the eleven consumers
  structurally unreadable (not just "needs padding tweaks") — stop and
  report rather than forking the primitive per feature.

## Execution record

- Removed the redundant page-level card wrappers from schedules, agents,
  skills, files, workspaces, and conversations. Each page now has one title
  and one primary action, supplied by its existing `PageHeader`.
- Reworked the two dashboard panels as plain sections with compact heading,
  count, and action rows while preserving their two-column layout, lists, and
  empty states.
- Flattened `ResponsiveList` to divider-separated mobile rows and retained its
  intrinsic-size and `content-visibility` performance classes. Static review
  confirmed all eleven consumers retain their controls, badges, metadata
  grids, mobile-only branch, and wrap/min-width containment without local row
  wrapper overrides.
- The card sweep left only surfaces with distinct grouping responsibilities,
  including authentication, invitation acceptance, settings subsections, and
  detail forms. No API, FastAPI, Pydantic AI, agent runtime, data, routing,
  query-key, or mutation behavior changed.
- `pnpm check` passed on 2026-07-16: typecheck, ESLint, 89 Vitest tests,
  Prettier, Knip, dependency-cruiser, and the production build. Browser
  automation was not used at the maintainer's direction; responsive and theme
  behavior were verified through shared semantic classes, breakpoint and
  overflow source review, consumer-by-consumer static inspection, and the
  production build.
