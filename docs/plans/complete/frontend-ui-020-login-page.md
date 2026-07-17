# Plan 020: Login page — brand panel art & card breathing room

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Verification**: `cd apps/web && pnpm check` passed (25 test files, 122
  tests); `git diff --check` passed.
  Browser-based verification was intentionally not used per maintainer
  instruction.
- **Written**: 2026-07-16 (anchors verified at `75da3b5`, with plan 014's
  changes applied uncommitted in the working tree)
- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MEDIUM — the mechanics are trivial; the risk is aesthetic.
  Brand art is subjective, so the composition below is a concrete recipe,
  not a vague "make it pretty", and manual QA in both themes is the real
  gate.
- **Depends on**: 013 (landed at `75da3b5`). The copy sweep grazes the two
  OAuth callback routes that the in-flight 014 work modified — land 014's
  commit before starting, or leave those two files out.

## Goal

The auth screens stop looking half-finished:

1. The huge empty brand panel gets an abstract, on-brand composition
   built from CSS gradients and inline SVG using the existing theme
   tokens — no raster assets.
2. The sign-in card gets breathing room: taller buttons, more generous
   padding and rhythm.
3. Mobile (which currently shows zero branding) gets the brand mark
   above the card.
4. A small copy-casing consistency pass across the four auth screens.

## Current state (verified 2026-07-16)

- `src/routes/auth-layout.tsx` (35 lines): a two-column grid
  (`lg:grid-cols-[minmax(0,0.9fr)_minmax(420px,0.55fr)]`) — the left
  ~62% is a flat `bg-sidebar` panel holding only a small "P" logo tile
  top-left (lines 11-16) and a strapline + `text-3xl` headline
  bottom-left (lines 17-25). Everything between is empty. The panel is
  `hidden` below `lg`, so mobile gets no branding at all.
- `features/auth/components/auth-card.tsx`: `Card` with `shadow-xs`;
  the card primitive's `--card-spacing` is `--spacing(4)` (1rem), so
  the whole card runs on 16px padding.
- `features/auth/routes/login-route.tsx`: `OAuthLoginProviders` then
  the email/password form in a `flex flex-col gap-5`. Submit button is
  default size.
- `features/auth/components/oauth-login-providers.tsx`: provider
  buttons stacked in `grid gap-2` (line 65), default size, then
  `<FieldSeparator>or</FieldSeparator>`.
- `components/ui/button.tsx`: `default` size is **h-8**, `lg` is
  **h-9** — both compact, tuned for the dense in-app UI. Stacked h-8
  full-width buttons at `gap-2` are what reads as "cramped" here.
- Copy casing is inconsistent across the auth screens: titles
  "Sign In" / "Create account" / "Completing sign in"; alert titles
  "Sign In Failed" / "Registration failed" / "Provider sign in failed"
  / "Sign in failed" / "Two-Step Verification Required" /
  "Two-step verification required".
- Theme tokens available for the art (`src/index.css`): `--primary`
  (amber), `--link` (teal), `--sidebar`, and the eight agent identity
  hues `--agent-1` … `--agent-8` — both themes define all of them.

## Steps

### 1. Brand panel composition

Extract the left panel into
`features/auth/components/auth-brand-panel.tsx` (consumed by
`auth-layout.tsx` — new file ships with its consumer, keeping knip
green). Keep the existing contents (logo tile + name top-left,
strapline + headline bottom-left) and layer the art behind them:

- **Gradient wash** (CSS, on the panel): two or three large soft
  radial gradients over the `bg-sidebar` base — a warm amber glow
  derived from `--primary` and a teal counter-glow from `--link`,
  both heavily diluted via `color-mix(in oklch, var(--primary) N%,
  transparent)` at low percentages (roughly 8-15% light, 12-20% dark —
  tune by eye). Position them asymmetrically (e.g. one bleeding off
  the top-right, one low-left behind the headline area).
