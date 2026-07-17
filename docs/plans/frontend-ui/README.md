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

## The tool-surface target (added 2026-07-17)

`reference-tool-card.png` in this directory is the second reference: a
Gmail send request rendered as a miniature mail composer — labeled
To/Subject/Message fields editable in place, an "Add Cc/Bcc" affordance,
one primary "Approve & Send". As with `reference.png`, we adopt the
*theory*, not the colors: **a tool call is a miniature app surface
through its whole lifecycle**, keeping the user informed, in control,
and collaborating in real time. Plans 025–031 are that series; five
threads run through all of them:

1. **Surfaces, not log lines** — the entire tool process, auto-run
   tools included, not just approvals.
2. **One click decides** — no staged decisions, no second submit
   button, ever.
3. **One field system** — every value, editable or not, renders as a
   labeled field-shaped well.
4. **Outcomes are interactive** — results are working mini-views of
   real product entities (a files list you can open, rename, download),
   reusing the product's real modals and mutations.
5. **In place, in order** — a tool call renders exactly where it
   happened in the turn, between the text written before and after it.

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
| 007 | Pages & states polish (dashboard, lists, auth, empty) | P2 | M | 001, 002, 003 | DONE |
| 008 | Typography: Inter replaces Geist | P1 | S | — | DONE |
| 009 | Sidebar declutter & user menu redesign | P1 | S | 001 | DONE |
| 010 | Mobile shell: drawer sidebar | P1 | M | 002, 009 | DONE |
| 011 | De-card pages: plain content surfaces | P1 | M | 001, 002, 007 | DONE |
| 012 | Sidebar conversation rows: compact datetime | P2 | S | 010 | DONE |
| 013 | Button text: normal weight, Title Case actions | P2 | S | 010, 011, 012 | DONE |
| 014 | Remove unneeded useEffects | P2 | M | — | DONE |
| 015 | Form kit: shared sections, action bar, alerts | P1 | M | 011, 013 | DONE |
| 016 | Skill form: create wizard (builds shell) & edit wizard | P1 | M | 015 | DONE |
| 017 | Agent form: create wizard & edit clarity | P1 | L | 016 | DONE |
| 018 | Schedule form: create wizard & edit clarity | P1 | M | 016 | DONE |
| 019 | Files: thumbnails, detail modal with preview, rename | P1 | L | 011, 013 | DONE |
| 020 | Login page: brand panel art & card breathing room | P2 | M | 013 | DONE |
| 021 | Conversation headers: compact banner, source without pills | P1 | M | — | DONE |
| 022 | Approval editing: labeled fields, zero JSON | P1 | L | 005 | DONE |
| 023 | Agents table: retire "Runtime" | P2 | S | — | DONE |
| 024 | "Configure" dies: Edit language sweep | P2 | S | 023 | DONE |
| 025 | Tool presentation contract v2 | P1 | M | 022 | DONE |
| 026 | One tool field system: labeled wells | P1 | M | 025 | DONE |
| 027 | Approval card: form-first, one-click | P1 | L | 025, 026 | DONE |
| 028 | Live activity card & outcome rows | P1 | L | 026, 027 | DONE |
| 029 | Interactive outcomes: files proof case | P1 | L | 026, 028 | DONE |
| 030 | In-place tool calls: ordered turns | P1 | L | — | DONE |
| 031 | Catalog sweep: every tool a full surface | P1 | M | 025–030 | DONE |
| 032 | Resilient conversation streams across navigation | P1 | M | — | DONE |

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
- 010 replaces `mobile-menu.tsx` and adds the sheet primitive; 012 and
  013 now depend on it — land it before them.
- 011 (plans written 2026-07-16 at `d1c4a89`) touches route/feature
  files only, disjoint from 010's shell files — safe in parallel
  with 010.
- 012 restyles the sidebar conversation rows that 010's drawer reuses;
  run it after 010 so the row work happens once.
- 013 sweeps action-label literals across files 010 adds and 011
  deletes — run it last, after 010–012, so it sweeps final copy.
- 014 (written 2026-07-16 at `b011664`) is a code-health plan, not a
  visual one. No hard dependencies, but do not run it concurrently
  with 012/013 — it touches the same conversation-route and callback
  files 013 sweeps.
- 015–018 (the forms series, written 2026-07-16 against the tree at
  `9d597e1` with 013 applied) run strictly after 013's commit lands.
  015 is the foundation and runs alone against the form files; 016
  builds the wizard shell on the smallest form (skills) and must
  precede 017/018, which touch disjoint feature directories and may
  run in parallel worktrees.
- 019 (written 2026-07-16 at `75da3b5`) is independent of 014–018 —
  the files feature directory is disjoint from everything they touch,
  so it can run in a parallel worktree at any point after 013. It is
  the first plan in the series with a backend step (widening the
  preview grant), so its gate includes the `apps/api` checks.
- 020 (written 2026-07-16 at `75da3b5`) touches only the auth screens
  and can run in parallel with 015–019. Its copy pass grazes the two
  OAuth callback routes that 014's in-flight work modified — land
  014's commit first, or skip those two files (the plan says how).
