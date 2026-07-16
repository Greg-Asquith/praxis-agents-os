# Plan 002: App shell — inset canvas (visual only)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Scope constraint (settled decision — do not revisit)

This plan is **visual only**. The maintainer explicitly rejected copying the
reference's information architecture (2026-07-16):

- The sidebar menu content does not change: same items, same order, same
  sections, same "Conversations" title, same brand header, same footer.
- The workspace switcher stays in the top bar; it does not move into the
  sidebar.
- No breadcrumb restructure, no quick-action rows, no Agents section in
  the sidebar, no "Recents" rename, no search entry.

What this plan does change is the *shape and finish*: the page backdrop,
the inset rounded content canvas, and the styling of the pieces that
already exist.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM — the shell wraps every authenticated screen; the
  conversation route's own-scroll contract (`overflow-hidden` main) must
  survive.
- **Depends on**: 001 (tokens).

## Goal

Adopt the reference's shell *shape*: the whole page sits on the warm
sidebar gray, and the content area becomes a white rounded canvas inset
from the top/right/bottom edges, with the existing header row (mobile
menu + breadcrumbs + workspace switcher) rendered inside the canvas
instead of as a full-width sticky translucent bar. Same navigation, same
components, different finish.

## Current state (verified at `158de0b`)

- `src/components/shell/app-shell.tsx:41` — root grid
  `bg-background … md:grid-cols-[280px_minmax(0,1fr)]`; `:42` sidebar
  `bg-sidebar … border-r`; `:57` main column; `:58` sticky translucent
  topbar `h-14 … border-b … backdrop-blur` holding `MobileMenu` +
  `AppBreadcrumbs` left and `WorkspaceSwitcher` right; `:76-81` `<main>`
  gets `overflow-hidden` for conversation-detail paths, else
  `overflow-y-auto p-4 md:p-6`.
- `sidebar-header.tsx` — "P" brand badge + "Praxis / Agents OS" text,
  `h-14 border-b`.
- `src/config/navigation.ts:30-73` — flat nav: Home, Agents, Skills, Files,
  Schedules, Workspaces, Settings; rendered by `primary-navigation.tsx`
  (rows `h-8 rounded-lg px-2 text-sm`, active = `bg-sidebar-accent`).
- `sidebar-conversations.tsx` — "Conversations" section, 50 most recent,
  rows with title + agent label + glyphs (`ShieldAlertIcon` in destructive
  red for needs-approval).
- `app-layout-fallback.tsx` mirrors the current shell for the Suspense
  skeleton, and must be updated in lockstep.

## Decisions taken

1. **Keep the bespoke shell; do not adopt the shadcn `sidebar.tsx`
   primitive.** The current hand-rolled aside is small and understood;
   swapping to SidebarProvider/rail machinery is a rewrite with no visual
   payoff.
2. **Inset canvas replaces the full-width sticky topbar chrome, not its
   contents.** The header row keeps exactly what it holds today
   (`MobileMenu`, `AppBreadcrumbs`, `WorkspaceSwitcher`) and moves inside
   the canvas as its first row.
3. **Sidebar content untouched** (see scope constraint). Only spacing,
   color, and status-glyph styling may change.

## Steps

### 1. Canvas layout in `app-shell.tsx`

- Root: `bg-sidebar text-foreground h-dvh overflow-hidden md:grid
  md:grid-cols-[280px_minmax(0,1fr)]`.
- Sidebar `<aside>`: drop `border-r` (the canvas edge now provides the
  separation); keep `bg-sidebar` and the flex column, contents unchanged.
- Main column: `flex h-dvh min-h-0 min-w-0 flex-col p-2 pl-0` (mobile:
  `p-0` below `md` — full-bleed canvas, no gray frame on phones).
- Canvas wrapper inside it: `bg-background border-border/60 flex min-h-0
  flex-1 flex-col overflow-hidden rounded-xl border shadow-sm` (dark mode
  relies on the 001 tokens: canvas lighter than backdrop; `rounded-none`
  below `md`).
- Header row (first row inside the canvas, replacing the sticky topbar):
  `flex h-12 shrink-0 items-center gap-3 border-b px-4` — same contents
  and order as today: `MobileMenu` (mobile only) + `AppBreadcrumbs` left,
  `WorkspaceSwitcher` right. Drop the `sticky`/`backdrop-blur`/
  translucency — inside an `overflow` canvas the row is pinned by layout,
  not stickiness.
- `<main>` keeps the existing conditional: conversation-detail paths get
  `overflow-hidden`, everything else `overflow-y-auto px-6 py-5`.
- Update `app-layout-fallback.tsx` to mirror the new structure exactly.

### 2. Sidebar finish (styling only)

- `sidebar-header.tsx`: keep the "P" badge + wordmark; restyle the badge
  to `rounded-lg bg-primary/10 text-primary` (the 001 accent) instead of
  the current filled near-black chip; drop `border-b` if the header reads
  cleaner floating on the gray (judgment call at QA — keep whichever
  looks calmer).
- `primary-navigation.tsx`: rows keep `h-8 rounded-lg px-2 text-sm`;
  verify the active pill (`bg-sidebar-accent`) and hover states read well
  on the 001 warm-gray `--sidebar` — adjust the sidebar-accent token in
  001's file if contrast slipped, not per-component overrides.
- `sidebar-conversations.tsx`: keep the title, query, and row structure.
  One color fix: the needs-approval `ShieldAlertIcon` glyph →
  `text-warning` (pending-attention, not an error; destructive red stays
  for failures). Unread dot → `bg-primary`.

### 3. Verify

- `pnpm check` passes.
- Visual pass, light + dark, `md` and mobile widths: gray backdrop with
  white rounded canvas; header row inside the canvas with breadcrumbs and
  workspace switcher exactly where they were; sidebar menu byte-for-byte
  the same items; conversation detail still owns its scroll (transcript
  scrolls, shell does not); mobile is full-bleed with the mobile menu
  working; keyboard-tab order unchanged.

## STOP conditions

- Any step tempts a change to `navigation.ts`, sidebar section structure,
  or the workspace switcher's location — out of scope; stop (see scope
  constraint).
- The conversation route's scroll behavior cannot survive the canvas
  wrapper without changes to the route itself beyond classNames — stop
  and report.
