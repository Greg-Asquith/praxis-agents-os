# Frontend UI Redesign Plans

Written 2026-07-16 at commit `158de0b` against the code as it exists on that
commit. These are visual/UX plans for `apps/web`, deliberately separate from
the product roadmap in `docs/plans/` — `docs/plans/000_README.md` remains the
authoritative ordering for feature plans and is not superseded here.

Each executor: read the plan fully before starting, honor its STOP conditions,
run every verification command, and update your row in the table below when
done. All code anchors (file:line) were verified at `158de0b`; if a file has
drifted meaningfully, reconcile against the live code before proceeding — the
live code wins on mechanics, this plan set wins on visual direction.

## The design target

`reference.png` in this directory is the target **aesthetic** — a clean,
Claude-desktop-style agent workspace. We adopt its *style and shape*, not
its information architecture (maintainer decision, 2026-07-16): the
sidebar menu, workspace switcher location, and navigation structure stay
exactly as they are today. The load-bearing visual traits every plan below
serves:

1. **A soft warm-gray sidebar on a gray page, with the content area as a
   white rounded canvas** inset from the page edges. Our existing header
   row (breadcrumbs + workspace switcher) moves inside the canvas; its
   contents do not change.
2. **Per-agent colored identity icons** wherever agents appear in content
   (pickers, tables, transcript turns) — agents stop being interchangeable
   gray robots.
3. **Praxis's restrained brand accents**: amber for primary actions and
   selection, teal for links, emerald for positive outcomes, and bright amber
   for pending/attention. Everything else stays quiet charcoal, cream, and
   warm neutral. The live brand palette at `praxis-agents.ai` is the source of
   truth (maintainer correction, 2026-07-16).
4. **Approvals as calm, scannable rows**: title, right-aligned outcome
   metric, ghost "Decline" + filled "Approve" — no heavy chrome.
5. **A floating composer card**: borderless textarea inside a rounded
   bordered card, plus-button for attachments, inline agent picker, muted
   model label, circular amber icon-only send button, small disclaimer line
   beneath.

Out-of-the-box the product should look like this while remaining themable:
every color decision goes through the semantic tokens in `src/index.css`, so
a downstream theme is still a one-file change.

## What the current UI is (for contrast)

Fully monochrome grayscale oklch tokens (`--primary` is near-black; the only
chroma anywhere is destructive red), a flush full-bleed layout with a sticky
translucent topbar, a generic nav rail (Home/Agents/Skills/Files/…),
workspace switcher in the top-right, agents represented as plain text with a
shared generic `BotIcon`, utilitarian Allow/Deny approval boxes, and a
form-like composer with a labeled Send button and inline keyboard hints.
Functional, but visibly unstyled.

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001 | Design tokens & primitive polish | P1 | M | — | DONE |
| 002 | App shell: inset canvas (visual only) | P1 | M | 001 | DONE |
| 003 | Agent identity (deterministic colored icons) | P1 | S | 001 | DONE |
| 004 | Conversation surface: transcript & message styling | P1 | M | 001, 003 | DONE |
| 005 | Tool rows & approval styling | P1 | M | 001, 004 | DONE |
| 006 | Composer redesign | P1 | M | 001, 003 | DONE |
| 007 | Pages & states polish (dashboard, lists, auth, empty) | P2 | M | 001, 002, 003 | TODO |
| 008 | Typography: Inter replaces Geist | P1 | S | — | TODO |
| 009 | Sidebar declutter & user menu redesign | P1 | S | 001 | TODO |
| 010 | Mobile shell: drawer sidebar | P1 | M | 002, 009 | TODO |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) |
REJECTED (with one-line rationale)

Completed frontend UI plans move to `docs/plans/complete/` with a
`frontend-ui-` filename prefix so they do not collide with the main numbered
roadmap.

Dependency notes:

- **001 first, alone.** It changes shared tokens and primitives that every
  other plan builds on. Do not run anything in parallel with it.
- 002 and 004/005/006 touch disjoint files (shell vs conversation feature)
  and can run in parallel worktrees after 001 lands (003 too, for the
  conversation plans).
- 003 is small and unblocks per-agent identity in 004 (turn labels) and
  006 (agent picker); land it early.
- 007 sweeps whatever the earlier plans did not touch; run it last.
- 008 (font swap) is independent of everything; land it early so the
  remaining plans' visual QA happens in the final typeface.
