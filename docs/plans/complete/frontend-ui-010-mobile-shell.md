# Plan 010: Mobile shell — drawer sidebar

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM — introduces one new primitive (sheet/drawer) and
  replaces the whole mobile navigation surface. Desktop is untouched.
- **Depends on**: 002 (inset canvas shell), 009 (final menu contents —
  do not build the drawer around items 009 is about to move).

## Goal

The mobile experience today is a single giant dropdown menu: navigation,
conversation links, workspace switching, and account actions crammed into
four groups of a `w-64` popover, with no conversation list, no user
identity, and no visible workspace context. Replace it with the real
sidebar in a slide-in drawer, so mobile gets the same shell as desktop —
same sections, same components, same styling — instead of a parallel,
worse one (maintainer, 2026-07-16).

## Current state (verified 2026-07-16 against the live tree, post-002)

- `src/components/shell/app-shell.tsx:41-55` — the sidebar `<aside>` is
  `hidden ... md:flex`; below `md` there is no sidebar at all. The header
  row (`app-shell.tsx:59-76`) shows `MobileMenu` + breadcrumbs; the
  workspace switcher is `hidden ... md:block`.
- `src/components/shell/mobile-menu.tsx` — the dropdown described above:
  Navigate group (from `navigationItemsForRole`), Conversations group
  (New / View All links only — no actual list), Switch Workspace group
  (flat list, no personal/team split), account group (Profile Settings,
  Sign Out — no avatar, no name). This file is replaced by this plan.
- Sidebar building blocks are already self-contained and reusable:
  `SidebarHeader` (no props), `PrimaryNavigation` (`pathname`,
  `workspaceRole`), `SidebarConversations` (`conversations`, `pathname`),
  `SidebarFooter` (`user`, `onSignOut`). `AppShell` already holds every
  prop they need (`app-shell.tsx:27-30`).
- `src/components/ui/` has `dialog.tsx` but **no sheet/drawer**.
- `WorkspaceSwitcher` (`workspace-switcher.tsx`) takes an `align` prop
  and is otherwise placement-agnostic.

## Steps

### 1. Add the sheet primitive

Add `src/components/ui/sheet.tsx` from the shadcn registry (base-nova
style, `pnpm dlx shadcn@latest add sheet` or the project's established
add flow). If the base-nova/base-ui registry has no sheet, derive it from
the existing `dialog.tsx` (base-ui Dialog already provides portal,
backdrop, focus trap, Escape, scroll lock) with side-panel styling:
left-anchored, `h-dvh w-80 max-w-[85vw]`, slide-in/out via
`tw-animate-css` classes, backdrop consistent with `dialog.tsx`. It goes
in `components/ui/`, so it stays generic — no shell-specific styling
baked in. Respect `prefers-reduced-motion`: the slide animation reduces
to a fade/instant per the same pattern the dialog uses.

### 2. Rebuild `mobile-menu.tsx` as a drawer

Replace the dropdown wholesale; keep the file name, the `md:hidden`
wrapper, and the component's public props so `app-shell.tsx` changes
minimally (it must additionally pass `user`, `pathname`, and
`conversations` — all already in scope there).

- **Trigger**: the existing `variant="outline" size="icon"` hamburger
  with `aria-label="Open menu"` stays.
- **Sheet content is the sidebar composition**, in desktop order, on
  `bg-sidebar text-sidebar-foreground`:
  1. `SidebarHeader` (brand chip row) — the sheet's close button sits in
     this row, right-aligned (`aria-label="Close menu"`).
  2. The workspace switcher: mobile has no header-row switcher, so it
     lives here, full-width above the nav (`align="start"`). This is a
     mobile-only placement; the desktop decision (switcher in the header
     row) is unchanged.
  3. `PrimaryNavigation`
  4. `Separator`, then `SidebarConversations` — the real list, scrolling
     within the drawer (`min-h-0 flex-1 overflow-y-auto` structure as in
     the desktop `<aside>`), including the needs-approval and unread
     affordances mobile currently lacks entirely.
  5. `SidebarFooter` with the plan-009 user menu (identity row,
     Profile Settings / Workspaces / Workspace Settings / Sign Out).
     Inside the drawer it should open **downward/inward** without
     clipping the viewport bottom — verify, and adjust its side/collision
     handling via props if 009's `side="top"` default clips.
- **Close on navigate**: the drawer closes when any link inside it is
  handled — control the sheet's `open` state in `mobile-menu.tsx` and
  close on router pathname change (effect on `pathname` prop), which
  catches nav links, conversation rows, and switcher-triggered
  navigation uniformly. Also close on workspace switch even if the
  pathname happens not to change.
- **Touch targets**: inside the drawer, nav and conversation rows may
  render at a comfortable mobile height. If `h-8` rows feel too tight,
  prefer a minimal `className`/density prop threaded through
  `PrimaryNavigation`/`SidebarConversations` over duplicating either
  component — duplication is the failure mode this plan exists to remove.

### 3. Header row cleanup (`app-shell.tsx`)

- Pass the new props to `MobileMenu`; delete the now-unused
  `setWorkspaceBySlug`/`workspaces` plumbing from it only if the switcher
  inside the drawer doesn't need them (it does — they move, not vanish).
- Breadcrumbs remain the mobile header's content. No other header
  changes; the desktop layout must render byte-identical DOM to before
  at `md+` except for prop threading.

### 4. Verify

- `pnpm check` passes (knip: removed dropdown imports; depcruise: sheet
  in `components/ui` keeps the layering clean).
- Mobile visual QA (real device or devtools ≤ 390px width), both themes:
  drawer opens/closes smoothly; slide respects reduced motion; body
  scroll locks while open; Escape and backdrop-tap close it; focus is
  trapped inside and returns to the hamburger on close; every route
  reachable; conversation list scrolls independently; needs-approval and
  unread indicators visible; user menu opens inside the drawer without
  clipping; switching workspace closes the drawer and updates content.
- Desktop regression pass: sidebar, header row, and user menu unchanged
  at `md` and above.
- iOS-style dynamic viewport: the drawer uses `h-dvh` (not `h-screen`)
  so browser chrome show/hide doesn't clip the footer.

## STOP conditions

- No sheet in the base-nova registry **and** the dialog primitive cannot
  be adapted into a side panel without a new dependency — stop; the "no
  new UI libraries" rule holds.
- Reusing `PrimaryNavigation`/`SidebarConversations`/`SidebarFooter` in
  the drawer requires more than superficial prop threading (e.g. a
  density prop turning into a fork of the component) — stop and report
  the design tension instead of duplicating the components.
