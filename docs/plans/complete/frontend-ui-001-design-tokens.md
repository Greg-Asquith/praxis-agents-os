# Plan 001: Design tokens & primitive polish

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM — every screen re-renders against these tokens; a bad
  value is globally visible but trivially revertable (one file dominates).
- **Depends on**: —
- **Blocks**: every other plan in this set.

## Goal

Replace the all-grayscale token palette with the reference look expressed in
Praxis's established brand colors: charcoal, cream, amber, teal, and semantic
success/warning colors — all in `src/index.css` — then make the shared
primitives (`button`, `badge`) express those tokens correctly. After this plan
the app already looks noticeably better with zero layout changes.

**Maintainer correction (2026-07-16):** the original blue-primary proposal
was rejected after visual review. The live palette published by
`praxis-agents.ai` and the existing amber product icon are authoritative.

## Current state (verified at `158de0b`)

- `src/index.css` `:root` (lines ~51–84): every token is zero-chroma
  grayscale — `--background: oklch(1 0 0)`, `--foreground: oklch(0.145 0 0)`,
  `--primary: oklch(0.205 0 0)` (near-black), `--muted/--secondary/--accent:
  oklch(0.97 0 0)`, `--border/--input: oklch(0.922 0 0)`, `--ring:
  oklch(0.708 0 0)`. Only `--destructive` has chroma. `--radius: 0.625rem`.
- `.dark` (lines ~86–118) mirrors this in reverse; its one hue is
  `--sidebar-primary: oklch(0.488 0.243 264.376)`.
- `@theme inline` (lines ~8–49) maps tokens to utilities and derives the
  radius scale; fonts are Geist Variable for both `--font-sans` and
  `--font-heading`.
- There are no success/warning tokens anywhere; positive/pending states have
  no color vocabulary.

## Steps

### 1. Rewrite the palette in `src/index.css`

Light theme (`:root`) — exact brand values:

```css
--background: #fff;                               /* paper canvas */
--foreground: #111318;                            /* brand charcoal */
--card: #fff;
--card-foreground: var(--foreground);
--popover: #fff;
--popover-foreground: var(--foreground);
--primary: #92400e;                               /* brand amber action */
--primary-hover: #b45309;
--primary-foreground: #f7f4ec;
--link: #0f766e;                                  /* brand teal link */
--secondary: #f1eee6;                             /* warm surface */
--secondary-foreground: #1e293b;
--muted: #f7f4ec;
--muted-foreground: #64748b;
--accent: #fef3c7;                                /* amber-soft selection */
--accent-foreground: #92400e;
--destructive: #dc2626;
--success: #047857;                               /* emerald positive */
--success-foreground: #fff;
--warning: #f59e0b;                               /* pending/attention */
--warning-foreground: #111318;
--border: #e2e8f0;
--input: #cbd5e1;
--ring: #92400e;
--sidebar: #fafaf8;                               /* reference warm gray */
--sidebar-foreground: var(--foreground);
--sidebar-primary: var(--primary);
--sidebar-primary-foreground: var(--primary-foreground);
--sidebar-accent: #e8e8e4;
--sidebar-accent-foreground: var(--foreground);
--sidebar-border: #e2e8f0;
--sidebar-ring: var(--ring);
```

Dark theme (`.dark`) uses the website's deep-charcoal (`#0b0d12`), raised
charcoal (`#171a22`), cream (`#f7f4ec`), muted text (`#a8b0bc`), and a
slightly brighter brand amber (`#b45309`). The sidebar stays darker than the
canvas so the inset-canvas contrast survives; borders retain the existing
white translucency approach.

Then register the new tokens in `@theme inline` so utilities exist:

```css
--color-success: var(--success);
--color-success-foreground: var(--success-foreground);
--color-warning: var(--warning);
--color-warning-foreground: var(--warning-foreground);
--color-link: var(--link);
```

Also set `--chart-1..5` to the brand's categorical amber, teal, violet, blue,
and rose set in both themes. Blue is a chart category, not the interface
accent. Keep `--radius: 0.625rem` and the derived scale untouched.

### 2. Audit the primitives against the new palette

- `src/components/ui/button.tsx`: `default` variant is now brand amber — use
  the explicit `--primary-hover` token instead of opacity; `outline`/`ghost`/
  `secondary` stay neutral. Keep the existing `focus-visible:ring-3`; its ring
  is brand amber.
- `src/components/ui/badge.tsx`: add `success` and `warning` variants
  (tinted fills: `bg-success/10 text-success border-transparent` pattern,
  matching how `destructive` is handled in this file — reconcile with the
  live variant style). These get used by plans 002/005/007.
- Skim `input.tsx`, `textarea.tsx`, `select.tsx`, `tabs.tsx`, `alert.tsx`
  in both themes for anything that assumed the primary was near-black
  (e.g. a `bg-primary` used as a neutral). Fix by switching those uses to
  `foreground`/`secondary` tokens, not by re-darkening primary.

### 3. Sweep feature code for now-wrong primary uses

`git grep -n "text-primary\|bg-primary\|border-primary" apps/web/src
--and --not -e components/ui` — every hit now renders amber. Expected-good:
unread dots in
`sidebar-conversations.tsx`/`conversation-badges.tsx`, in-progress todo icon
in `todo-list-row.tsx`, and selected controls. Links use `text-link` instead.
Anything using primary as "strong neutral" must move to `text-foreground`.
Record each changed hit in the commit message body.

### 4. Verify

- `cd apps/web && pnpm check` → passes.
- `pnpm dev` visual pass, light and dark: login page, dashboard, agents
  list, a conversation with tool calls, an approval. Checklist: no
  cream-on-amber or gray-on-gray regressions; focus rings visible on
  keyboard-tab through the composer and sidebar; destructive actions still
  clearly red; amber stays limited to selection/attention and primary CTAs,
  while links are teal.

## STOP conditions

- The live `index.css` no longer matches the token names above (a Tailwind
  or shadcn upgrade landed) — reconcile names first, then continue.
- Any `pnpm check` gate fails for reasons unrelated to this diff.
- The button `default` variant is used in so many places that amber becomes
  the dominant page color (grep count of `<Button` without a `variant=`
  prop across `src/features` + `src/routes` — if this is > ~25 sites, stop
  and report; the usage audit belongs in plans 002–007, not here).

## Execution record

- The JSX audit used the TypeScript parser because multiline opening tags and
  arrow functions made the plan's text grep overcount. It found 31 implicit
  defaults; duplicate empty-state actions on pages with an existing primary
  CTA were changed to `secondary`. The maintainer explicitly authorized
  continuing after review of the remaining primary actions.
- Maintainer visual review rejected the proposed blue primary. Tokens were
  realigned to the live Praxis brand palette, with links split onto the teal
  `--link` token. A follow-up screenshot identified the sidebar's cream cast;
  its field and active-row colors were sampled from `reference.png` and set to
  `#fafaf8` and `#e8e8e4` respectively.
- `pnpm check` passed on 2026-07-16: typecheck, ESLint, 79 Vitest tests,
  Prettier, Knip, dependency-cruiser, and the production build.
