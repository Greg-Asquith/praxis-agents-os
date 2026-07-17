# Plan 023: Agents table — retire "Runtime"

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Updated**: 2026-07-16 after the UI-017 follow-up removed system-managed
  slugs from every user-facing agent surface. This plan now owns only the
  remaining Runtime-to-Tools language change.
- **Written**: 2026-07-16 (anchors verified against the live tree at
  `01104f7`)
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — one component, display only.
- **Depends on**: nothing outstanding. Must land **before** 024, which
  sweeps action labels through this same file.

## Completed implementation

- Desktop and mobile list labels now say "Tools" instead of "Runtime".
- A shared responsive summary renders singular/plural tool counts, plain-language
  approval counts ("1 needs approval" / "2 need approval"), and muted "No
  tools" copy for agents without tools.
- Agent names and optional descriptions remain the only rendered identity copy;
  system-managed slugs remain absent.
- `pnpm check` passed. Browser-based manual QA was not run because the executor
  was explicitly instructed not to use browser verification.

## Goal

The agents list stops speaking developer. The "Runtime" column header — which
no target user will parse — is replaced by the thing the cell actually
answers: what the agent is allowed to do, in words. Slug removal already landed
as part of the UI-017 maintainer follow-up.

## Current state (verified 2026-07-16 at `01104f7`)

All in `features/agents/components/agents-table.tsx`:

- Desktop table headers `Name / Status / Model / Runtime / Updated /
  (actions)` (lines 66-73).
- The name cell stacks name and optional description; slug has already been
  removed.
- The "Runtime" cell (lines 100-111) renders two badges from
  `agent.tool_names.length` and `countApprovalPolicyTools(agent)`:
  `"{n} tools"` (outline) and `"{n} approval gates"` (secondary).
- The mobile row has no slug and retains a "Runtime" meta label with the same
  badges.

The slug remains in API data and internal identifiers only. It must not return
to rendered copy.

## Steps

### 1. Preserve completed slug removal

No implementation work remains here. Confirm the desktop and mobile rows still
render name plus optional description without exposing the system slug.

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

- Any user-facing slug has returned — stop and remove the regression; slugs are
  system-managed identifiers.
