# Plan 003: Agent identity — deterministic colored icons

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW — additive component, no data changes.
- **Depends on**: 001 (tokens). Unblocks the agent-facing parts of 004,
  006, 007.

## Goal

Give every agent a stable visual identity — a small rounded-square icon
with a per-agent color, like the reference sidebar (each agent has its own
colored glyph) — derived deterministically on the client from the agent id.
No backend change: same agent, same color, everywhere, every session.

## Current state (verified at `158de0b`)

- Agents have **no** visual identity anywhere: the assistant message avatar
  is a generic `BotIcon` in a gray circle
  (`features/conversations/components/message-shell.tsx:56`), the agents
  table, sidebar, composer select (`agent-select-item.tsx`), and breadcrumbs
  are text-only.
- No icon/color field exists on the agent API type
  (`features/agents/types.ts`) — and this plan does not add one.

## Decisions taken

1. **Deterministic client-side palette, no persistence.** Hash the agent id
   into an 8-hue palette. A user-pickable persisted color/icon is a
   possible later vertical (needs API + migration); explicitly out of
   scope, do not half-add a field.
2. **Rounded square, not circle** — matches the reference and
   distinguishes agents from user avatars (which stay circular).
3. **One component, used everywhere.** No feature re-implements the hash
   or the styling.

## Steps

### 1. Palette + hash helper

`src/lib/agent-identity.ts` (framework-light, fits `lib/`): export
`agentIdentityIndex(id: string): number` — a tiny stable string hash (e.g.
FNV-1a) mod 8. Palette lives in CSS so it themes: add to `src/index.css`
eight pairs `--agent-1` … `--agent-8` (strong color) and register
`--color-agent-1..8` in `@theme inline`. Hues spread for adjacency
contrast, all at similar L/C so no agent looks "more important" (starting
values, light theme — dark theme raises L ~0.08):

blue 262, violet 292, magenta 335, red 20, orange 60, green 150, teal 185,
sky 230 — each `oklch(0.55 0.17 <hue>)`.

### 2. `AgentIdentityIcon` component

`src/features/agents/components/agent-identity-icon.tsx` (feature-owned;
`components/ui/` stays generic). Props: `agentId`, `name`, `size?: "sm" |
"md" | "lg"` (20 / 24 / 32px). Render: rounded-square (`rounded-md`, lg:
`rounded-lg`) filled with the agent color at a soft gradient
(`bg-linear-to-br from-[…]/90 to-[…]` via a `style`-set CSS var — the only
sanctioned non-utility color use, since the class must be dynamic:
`style={{ "--agent-color": \`var(--agent-${index + 1})\` }}` +
`from-(--agent-color)/85 to-(--agent-color)`), containing a white
`BotIcon` at ~60% of the box, `aria-hidden` with the name carried by the
adjacent text (or `aria-label` when rendered alone). Verify the
CSS-variable arbitrary-value syntax against the live Tailwind 4 version —
if `from-(--agent-color)` is unsupported, fall back to plain
`backgroundColor` via `style`.

### 3. Adopt it

- Composer agent picker: `agent-select-item.tsx` — icon (`sm`) + existing
  name/model stack.
- Agents table (`agents-table.tsx`): name cell gets the icon (`md`), both
  desktop table and mobile `ResponsiveList` card.
- Agent detail/configure header and breadcrumb-adjacent header if one
  exists (check `features/agents/routes/`).
- Conversation assistant turns adopt it in plan 004 — do not reach into
  that surface here; leave its integration to that plan. The sidebar is
  out of scope entirely (its menu/content does not change in this set).

### 4. Verify

- `pnpm check` passes (knip will flag the new lib file if something ends
  up unused — wire-ups above prevent that).
- Visual: two different agents get visibly different colors; the same
  agent's color is identical across the picker, table, and detail header;
  both themes read well (white glyph keeps ≥ 3:1 on every palette entry —
  spot-check orange and teal, the risky ones).

## STOP conditions

- The agent API already exposes any icon/color/avatar field (re-check
  `features/agents/types.ts` and the backend agent schema at execution
  time) — if so, stop: the plan should consume it, not shadow it.
- Tailwind rejects both the arbitrary-value CSS-var gradient and the
  `style` fallback for some reason — report rather than inlining hex.

## Execution record

- The live frontend and backend agent contracts still expose no icon, color,
  or avatar field, so the implementation remains entirely client-derived with
  no API or persistence changes.
- A shared FNV-1a helper maps agent ids into eight themed hues. One
  `AgentIdentityIcon` component now serves the shared agent picker, desktop and
  mobile agent lists, and the agent configure header; conversation turns remain
  reserved for plan 004.
- The live Tailwind 4 build accepts the CSS-variable gradient syntax. Static
  contrast calculation found that the suggested 85% light gradient diluted the
  green, teal, and sky entries below 3:1, so the light gradient uses 95% and the
  dark palette uses `L=0.62`; the resulting worst case is 3.1:1.
- `pnpm check` passed on 2026-07-16: typecheck, ESLint, 81 Vitest tests,
  Prettier, Knip, dependency-cruiser, and the production build. Interactive
  browser QA was not run at the maintainer's direction.
