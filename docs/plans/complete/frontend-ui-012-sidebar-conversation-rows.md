# Plan 012: Sidebar conversation rows — compact datetime, full-width titles

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — one shell component plus one new format helper with
  unit tests.
- **Depends on**: 010. The mobile drawer reuses the sidebar contents;
  land this after 010 so the row restyle happens once, in the final
  sidebar.

## Goal

In the sidebar conversations list, the full datetime ("16 Jul 2026,
17:21") is right-aligned on the title line and eats roughly half the
280px sidebar, truncating every title to a few words ("Greeting and
Welc…"). The datetime is useful and stays (maintainer, 2026-07-16) —
the fix is placement and format, not removal:

1. Titles get the full row width.
2. The datetime moves to the second line, right-aligned opposite the
   agent name, in a compact format that scales with age: time for
   today, day+month within the year, day+month+year beyond.

## Current state (verified 2026-07-16 at `d1c4a89`)

- `src/components/shell/sidebar-conversations.tsx:61-101` —
  `ConversationRow`: a two-column flex (`flex min-w-0 items-start
  gap-2`). Left column (`min-w-0 flex-1`): title (`truncate text-sm
  font-medium`) over agent label (`truncate text-xs` muted). Right
  column (`shrink-0`, lines 85-99): approval `ShieldAlertIcon`, unread
  dot, then `formatDateTime(conversation.last_message_at ??
  conversation.updated_at)` at `text-[0.7rem]` — the full
  "16 Jul 2026, 17:21" string that squeezes the title.
- `src/lib/format.ts:3-16` — `formatDateTime` (Intl `dateStyle:
  "medium", timeStyle: "short"`, `"Never"` on null). `relativeDateTime`
  (line 34) exists but produces "2h ago"-style strings — not what we
  want here; absolute times stay (maintainer decision above).
- The page-level `ConversationList`
  (`src/features/conversations/components/conversation-list.tsx:51-80`)
  already puts its datetime on its own line and does not truncate
  titles against it — **out of scope**; touch only the sidebar row.
- Frontend unit tests live under `apps/web/tests/` mirroring source
  paths (Vitest via `pnpm test`).

## Steps

### 1. Add a compact date formatter

In `src/lib/format.ts`, add:

```ts
formatCompactDate(value: string | null | undefined, now: Date = new Date()): string
```

- null/undefined → `"Never"` (matches the file's convention).
- Same calendar day as `now` (local time) → time only, via
  `Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" })`
  → "17:21".
- Same calendar year → `{ day: "numeric", month: "short" }` → "16 Jul".
- Otherwise → `{ day: "numeric", month: "short", year: "numeric" }` →
  "16 Jul 2026".

The `now` parameter exists for tests; production callers omit it.
Calendar-day comparison is by local date parts, not a 24h delta — a
message from 23:50 yesterday shows "15 Jul", not a time.

### 2. Restructure the sidebar row

In `ConversationRow` (`sidebar-conversations.tsx`), rework the layout
to two stacked lines inside the existing `Link` (keep its hover/selected
classes untouched):

- **Line 1**: title (`min-w-0 flex-1 truncate text-sm font-medium`) with
  the indicators — approval icon and unread dot, unchanged markup and
  `aria-label`s — as a trailing `shrink-0` group. Indicators are small
  and rare; they cost the title almost nothing.
- **Line 2**: agent label (`min-w-0 flex-1 truncate text-xs` muted) with
  the datetime right-aligned (`shrink-0 whitespace-nowrap text-[0.7rem]`
  muted), rendered via `formatCompactDate`. Give the datetime span
  `title={formatDateTime(...)}` so the full timestamp survives on hover.

Net effect: the title line owns the sidebar width; the compact date
("17:21" for today's threads — the common case in a recents list)
shares the meta line without crowding the agent name.

### 3. Tests

Add `apps/web/tests/lib/format.test.ts` cases for `formatCompactDate`
(or extend the existing file if one covers `format.ts`): null → "Never",
same-day → time, same-year → day+month, prior-year → day+month+year,
and the yesterday-23:50 boundary. Pass a fixed `now` — no fake timers
needed.

### 4. Verify

- `cd apps/web && pnpm check` passes.
- Visual QA against `pnpm dev`, both themes, in the desktop sidebar and
  the plan-010 mobile drawer: long titles truncate only against the
  indicators, not the date; today's conversations show bare times;
  older ones show dates; hover reveals the full timestamp; approval and
  unread indicators still visible and labeled; selected-row styling
  unchanged.

## STOP conditions

- Plan 010 landed a materially different sidebar row (not just moved
  files) — reconcile against the live component before editing; if the
  layout conflict is structural, stop and report.
- The compact format proves ambiguous in real data in some locale
  (e.g. a locale where the short-month form still overflows) — stop and
  report rather than inventing a custom non-Intl format.

## Execution record

- Added a locale-aware compact date formatter with module-level `Intl`
  formatters. It distinguishes today, the current calendar year, and prior
  years by local date parts; null and undefined retain the existing `Never`
  convention.
- Reworked the shared sidebar conversation row into two stacked lines. Titles
  now use the width left by the approval/unread indicators, while the agent and
  compact timestamp share the meta line. The full timestamp remains available
  through the datetime span's `title` attribute.
- Added locale- and timezone-independent unit coverage for null, undefined,
  same-day, same-year, prior-year, and yesterday-at-23:50 behavior.
- `pnpm check` passed on 2026-07-16: typecheck, ESLint, 91 Vitest tests,
  Prettier, Knip, dependency-cruiser, and the production build. Browser use was
  excluded at the maintainer's direction; desktop/mobile reuse, both semantic
  themes, selected-row classes, truncation constraints, full-timestamp hover
  metadata, and indicator labels were verified through source inspection of
  the single component shared by the desktop sidebar and mobile drawer.
