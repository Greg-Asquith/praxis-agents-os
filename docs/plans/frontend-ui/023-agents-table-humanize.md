# Plan 023: Agents table — drop the slug, retire "Runtime"

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-16 (anchors verified against the live tree at
  `01104f7`)
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — one component, display only.
- **Depends on**: nothing outstanding. Must land **before** 024, which
  sweeps action labels through this same file.

## Goal

The agents list stops speaking developer. The `slug` disappears from the
table (it is an API identifier; users address agents by name), and the
"Runtime" column header — which no target user will parse — is replaced
by the thing the cell actually answers: what the agent is allowed to do,
in words.

## Current state (verified 2026-07-16 at `01104f7`)

All in `features/agents/components/agents-table.tsx`:

- Desktop table headers `Name / Status / Model / Runtime / Updated /
  (actions)` (lines 66-73).
- The name cell stacks name, slug (line 87), and description (88-92).
- The "Runtime" cell (lines 100-111) renders two badges from
  `agent.tool_names.length` and `countApprovalPolicyTools(agent)`:
  `"{n} tools"` (outline) and `"{n} approval gates"` (secondary).
- The mobile row repeats the slug (line 150) and a "Runtime" meta label
  (line 166) with the same badges (167-176).

The slug is still shown on the agent detail page and used in
workspace-scoped query keys — those are out of scope; only the list
presentation changes.

## Steps

### 1. Remove the slug from the list

Delete the slug line from the desktop name cell (line 87) and the
mobile row (line 150). The name cell becomes name + optional
description; the mobile row name block loses its second line (keep the
favorite/description structure of the surrounding rows intact).

### 2. "Runtime" → "Tools", in words

- Desktop header (line 69) and mobile meta label (line 166) become
  **"Tools"**.
- The cell keeps both facts but drops the jargon: the outline badge
  stays `"{n} {tool|tools}"`; the secondary badge rewords
  `"{n} approval {gate|gates}"` to `"{n} need{s} approval"` — pluralized
  with the existing `pluralize` helper where it fits, hand-rolled for
  the needs/need verb (mirror how `approval-submit-bar.tsx:31-34`
  handles the same construction). An agent with zero tools shows a
  muted "No tools" rather than "0 tools".

### 3. Verify

- `cd apps/web && pnpm check` passes.
- Manual QA against `pnpm dev`, both themes, desktop + mobile widths:
  agents with 0, 1, and many tools; with and without approval-gated
  tools; no slug visible anywhere in the list; column alignment holds
  with the narrower name cell.

## STOP conditions

- Removing the slug leaves two agents visually indistinguishable in a
  real workspace (identical names) — stop and note it; de-duplication
  is a naming/product question, not a table-layout fix.
- Anything else in the app reads the slug **from this component** —
  stop and report (nothing should; it is display-only here).