- 025–031 (the tool-surface series, written 2026-07-17 against the
  working tree at `19ace81` with plan 022's changes applied) run after
  022's commit lands. 025 is backend-first and runs alone; 026 builds
  the field renderer on it; 027 (approval card + one-click flow) and
  028 (live/outcome states) both touch `tool-call-row.tsx` and the
  card shell — run them sequentially, 027 first. 030 (in-place
  ordering) touches the parser/reducer/`message-row.tsx`, disjoint
  from 025/026 but overlapping 027/028's row rendering — run it
  before 027, or coordinate carefully. 029 needs 026's shells and
  028's outcome-row shape. 031 is the closing sweep and runs last,
  after everything.
- 032 (written 2026-07-17 at `89ac993`) is a correctness plan, not a
  visual one (precedent: 014): it fixes the diagnosed stream-freeze bug
  on the `/new` → `/conversations/{id}` transition and hardens the
  stream lifecycle. No dependencies, but it touches
  `src/app/router.tsx` (router-wide pending component + loaders) and
  the conversation stream files — do not run it concurrently with any
  plan editing those.
- 021–024 (written 2026-07-16 at `01104f7`) are independent of the
  outstanding 017–020 (disjoint files) and may run in parallel
  worktrees with them. Within the set: 021 (conversation headers) and
  022 (approvals) both live in `features/conversations/` but in
  disjoint files — parallel is fine, sequential is simpler. 023 must
  land before 024, which sweeps copy through the same
  `agents-table.tsx`. 022 is the second plan with a backend step (the
  `editable` field-presentation flag), so its gate includes the
  `apps/api` checks.

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
- **Pages render content plainly — wrapper cards die** (maintainer,
  2026-07-16; plan 011). The `PageHeader` is a page's only title; the
  per-page `Card` whose header restated it is removed, and the mobile
  `ResponsiveListItem` boxes flatten to divider-separated rows (the
  card-in-card fix). `Card` remains for genuinely grouping surfaces:
  auth, dialogs, detail-page form sections.
- **List datetimes stay, compact** (maintainer, 2026-07-16; plan 012).
  Sidebar conversation rows keep an absolute timestamp — moved to the
  meta line and shortened by age (time today, "16 Jul" this year, full
  date beyond) — rather than being dropped or made relative.
- **Action labels are Title Case; button text is normal weight**
  (maintainer, 2026-07-16; plan 013). `font-medium` in the button
  primitive read as bold in Inter; buttons drop to `font-normal`, and
  every action label ("New Schedule", "Save Changes") uses Title Case.
  This settles the sentence-case/Title Case split — plan 009's
  "sentence-cased" phrasing for menu items is superseded (those labels
  were already Title Case in practice).
- **`useEffect` is reserved for external-system sync** (maintainer,
  2026-07-16; plan 014). Effects exist only to synchronize with
  systems outside React — connections, the DOM, timer cleanup. Data
  fetching on navigation goes in route loaders, derived state in
  render, persistence in event handlers, polling in the query layer.
  Plan 014's audit table records the five justified survivors; new
  effects need the same justification.
- **The target user is not necessarily technical** (maintainer,
  2026-07-16; plans 015–018). Abstract complexity away wherever
  possible: plain-language copy states outcomes rather than mechanisms,
  anything with a safe default stays out of create flows, and expert
  fields sit behind a collapsed Advanced disclosure. This constraint
  applies to all future UI work, not just the forms series.
- **Create flows are wizards; edit flows are sectioned pages by default**
  (maintainer, 2026-07-16; plans 015–018). Creating an Agent, Skill, or
  Schedule walks a stepped wizard (plain-question step titles, one
  primary action per screen, optional steps skippable, review before
  commit where the stakes warrant it). Editing keeps a single page of
  well-spaced card sections with a sticky action bar by default. UI-016
  established a maintainer-directed exception for Skills: editing also uses
  the wizard so Documents remains an intermediate step and the final save
  happens on Availability. Both patterns are built on the shared kit in
  `src/components/forms/` — new entity forms use it rather than hand-rolling
  scaffolding.
- **Detail surfaces are centered modals, not side sheets** (maintainer,
  2026-07-16; plan 019). The file detail "sheet" (a Dialog dressed as a
  right-hand panel) becomes a standard centered modal; new detail
  surfaces follow suit. And previews lead: for visually renderable
  files (images, video, PDF, HTML, text) the content shows inline at
  the top of the modal — never behind a tab — while technical metadata
  (revision UUIDs, content hashes) hides behind a closed "Technical
  details" disclosure or disappears when inapplicable to the file type.
- **Previews are passive and unaudited; opens/downloads are audited**
  (recorded 2026-07-16; plan 019 extends an existing backend decision).
  The preview grant skips the file-read audit event by design; plan 019
  widens which categories can be previewed (image → +video +PDF)
  without changing that split. Do not add audit events to previews or
  remove them from downloads.
- **Brand art is built from tokens — CSS gradients + inline SVG, no
  raster assets** (recorded 2026-07-16; plan 020). Decorative
  compositions (the auth brand panel, any future empty-state art)
  derive from the existing semantic tokens — including the
  `--agent-1…8` identity hues — via `color-mix` and inline SVG, so
  they follow both themes for free and keep the one-file theming
  contract. A generated/raster image is a maintainer-approval
  exception, never a default.
- **Conversation source avoids generic taxonomy pills** (maintainer direction,
  2026-07-16; plan 021). Direct is the default and goes unmarked; list rows use
  quiet scheduled/delegated icons, and delegated detail headers say "Started by
  another agent." Scheduled detail headers use one named context badge beside
  the title (`Schedule - {cadence}`), not a generic "Scheduled" pill, and keep
  right-aligned Ran/Updated timestamps. Approval, Unread, and run-status badges
  stay because they carry state.
- **Users never see or edit JSON — anywhere** (maintainer direction,
  2026-07-16; plan 022). The approval "Advanced: Edit the Request" JSON
  textarea is deleted, not restyled. Editability is a per-field flag a
  tool declares on its server-side presentation (`editable` on
  `ToolFieldPresentation`); flagged fields render as ordinary labeled,
  pre-filled inputs in the approval block. Tools with nothing flagged
  offer approve/decline only — Decline + "tell the agent why" is the
  universal correction path. This bars raw-JSON editing surfaces from
  all future UI, not just approvals.
- **List columns speak user language** (maintainer direction,
  2026-07-16; plans 017, 023–024). Identifiers users didn't choose (slugs)
  are entirely system-managed and never appear in user-facing surfaces;
  "Runtime" becomes "Tools" with counts in
  words ("2 need approval"); row actions on user-created entities say
  **Edit** (pencil icon), with plan 013's "Save Changes" for the commit.
  "Configure" (and user-facing "configured") is retired from copy;
  "Update" stays an API term.

- **Tool calls are surfaces through their whole lifecycle**
  (maintainer direction, 2026-07-17; plans 025–031). A live card while
  running (arg fields visible, moving status, elapsed time), a
  form-first card when a decision is needed, a compact outcome-first
  row when finished. Auto-run tools get the treatment too — this is
  the entire tool process, not an approvals feature.
- **Approval decisions are one click** (maintainer direction,
  2026-07-17; plan 027 — supersedes plan 022's staged-decisions +
  "Send Decisions" bar, which is deleted, not restyled). "Approve &
  {verb}" commits and submits; Decline is a single confirm with the
  optional note; decided cards lock. No second button layer anywhere.
- **One field system for tool values** (2026-07-17; plan 026). Every
  argument and result renders as a labeled field-shaped well — real
  inputs when editable, wells when not — one geometry, no
  `<dl>`/`<pre>`/input mixture.
- **No generic Technical Details in conversation tool UI** (maintainer
  direction, 2026-07-17; plan 027 correction). Declared user-facing fields are
  the review surface; raw tool arguments/results remain in runtime data but do
  not get a generic JSON disclosure in the transcript.
- **Tool outcomes are interactive working views** (maintainer
  direction, 2026-07-17; plan 029). Entity-bearing results (files
  today) render as miniature versions of their product surface with
  real actions — open the detail modal, rename, download — always by
  reusing the owning feature's components, queries, and mutations,
  never by re-implementing them. External integrations (e.g. Google
  Drive) adopt the same presenter pattern when they land, shipping
  their actions with the integration vertical — nothing speculative
  before then.
- **Tool calls render in place, in order** (maintainer direction,
  2026-07-17; plan 030, corrected during 027 review). Thinking is hidden
  turn-level reasoning and always renders first in one collapsed disclosure.
  Beneath it, text and tool surfaces follow the sequence they actually happened
  in. Order is reconstructed client-side from the already-ordered payloads; no
  protocol change.
- **Liveness needs no protocol changes** (recorded 2026-07-17; plan
  028). Tool args arrive whole in one stream event, so there is no
  "watch the agent type" animation to build — liveness is motion on
  the status line, visible fields, and a client-measured elapsed
  count, live-run only. Do not propose arg-delta streaming for UI
  effect.
- **No per-provider brand logos on tool surfaces** (recorded
  2026-07-17; plan 025). The reference's Gmail "M" is not adopted: the
  semantic icon token set is the extension point, keeping the
  tokens-only theming contract; new tokens arrive with the tools that
  need them.

## Considered and rejected (do not re-propose)

- **Session-centric sidebar restructure** (workspace switcher into the
  sidebar, quick-action rows, an Agents section, "Recents" rename,
  breadcrumb header replacing the topbar): rejected by the maintainer
  2026-07-16 — the reference's *style* is the target, not its information
  architecture. A former version of plan 002 contained this; it was cut.
- **Search / command palette** (former plan 008): rejected 2026-07-16 —
  no search function is wanted. The sidebar ships without a search entry;
  do not add one as part of any styling pass.
