# Plan 009: Sidebar declutter & user menu redesign

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW — nav config + one shell component; no routes or data
  change. The main risk is losing a path to a page (covered in Verify).
- **Depends on**: 001 (tokens). Independent of 004–008; can run in
  parallel with them.

## Goal

Two problems, one change (maintainer, 2026-07-16):

1. **The sidebar nav is cluttered.** Seven items, and two of them —
   Workspaces and Settings — are administrative "manage the container"
   destinations, not daily working surfaces. They dilute the five real
   work sections (Home, Agents, Skills, Files, Schedules).
2. **The user menu is ugly.** A bare w-56 dropdown with a plain "Account"
   text label, one link, and Sign Out. It looks like scaffold next to the
   rest of the restyled app.

Move Workspaces and Settings (relabeled **Workspace Settings**) into the
user menu, and rebuild that menu to the same standard as the rest of the
shell. This amends the earlier "sidebar menu does not change" decision —
the amendment is recorded in the README.

## Current state (verified 2026-07-16 against the live tree, post-002)

- `src/config/navigation.ts:30-73` — `mainNavigation`: Home, Agents,
  Skills, Files, Schedules, **Workspaces** (`/workspaces`, `UsersIcon`),
  **Settings** (`/workspace-settings`, `SettingsIcon`). Consumed by
  `primary-navigation.tsx` (desktop) **and** `mobile-menu.tsx:48` — a
  removal here disappears from mobile too.
- `src/components/shell/sidebar-footer.tsx:32-67` — `UserMenu`: ghost
  button trigger (avatar + name + email), `DropdownMenuContent
  className="w-56"` containing `DropdownMenuLabel` "Account" → Profile
  Settings (`/profile`) → separator → Sign Out.
- `src/components/shell/app-breadcrumbs.tsx:170-171` — the
  `/workspace-settings` breadcrumb already reads "Workspace Settings";
  the new menu label matches it.
- `navigationItemsForRole` (`navigation.ts:75-77`) filters `managerOnly`
  items, but no item sets the flag today — visibility of both moved
  items is currently role-independent. Keep it that way; any page-level
  restriction stays inside the routes.

## Steps

### 1. Remove the two items from the sidebar nav

In `src/config/navigation.ts`, delete the Workspaces and Settings entries
from `mainNavigation`. Five items remain: Home, Agents, Skills, Files,
Schedules. Keep `navigationItemsForRole` and the `managerOnly` seam as-is.
If `UsersIcon`/`SettingsIcon` imports go unused here, remove them (knip
will catch stragglers).

### 2. Rebuild the user menu (`sidebar-footer.tsx`)

Keep the component boundary (SidebarFooter wrapping UserMenu) and the
dropdown-menu primitive — this is a restyle plus two new items, not a new
widget.

**Trigger** — make it read as an openable control, not a dead row:

- Same avatar + name + email layout, plus a trailing
  `ChevronsUpDownIcon` (`text-muted-foreground ml-auto size-4 shrink-0`),
  the standard "this row opens a menu" affordance.
- Hover/open states use sidebar tokens:
  `hover:bg-sidebar-accent hover:text-sidebar-accent-foreground`, and
  `data-[popup-open]:bg-sidebar-accent` so the row stays lit while the
  menu is open (confirm the exact open-state attribute against
  `components/ui/dropdown-menu.tsx` / base-ui docs — use what the
  primitive actually emits).
- Row stays full-width, `rounded-lg`, current padding.

**Content** — one coherent menu instead of a bare list:

- `DropdownMenuContent` width `w-(--anchor-width)` if the base-ui anchor
  width variable is available (menu matches the trigger row, like the
  reference), else fixed `w-60`. Open direction: above the trigger
  (`side="top"` / base-ui equivalent, `align="start"`, small
  `sideOffset`) — the trigger sits at the viewport bottom and the menu
  must not clip.
- **Identity header** replacing the "Account" text label: a
  non-interactive block (`DropdownMenuLabel` with custom content or a
  plain padded div per the primitive's API) showing avatar + display
  name (`text-sm font-medium`) + email (`text-muted-foreground text-xs`),
  both truncating. This is where name/email live from now on — do not
  duplicate them in the trigger *and* header at different truncation
  widths without checking both.
- Separator, then the items in this order:
  1. `UserIcon` **Profile Settings** → `/profile`
  2. `UsersIcon` **Workspaces** → `/workspaces`
  3. `SettingsIcon` **Workspace Settings** → `/workspace-settings`
- Separator, then `LogOutIcon` **Sign Out** (`onSignOut`). Keep it a
  normal item — no destructive red; signing out is routine.

Icons at the primitive's default menu-item size, labels sentence-cased as
written above. No theme toggle, no keyboard-shortcut hints, no status
dot — nothing speculative.

### 3. Keep mobile reachable (bridge until plan 010)

`mobile-menu.tsx` inherits the nav removal via `navigationItemsForRole`,
so Workspaces and Workspace Settings would vanish from mobile entirely.
In its last group (currently Profile Settings + Sign Out,
`mobile-menu.tsx:96-106`), add Workspaces and Workspace Settings items
mirroring step 2's order and icons. Plan 010 replaces this menu wholesale;
this is a two-line bridge, not a redesign.

### 4. Verify

- `pnpm check` passes (knip: unused icon imports in `navigation.ts`).
- Every destination still reachable, desktop and mobile: `/workspaces`
  and `/workspace-settings` open from the user menu (desktop) and the
  hamburger menu (mobile). Deep links and breadcrumbs for both routes
  still work — nothing in routing changed, confirm anyway.
- Visual QA, both themes: sidebar shows five nav items; user menu opens
  upward without clipping; identity header truncates gracefully with a
  long display name and a long email; hover/open states visible; keyboard
  path works (Tab to trigger, Enter opens, arrows navigate, Escape
  closes, focus returns to trigger).

## STOP conditions

- The dropdown-menu primitive cannot render a rich identity header or
  open-side control without patching `components/ui/dropdown-menu.tsx`
  in ways that break its generic API — stop and report; do not fork the
  primitive.
- Anything outside `navigation.ts`'s two consumers turns out to depend on
  Workspaces/Settings being in `mainNavigation` (e.g. an active-state or
  layout assumption) — stop and report before working around it.

## Execution record

- The shared primary navigation now contains only Home, Agents, Skills, Files,
  and Schedules for every role; a focused regression test protects that exact
  set while preserving the existing role-filter seam.
- The desktop footer trigger now has the standard menu affordance and persistent
  sidebar-token open state. Its upward-opening, anchor-width menu reuses one
  identity component for matching trigger/header truncation and exposes Profile
  Settings, Workspaces, Workspace Settings, and Sign Out in the planned order.
- The existing mobile dropdown includes the two moved destinations as a bridge
  until UI-010 replaces it. Both destination routes and their breadcrumbs remain
  registered; no routing, API, backend, or agent-runtime behavior changed.
- Base UI's installed trigger and positioner contracts confirm
  `data-popup-open`, `--anchor-width`, and top-side placement. `pnpm check`
  passed on 2026-07-16: typecheck, ESLint, 89 Vitest tests, Prettier, Knip,
  dependency-cruiser, and the production build. Browser-based verification was
  not run at the maintainer's direction; responsive, theme, focus, truncation,
  and placement behavior were checked through the primitive contract, shared
  semantic classes, source review, and the production build.
