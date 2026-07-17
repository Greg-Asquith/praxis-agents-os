# Plan 031: Catalog sweep — every tool a full surface

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-17, anchors verified against the working tree at
  `19ace81` with plan 022 applied. Part of the tool-surface series —
  see the series preamble in plan 025. This is the closing sweep: after
  it, no tool in the product renders as a bare technical row, and the
  custom presenter rows share the series' shells instead of their own
  scaffolding.
- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM — mostly declarations and restyles on
  foundations the earlier plans proved. The subtle risk is copy:
  status/approval templates are user-facing product language for
  non-technical users and deserve the same care as any UI copy.
- **Depends on**: 025–030 (all of them — this plan applies the whole
  system across the catalog). Backend declarations + web alignment;
  the gate covers both apps.

## Goal

The series' machinery only pays off if every tool uses it. After this
plan: every runtime tool declares a full presentation (icon, all three
status templates, approval title/prompt where approval is possible, a
verb `approve_label`, arg/result fields with editability, options,
placeholders, and secondary flags where they earn it); collapsed rows
across the product show outcome language, approval cards show real
forms, and the custom presenter rows (files, todos, skills,
delegation) sit visually inside the same card/field system as
everything else — custom only where a mini-view genuinely needs code
(interactive file rows, the todo checklist, image previews).

## Current state (verified 2026-07-17, working tree at `19ace81` + 022)

- **Declarations are thin outside web_search.**
  `native/web_search.py:96-108` is complete (plus 025's approve_label/
  placeholder); `files/write_file.py:58-69` and
  `files/promote_scratch.py:47-59` declare labels + a couple of arg
  fields; `files/list_files.py:52-57`, `files/read_file.py:41-46`, and
  both planning tools (`planning.py:44-49,98-103`) declare status
  labels only — no fields, no approval verbs.
- **Custom rows carry their own scaffolding.** `file-tool-row.tsx`
  hand-rolls headers/`TextBlock`s per subcase (`:71-363`);
  `todo-list-row.tsx`, `skill-activation-row.tsx`,
  `skill-document-read-row.tsx`, and `delegation-tool-row.tsx` each do
  their own version. After 026–029 land, several of these blocks are
  the last `TextBlock`/ad-hoc summaries in the transcript.
- **Fallback rows still occur**: a tool without declarations renders
  generic verb + `autoUiFields` (`tool-call-row.tsx:70-84`) — fine as
  a safety net, wrong as the steady state for first-party tools.
- The registry comment (`tool-call-row-registry.tsx:30-37`) already
  states the doctrine: presenters only when declarative config cannot
  express the UI.

## Design decisions (this plan)

- **Declarative-first, presenters for mini-views only.** Each custom
  presenter must justify itself against the 025 contract: file rows
  stay (interactive entities, 029), the todo checklist stays (a real
  mini-view), skill rows are reviewed — if the declarative card can
  express them, they become declarations and the presenter dies.
  Delegation stays custom (it renders another agent's run) but adopts
  the shared shells.
- **Copy is outcome-language, Title Case actions.** Status templates
  say what happened to the user's world ("Saved {name} to Your
  Files"), approve labels are verbs ("Approve & Save"), and technical
  vocabulary (bytes offsets, provider ids) moves behind field labels a
  non-technical user understands or into Technical details. Plans 013
  and 015–018's copy rules apply verbatim.
- **Fields where the user would look.** Every approval-capable tool
  declares the fields a user needs to judge the request (and marks
  editable/secondary/options deliberately — editability is a per-field
  product decision, settled in 022, not a default). Every tool with a
  meaningful result declares result fields so outcome rows (028) get
  their collapsed metric and outcome-first open state.
- **No speculative declarations.** A field nobody would read does not
  get declared; `autoUiFields` remains the honest fallback for
  genuinely technical tools. Do not pad.

## Steps

### 1. Backend declaration sweep

For each runtime tool, complete its `ToolPresentation` (this is a
product-copy exercise as much as a code one; keep a table in the PR
description):

- `web_search`: already complete; confirm result field `answer` +
  short result metric behavior.
- `list_files`: arg fields (`name_contains` "Matching", secondary;
  `limit` stays undeclared), result handled by the 029 interactive
  view; completed label gains the count ("Found {total} Files") if the
  output model exposes it.
- `read_file`: arg fields (name/mode), approval unused (read tools
  default auto) — status labels reviewed for outcome language.
- `write_file`: `approve_label="Approve & Save"`; `name` editable with
  placeholder; `content` stays read-only multiline (agent-authored
  content is reviewed, not rewritten, in the approval card — the
  denial path handles redirection); result fields for the saved file.
- `promote_scratch`: `approve_label="Approve & Save"`, arg fields as
  declared plus editable `file_name`.
- `write_todos` / `read_todos`: status labels reviewed; no fields (the
  checklist row is the view).
- Delegation runtime tools (under `runtime/delegation/`): approval
  title/prompt/approve_label ("Approve & Delegate"), task preview as a
  declared multiline arg field where the args carry it.
- Extend the presentation route test to assert every registered
  first-party tool now declares at least icon + the three status
  labels (a floor, so future tools cannot ship bare).

### 2. Custom row alignment (web)

- `file-tool-row.tsx`: replace remaining ad-hoc headers/`TextBlock`s
  with the shared header + 026 field shells (029 already made the
  entity rows; this step retires the rest of the bespoke scaffolding —
  byte ranges and hints move into fields or Technical details).
- `todo-list-row.tsx`, `skill-activation-row.tsx`,
  `skill-document-read-row.tsx`: adopt the shared shell/field
  primitives around their mini-views; review the skill rows against
  the declarative card and delete any that no longer earn custom code.
- `delegation-tool-row.tsx`: final alignment pass (026/027 already hit
  it); running delegations show the elapsed suffix (028), completed
  ones the outcome metric.
- Delete `TextBlock` (`tool-call-content-blocks.tsx`) if this sweep
  removes its last caller; knip enforces.

### 3. Verify

- `cd apps/api && uv run ruff check . && uv run pytest`
- `cd apps/web && pnpm check`
- Manual QA (`pnpm dev`, both themes, desktop + mobile) — run one
  conversation that exercises every family: web search (approval),
  file write (approval) + list + read, todos, a skill activation, and
  a delegation. Checklist per call: correct icon, outcome-language
  collapsed line, card while running, form-first approval card with
  verb button, outcome-first open state, no raw JSON outside Technical
  details, no bare generic rows for first-party tools.

## STOP conditions

- A tool's honest presentation needs a contract feature 025 does not
  have (e.g. a numeric editable field, a table format) — stop and
  record it as a follow-up contract proposal; do not bend an existing
  format to fake it.
- A skill/todo presenter cannot be expressed declaratively but also
  cannot adopt the shared shells without losing its view — stop and
  report the conflict rather than forking shell styles.
- Copy review stalls on naming (what a non-technical user calls a
  scratch draft, a delegation) — stop and collect the open questions
  for the maintainer in one batch instead of guessing inconsistently.
