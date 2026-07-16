# Plan 013: Button text — normal weight, Title Case actions

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-16 (anchors verified at `d1c4a89`)
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — one class change in the button primitive plus a wide
  but shallow copy sweep. Main hazard is tests asserting old label text.
- **Depends on**: 010, 011, 012 — run this **last**. It sweeps label
  literals across files those plans add (010's drawer) and delete
  (011 removes "Start new"); sweeping final copy once beats merging
  label diffs three times.

## Goal

Two maintainer decisions (2026-07-16, with screenshot):

1. **Buttons stop bolding their text.** In Inter at button sizes,
   `font-medium` reads as bold — especially on the filled amber primary
   ("New schedule"). Buttons drop to normal weight.
2. **Action labels use Title Case everywhere.** Current copy is split:
   feature routes say "New schedule" / "Save changes" (sentence case)
   while the shell says "Sign Out" / "Profile Settings" (Title Case).
   Title Case wins, applied consistently to every action label.

## Current state (verified 2026-07-16 at `d1c4a89`)

- `src/components/ui/button.tsx:7` — the base `cva` string contains
  `font-medium`; no size or variant overrides it, so every button
  inherits it. Size variants only change height/padding/text size.
- No shared label config exists — every action label is an inline JSX
  literal (`src/config/` holds only app/env/navigation data, and
  `navigation.ts` drives nav items, not buttons).
- Sentence-case majority (sample): "New schedule"
  (`schedules-route.tsx:25`, `schedules-table.tsx:47`), "New agent"
  (`agents-route.tsx:25`, `agents-table.tsx:43`), "New skill"
  (`skills-route.tsx:23`, `skills-table.tsx:33`), "New workspace"
  (`create-workspace-dialog.tsx:56`), "New conversation"
  (`conversations-route.tsx:38`, `home.tsx:45`, plus empty states),
  "Save changes" (`workspace-settings-form.tsx:206`), "Upload file"
  (`file-upload-button.tsx:88`, `files-table.tsx:105`), "Run now"
  (`schedule-detail-route.tsx:141`), "View details"
  (`audit-events-table.tsx:198`, `security-events-table.tsx:143`),
  "Open transcript" (`delegation-tool-row.tsx:136`).
- Already Title Case (the shell/error minority): "Open Conversations"
  and "View All" (`home.tsx:66,83`), "Sign Out" / "Profile Settings" /
  "Workspace Settings" (`sidebar-footer.tsx`), "Try Again" / "Profile
  Settings" (`error-route.tsx`), "Turn Off" (`two-factor-section.tsx:216`).
- Single-word labels (Save, Cancel, Delete, Configure, …) are already
  correct in either convention.

## The Title Case rule

Capitalize the first word, the last word, and every word in between
except articles, coordinating conjunctions, and prepositions of three
letters or fewer (a, an, the, and, or, but, to, of, for, in, on, at,
with → "with" has four letters and IS capitalized; keep the ≤3 rule
simple). Examples: "New Schedule", "Save Changes", "Run Now",
"View Details", "Open Transcript", "Turn Off", "Sign in to Praxis".

## Steps

### 1. Drop the bold weight

`src/components/ui/button.tsx:7`: change `font-medium` → `font-normal`
in the base string. Touch nothing else in the primitive — other UI
primitives (badges, tabs, menu items, card titles) keep their current
weights; this decision is about buttons.

### 2. Sweep action labels to Title Case

Scope — labels that *do something when activated*:

- `<Button>` children throughout `src/` (including `render={<Link/>}`
  buttons and form submit buttons).
- Dropdown/context menu items and dialog/alert-dialog action buttons.
- Empty-state CTA buttons (`EmptyState` `action` props).
- `aria-label`s on icon-only buttons (e.g. "New Conversation" — most
  are already Title Case; make the rest match).

Explicitly **not** in scope: page/card/section titles, descriptions and
helper copy, empty-state titles ("No conversations yet" is a state, not
an action), toasts, form field labels, badge text, table column
headers, breadcrumbs, and `navigation.ts` items (all single words —
already conformant).

Method: grep is the tool, the known list above is the seed, not the
boundary. Sweep `grep -rn "<Button" apps/web/src` plus the menu-item
and dialog-action components, and review each label against the rule.
Loading/pending variants too ("Saving changes…" → "Saving Changes…"
where the label is on the button itself).

### 3. Update tests

`grep -rn` the old label strings under `apps/web/tests/` — any
`getByRole("button", { name: … })` or text assertion using an old
label updates to the new casing. Do not loosen assertions to regexes
just to dodge the rename.

### 4. Verify

- `cd apps/web && pnpm check` passes (typecheck, lint, vitest,
  prettier, knip, depcruise, build).
- `grep -rniE ">(New|Save|Upload|View|Open|Run|Start|Create|Turn|Try) [a-z]"
  apps/web/src` (and a manual pass over dialogs/menus) turns up no
  remaining sentence-case action labels — expect a few false positives
  from prose; judge each hit.
- Visual QA against `pnpm dev`, both themes: primary amber buttons read
  as normal weight and stay legible (contrast is unchanged — weight is
  not a contrast property, but confirm the amber fill still reads
  comfortably at `font-normal`); focus rings and icon spacing
  unaffected.

## STOP conditions

- `font-normal` makes button text visibly illegible on any filled
  variant in either theme (not just "lighter than before") — stop and
  report before compensating with size or color changes.
- Any label turns out to be derived from data or shared config rather
  than a literal (so the sweep would change non-action strings) — stop
  and report that case rather than transforming at runtime.