- **Abstract SVG figure**: an inline SVG of concentric orbital arcs
  (three to five thin circles/arcs, `stroke="currentColor"` at low
  opacity on the panel's muted foreground) with small filled nodes
  sitting on the arcs, each node filled with one of
  `var(--agent-1)` … `var(--agent-8)` — a quiet "constellation of
  agents" motif that reuses the product's own identity palette.
  Inline SVG inherits CSS custom properties, so the tokens-only rule
  holds with zero new tokens. Fade the figure's edges with a CSS
  `mask-image` linear/radial gradient so it dissolves into the panel
  instead of ending at a hard viewBox edge. Size it large — this is
  filling a ~62%-wide panel, not decorating a corner.
- **Static.** No animation. (If a slow drift is ever wanted it needs a
  `prefers-reduced-motion` guard, but do not add it in this plan.)
- **Legibility**: the strapline + headline must keep ≥ 4.5:1 contrast
  over whatever the art puts behind them. If a glow lands behind the
  text, add a subtle scrim (gradient from `--sidebar` to transparent)
  under the text block rather than dimming the whole composition.
- Verify in **both themes** — the dark theme's `--sidebar` is near
  black, so the same mix percentages will read differently; tune per
  theme with the `dark:` variant if needed, still via tokens.

### 2. Card breathing room

- **Buttons**: on the auth surfaces only, make the OAuth provider
  buttons and the submit buttons `h-10` (className on the buttons —
  do not touch the button primitive's size scale, which the dense
  in-app UI depends on). OAuth button stack goes `gap-2` → `gap-2.5`.
- **Card**: `AuthCard` overrides the card spacing to
  `[--card-spacing:--spacing(6)]` (24px padding all around) and bumps
  the title to `text-xl` via `CardTitle`'s className. Footer stays.
- **Rhythm**: the `gap-5` between the OAuth block and the form goes to
  `gap-6`; give the `FieldSeparator` a touch more vertical margin if
  it still reads tight after the gap change.
- **Mobile branding**: in `auth-layout.tsx`, above the card in the
  right section, render the logo tile + `appConfig.name` (the same
  pieces the brand panel uses — export them from
  `auth-brand-panel.tsx` or keep it inline) visible only below `lg`
  (`lg:hidden`), centered, with margin below so the card doesn't
  crowd it.

### 3. Copy casing pass

Auth card titles and alert titles go Title Case, consistently, across
`login-route.tsx`, `register-route.tsx`,
`oauth-login-callback-route.tsx`, and `oauth-link-callback-route.tsx`
(the last two were touched by 014 — see Depends on):

- "Create account" → "Create Account"; "Completing sign in" →
  "Completing Sign In".
- Alert titles: "Registration failed" → "Registration Failed",
  "Provider sign in failed" → "Provider Sign In Failed",
  "Sign in failed" → "Sign In Failed", "Two-step verification
  required" → "Two-Step Verification Required".
- Body copy stays sentence case; do not touch descriptions.

### 4. Verify

- `cd apps/web && pnpm check` passes.
- Manual QA against `pnpm dev`, both themes:
  - Desktop ≥ lg: the brand panel shows the composition; headline and
    strapline clearly legible over it in both themes; no horizontal
    scroll at any width; the art does not fight the form for
    attention (it should read as background, not hero image).
  - Between lg and ~2xl widths the composition still fills sensibly
    (gradients and the masked SVG scale; nothing pins to one corner
    leaving the old emptiness).
  - Below lg: brand mark + name appear above the card; panel hidden.
  - Login and register cards: h-10 buttons, comfortable padding,
    nothing cramped; OAuth pending/error states unchanged
    functionally.
  - Sign in with password and with an OAuth provider still work
    end to end; the two-factor pending alert renders.
  - Keyboard pass: focus-visible rings on all buttons/inputs/links
    survive the restyle; tab order unchanged.
  - Zoom to 200%: card remains usable, panel art doesn't obscure
    content.

## STOP conditions

- The composition cannot be built to look intentional from tokens +
  CSS + inline SVG and genuinely needs a raster/illustrative asset —
  stop and report. Generating an image (the maintainer has imagegen
  available) is a maintainer decision because a static raster must be
  produced per-theme, adds bundle weight, and exits the tokens-only
  theming contract. Do not commit a generated or stock image without
  that sign-off.
- Headline contrast over the art cannot reach 4.5:1 in some theme
  without a scrim so heavy it erases the composition — stop and
  propose repositioning the glows instead of shipping low-contrast
  text.
- Any need to add new color tokens beyond mixing the existing ones —
  add the token to `src/index.css` first per the shared rules; if the
  token wanted is a whole new hue family, stop and check it against
  the brand palette at praxis-agents.ai before inventing it.
- The 014 working-tree changes to the OAuth callback routes are still
  uncommitted when this plan starts — leave those two files out of the
  copy pass rather than creating a merge mess, and note it in the
  status row.