- 009 touches only nav config + the sidebar footer; it can run in
  parallel with 004–008 but must land before 010, which builds the
  mobile drawer around the final menu contents.
- 010 replaces `mobile-menu.tsx` and adds the sheet primitive; nothing
  else depends on it — safe to run last alongside 007.

## Shared rules for every plan

- **Tokens only.** No raw hex/oklch values in components; if a component
  needs a color that has no semantic token, the token gets added to
  `src/index.css` first. `src/components/ui/` stays generic and themable.
- **Both themes, every plan.** Each plan's dark-mode variants ship in the
  same step as the light ones. Verify visually in both.
- **Existing conventions hold**: shadcn (base-nova) on `@base-ui/react`,
  Tailwind 4 CSS-first, lucide icons, `cn()`. Prefer adding shadcn
  components over hand-building primitives. No new UI libraries, no
  animation libraries — `tw-animate-css` and CSS transitions suffice.
- **Approvals and per-tool-call UI render inline in the tool row**, never as
  separate blocks below the transcript. This is a settled product decision;
  plan 005 restyles within that constraint.
- Comments in code are terse and single-line, and only where the code cannot
  say it.
- **Gate**: `cd apps/web && pnpm check` must pass at the end of every plan
  (typecheck, eslint zero-warnings, vitest, prettier, knip, depcruise,
  build). Visual QA happens against `pnpm dev` (needs the API up —
  `make dev` from the repo root).
- Accessibility floor: visible keyboard focus everywhere (`focus-visible`
  rings survive the restyle), `prefers-reduced-motion` respected for any new
  animation, icon-only buttons keep `aria-label`s, contrast ≥ 4.5:1 for
  text on the new tinted surfaces.

## Decisions taken (recorded so nobody re-litigates)

- **`--primary` becomes Praxis amber** (was near-black). Buttons keep shadcn
  semantics — the `default` variant is now amber — and amber stays rare by
  *usage*: in-content actions use `secondary`/`outline`/`ghost`, and `default`
  is reserved for the single primary action of a surface (send, page-header
  CTA, approve-submit). Links use the separate brand-teal `--link` token.
  A proposed blue primary was rejected by the maintainer on 2026-07-16 after
  visual review because it did not match the established brand.
- **Inter replaces Geist** (maintainer, 2026-07-16; plan 008 — supersedes
  the earlier "Geist stays" decision). The reference's face is Styrene B,
  which is commercial; Inter is the closest open-licensed match, and
  Geist's geometric character read too "developer tool". Still one family
  for everything — `--font-heading` keeps aliasing `--font-sans`, no
  marketing-serif experiments.
- **Agent identity is client-derived** (deterministic hue from agent id) —
  no backend/schema change in this plan set. A persisted per-agent
  icon/color field is a possible follow-up vertical, out of scope here.
- **The sidebar nav slims to the five work sections** — Home, Agents,
  Skills, Files, Schedules. Workspaces and Settings (relabeled "Workspace
  Settings") move into the user menu (maintainer, 2026-07-16; plan 009 —
  amends the earlier "sidebar menu does not change" decision, which
  otherwise stands: no new sections, no reordering, and the workspace
  switcher stays in the header row on desktop). The mobile drawer (plan
  010) is the one exception on switcher placement: mobile has no header
  switcher, so the drawer hosts it.
- **No model picker in the composer.** The reference shows one, but in
  this product the model is bound to the agent. The composer shows the
  resolved model as a muted label (plan 006); changing the binding is an
  agent-form concern, not a composer concern.
- **Native `<details>` collapsibles stay** for tool rows / thinking /
  technical details. They work, they are accessible, and restyling them is
  cheaper and less risky than swapping in a JS accordion.

## Considered and rejected (do not re-propose)

- **Session-centric sidebar restructure** (workspace switcher into the
  sidebar, quick-action rows, an Agents section, "Recents" rename,
  breadcrumb header replacing the topbar): rejected by the maintainer
  2026-07-16 — the reference's *style* is the target, not its information
  architecture. A former version of plan 002 contained this; it was cut.
- **Search / command palette** (former plan 008): rejected 2026-07-16 —
  no search function is wanted. The sidebar ships without a search entry;
  do not add one as part of any styling pass.
