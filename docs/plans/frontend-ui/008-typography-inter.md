# Plan 008: Typography — Inter replaces Geist

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW — a font-family swap behind the existing `--font-sans`
  token; no layout or component changes.
- **Depends on**: — (independent; land any time, ideally before the visual
  QA passes of the remaining plans so they are judged in the final face).

## Goal

Replace Geist with Inter as the app's only sans. The reference's typeface
is Styrene B (Anthropic's commercial brand grotesque — not licensable for
an open-source default); Inter is the closest freely-licensed match at UI
sizes. Geist's tighter, more geometric character gives the app a
"developer tool" cast that fights the calm feel the rest of this plan set
is building (maintainer decision, 2026-07-16).

## Current state

- `src/index.css:4` — `@import "@fontsource-variable/geist";`
- `src/index.css:10` — `--font-sans: "Geist Variable", sans-serif;`
- `src/index.css:9` — `--font-heading: var(--font-sans);` (headings follow
  automatically — keep the alias, one family everywhere).
- `package.json` — `"@fontsource-variable/geist": "^5.2.9"`. No mono
  fontsource package; `font-mono` uses the Tailwind default stack — leave
  it alone.

## Steps

1. `cd apps/web && pnpm add @fontsource-variable/inter && pnpm remove
   @fontsource-variable/geist`.
2. `src/index.css`: import → `@import "@fontsource-variable/inter";`,
   token → `--font-sans: "Inter Variable", sans-serif;`. No
   `font-feature-settings` overrides — Inter's defaults are the look we
   want; `tabular-nums` utilities keep working via
   `font-variant-numeric`.
3. `pnpm check` passes (knip should confirm the Geist dep is gone; the
   build must not warn about the removed import).
4. Visual QA, both themes: sidebar, a conversation transcript, the
   composer, a data table, and the dashboard tiles. Check nothing
   truncates or wraps that didn't before (Inter runs a touch wider than
   Geist — button labels, badge pills, and the sidebar rows are where it
   would show), and that `font-semibold` headings don't look heavier than
   intended.

## STOP conditions

- Inter's width causes real truncation/overflow somewhere that a content
  fix can't absorb — stop and report the surface rather than adding
  per-component font tweaks.
- Any file references "Geist" outside `index.css`/`package.json`
  (`git grep -i geist` first) — reconcile those sites in this plan, not
  ad hoc.
