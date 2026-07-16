# Plan 007: Pages & states polish — dashboard, lists, auth, empty states

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Priority**: P2
- **Effort**: M
- **Risk**: LOW — page-level styling on non-streaming surfaces.
- **Depends on**: 001, 002, 003. Run after the P1 plans; this is the
  consistency sweep for everything they did not touch.

## Goal

Bring the non-chat pages up to the same standard: one page-header pattern,
one card vocabulary, colored status language from the 001 tokens, agent
identity from 003, and empty states that invite action. Kill the remaining
"unstyled scaffold" tells.

## Current state (verified at `158de0b`)

- **Page header pattern** (repeated in `src/routes/home.tsx:71-85`, agents
  /conversations/skills/schedules routes): muted workspace-name eyebrow +
  `font-heading text-2xl font-semibold` h1 + description + right CTA. The
  pattern is fine; instances have drifted (some omit eyebrow/description).
- **`home.tsx`**: summary tiles (87–112, `Card size="sm"` + `text-3xl`
  numbers); then `DashboardPanel`s (278–302) — bespoke `bg-background
  rounded-xl border` divs, *not* the `Card` component; then a 4-up
  info-card row (178–244) duplicating workspace/agent facts.
- **Agents list** (`features/agents/routes/agents-route.tsx` +
  `components/agents-table.tsx`): metric cards then a table; status via
  monochrome badges (`agent-status-badges.tsx` — Active = near-black
  filled, now brand amber after 001).
- **Conversations index** (`conversations-route.tsx` +
  `conversation-list.tsx:55-58`): bordered section + rows; badge pills
  from `conversation-badges.tsx` / `run-status-badge.tsx` (monochrome
  variants; failed = destructive).
- **Auth** (`src/routes/auth-layout.tsx`): split-screen with `bg-muted/30`
  brand panel, "P" badge, "The Operating Intelligence Layer" headline;
  `AuthCard` on the right.
- **Empty state** (`components/ui/empty-state.tsx`): dashed-border card +
  muted icon circle.
- Workspace settings: `Tabs variant="line"`; profile: narrow stacked
  forms.

## Steps

### 1. Extract the page header

Five hand-rolled copies is enough: add
`src/components/shell/page-header.tsx` (`title`, `description?`,
`eyebrow?`, `actions?`) rendering the existing pattern —
eyebrow `text-muted-foreground text-sm font-medium`, h1 `font-heading
text-2xl font-semibold tracking-tight`, actions right-aligned. Adopt it in
home, agents, conversations, skills, schedules, workspaces, settings
routes. (Shell is the right home: routes may import shell, features may
not — confirm against `.dependency-cruiser.cjs`; if features/routes
layering forbids it there, place it in `components/` root per the live
rules instead.)

### 2. Dashboard (`home.tsx`)

- Convert `DashboardPanel` to the `Card` component (`CardHeader` +
  content) — one card vocabulary everywhere.
- Summary tiles: number stays `font-heading text-3xl tabular-nums`; icon
  chip gets a quiet tint (`bg-primary/10 text-primary` for the
  conversations tile; others stay `bg-muted text-muted-foreground` —
  exactly one accent tile, matching the reference's restraint).
- Cut the bottom 4-up info-card row (178–244) **if** every fact on it is
  reachable elsewhere (workspace settings, agents list, profile). It is
  scaffold filler; removing beats restyling. If any fact is not reachable
  elsewhere, keep that card only and note it.

### 3. Status language on lists

- `agent-status-badges.tsx`: Active → `success` badge variant (from 001),
  Inactive → `outline`; Favorite stays `secondary`.
- `run-status-badge.tsx` / `conversation-badges.tsx`: awaiting approval →
  `warning` variant (icon included), failed/cancelled stay destructive,
  unread dot stays `bg-primary`.
- `agents-table.tsx`: adopt `AgentIdentityIcon` in the name cell (both
  table and mobile card variants) if plan 003 step 3 has not already.

### 4. Empty states

Sweep every `EmptyState` usage plus the bespoke empties (dashboard
panels, sidebar conversations list): title states the situation, description is one
sentence, and there is always a primary action when the user can act
("Create an agent", "Start a conversation"). Drop the dashed border in
`empty-state.tsx` for a plain `bg-muted/30 rounded-xl` fill — dashed
reads as a dropzone.

### 5. Auth pages

- Brand panel: `bg-sidebar` (the warm gray) instead of `bg-muted/30`;
  keep the split layout. Replace placeholder-flavored copy — headline
  should say what the product is in plain words (e.g. "Build and run
  agents for your team's real work"); confirm final copy with the
  maintainer if in doubt, scaffold copy must not survive.
- "P" letter badge: restyle to the sidebar-header chip treatment from
  plan 002 so the brand mark is consistent (`rounded-lg bg-primary/10
  text-primary` letterform).
- `AuthCard`: on the new gray backdrop give it `shadow-xs`; inputs and
  buttons already inherit 001.

### 6. Tables & settings

- `components/ui/table.tsx`: header row `text-muted-foreground text-xs
  font-medium uppercase tracking-wide` if not already close; row hover
  `hover:bg-muted/40`; keep density.
- Workspace settings tabs and profile forms: verify they inherit 001
  cleanly; fix only concrete regressions, do not redesign forms here.

### 7. Verify

- `pnpm check` passes (knip: the removed dashboard cards may strand
  helpers — delete them).
- Visual pass over every route in both themes: home, agents (+detail),
  conversations index, skills, files, schedules, workspaces, workspace
  settings (all tabs), profile, login, register. Checklist: headers
  identical in structure; a single accent tile on the dashboard; status
  colors consistent with plan 005's vocabulary; no dashed empty states;
  no scaffold copy anywhere.

## STOP conditions

- Removing the dashboard info-card row would orphan a fact with no other
  surface — keep that card, note it, continue.
- The page-header extraction fights the dependency-cruiser layering in
  both candidate locations — stop and report rather than editing rules.

## Execution record

- A shared `PageHeader` now provides one title-and-description structure for
  dashboard, list, workspace settings, and profile routes. Maintainer review
  removed the proposed eyebrow treatment everywhere, including the remaining
  create, invitation, auth, and not-found surfaces.
- Maintainer screenshot review also rejected the metric-card bands as
  redundant. Summary cards were removed from dashboard, list, and detail
  pages, and the now-unused `MetricCard` primitive and derived metric work were
  deleted. The dashboard's lower scaffold-information row was removed because
  every fact remains available on its dedicated workspace, agent, or profile
  surface.
- Dashboard and conversation panels now use the shared `Card` vocabulary.
  Agent, skill, file, schedule, conversation, and run badges use the shared
  success, warning, destructive, outline, and secondary status language.
- Empty states use a quiet filled surface instead of dashed borders, retain a
  clear one-sentence explanation, and expose an in-context action wherever the
  user can create or upload the missing resource. Dashed styling remains only
  on actual drop targets and unsupported-content diagnostics.
- The auth split uses the warm sidebar surface, consistent Praxis mark, direct
  product copy, and a lightly elevated auth card. Shared table headers and row
  hovers now use the compact muted treatment specified by this plan.
- No backend, FastAPI, Pydantic AI, runtime, provider, API-contract, query-key,
  or mutation behavior changed. `pnpm check` passed on 2026-07-16: typecheck,
  ESLint, 85 Vitest tests, Prettier, Knip, dependency-cruiser, and the
  production build. Browser automation was not used at the maintainer's
  direction; responsive and theme behavior were verified through semantic
  tokens, breakpoint classes, static source review, and the production build.
