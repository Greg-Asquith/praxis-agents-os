# Plan 025: Tool presentation contract v2 — surface-grade fields & actions

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-17
- **Written**: 2026-07-17, anchors verified against the working tree at
  `19ace81` **with plan 022's (uncommitted) changes applied**. Land
  022's commit before starting; if files have drifted, live code wins
  on mechanics, this plan set wins on direction.
- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM — additive contract change; every new key
  defaults safely, so undeclared tools render exactly as today. The
  risk is validation gaps letting a tool declare nonsense (options on a
  read-only field) that later confuses the card UI.
- **Depends on**: 022 (DONE). Backend + wire + client-types plan; the
  gate covers both apps. No rendering changes here — 026–031 consume
  what this plan adds.

## Completed implementation

- Extended runtime field presentations with placeholders, closed options,
  secondary placement, and `url`/`list` display formats; presentations now
  carry a tool-specific approval action label.
- Added import-time invariants for string-only editable formats, editable-only
  options/placeholders, non-blank unique options, arg-only secondary fields,
  display-only results, and non-blank configured approval labels.
- Mirrored every new key through the Pydantic route schema and React types with
  additive defaults. Web Search proves the populated contract with
  "Approve & Search" and a query placeholder.
- Added safe HTTP(S)-only URL resolution and scalar-list resolution with both
  joined display text and individual items. No rendering components changed.
- Verification passed: backend Ruff; 706 database-backed API tests; full
  frontend `pnpm check` with 140 tests, lint, formatting, dead-code analysis,
  dependency-cruiser, typecheck, and production build; `git diff --check`.
  Browser automation was intentionally not used per maintainer instruction.

## The tool-surface series (025–031)

`reference-tool-card.png` in this directory is the north star for this
series (maintainer, 2026-07-17): a Gmail send request rendered as a
miniature mail composer — labeled To/Subject/Message fields, editable in
place, one primary "Approve & Send". We adopt its *theory*, in Praxis
tokens: **a tool call is a miniature app surface through its whole
lifecycle** — a live card while running, a one-click form when
permission is needed, and an interactive working view of real product
entities when finished. Four threads run through every plan in the
series:

1. **Surfaces, not log lines** — the entire tool process, auto-run
   tools included, not just approvals.
2. **One click decides** — no staged decisions, no second submit
   button, ever.
3. **One field system** — every value, editable or not, renders as a
   labeled field-shaped well.
4. **Outcomes are interactive** — results render as working
   mini-views (a files list you can act on), reusing the product's real
   modals and mutations; the same pattern future integrations (Google
   Drive et al.) will adopt.
5. **In place, in order** — a tool call renders exactly where it
   happened in the turn, between the text the agent wrote before and
   after it, never regrouped to the top of the turn.

The audience constraint stands: the target user is non-technical and at
home in ordinary SaaS dashboards.

## Goal

The presentation contract can currently say "show these keys as labeled
fields, one of which is an editable string." It cannot express what the
card surfaces need: a verb-labeled primary action ("Approve & Search"),
a closed list of choices rendered as a select, an optional field tucked
behind an "Add Cc/Bcc"-style affordance, a placeholder, or a
link-shaped value. This plan extends the contract so tools declare
those server-side, with the client rendering following in 026–028.

## Current state (verified 2026-07-17, working tree at `19ace81` + 022)

- `ToolFieldPresentation`
  (`apps/api/services/agents/runtime/tools/contract.py:58-65`): `key`,
  `label`, `format` (`text|multiline|markdown|bytes|datetime|boolean`,
  `contract.py:20`), `editable: bool = False`.
- `ToolPresentation` (`contract.py:68-79`): `icon`, three status-label
  templates, `approval_title`, `approval_prompt`, `arg_fields`,
  `result_fields`. No action labels.
- Validation in `_validate_presentation` (`contract.py:238-253`): icon
  token membership, non-blank key/label, known format, result fields
  never editable.
- Wire schema mirrors the dataclasses 1:1
  (`apps/api/services/agents/runtime/tools/schemas.py:10-54`); web
  types mirror the wire
  (`apps/web/src/features/tools/types.ts:25-43`).
- Client resolution: `resolveUiFields` / `displayValue`
  (`apps/web/src/features/conversations/tool-ui.ts:48-61,142-156`)
  produce `ResolvedToolField {key,label,value,format}` — string values
  only; arrays and objects resolve to nothing.
- `editableUiFields` (`tool-ui.ts:63-69`) filters to
  `editable && typeof value === "string"`.
- Example declarations: `native/web_search.py:96-108` (the richest),
  `files/write_file.py:58-69`, `files/promote_scratch.py:47-59`;
  `files/list_files.py:52-57` and `planning.py:44-49,98-103` declare
  labels only.

## Design decisions (this plan)

- **Declarative-first, with a deliberate seam.** The contract owns
  everything generic: labels, formats, editability, choices, action
  verbs. It does **not** own entity interactivity — "this result row is
  workspace file X, offer rename/open" comes from the tool's typed
  `output_model` (`contract.py:104`) interpreted by a client custom
  presenter (`tool-call-row-registry.tsx:30-37`). Plan 029 builds that
  side; this plan keeps the contract free of entity-specific keys.
- **`options` means a closed choice.** A field with options renders as
  a select (027). The runtime already validates args via the tool
  signature; options are presentation truth and must not contradict the
  signature. Options are only allowed on editable fields.
- **`secondary` means "real but not headline."** Secondary arg fields
  with no value hide behind an "Add {label}" affordance in the approval
  card and are omitted from read-only views; with a value they render
  normally. This is the "Add Cc/Bcc" mechanic.
- **`approve_label` is a Title Case verb phrase** ("Approve & Search",
  "Approve & Save") per the plan-013 action-label rules. Empty means
  the generic "Approve". Decline never varies — it is the universal
  correction path (settled, plan 022).
- **Two new formats only: `url` and `list`.** `url` renders as a safe
  link (client enforces http/https); `list` accepts an array of scalars
  and joins/chips them. No nested-object format — objects stay in
  Technical details. Editing stays string-only (settled, plan 022);
  derived formats are never editable.
- **No brand logos.** Per-provider raster branding (the Gmail "M" in
  the reference) is rejected — the icon token set
  (`contract.py:40-55`) is the extension point, and new tokens arrive
  with the tools that need them. This keeps the tokens-only theming
  contract intact.

## Steps

### 1. Backend contract

- `contract.py`: extend `ToolFieldPresentation` with
  `placeholder: str = ""`, `options: tuple[str, ...] = ()`,
  `secondary: bool = False`. Add `"url"` and `"list"` to
  `ToolFieldFormat` / `VALID_TOOL_FIELD_FORMATS`. Extend
  `ToolPresentation` with `approve_label: str = ""`.
- `_validate_presentation` additions:
  - `options`/`placeholder` require `editable=True`; options entries
    non-blank and unique; `secondary` is args-only.
  - `editable=True` requires format `text` or `multiline` — the
    string-only editing rule becomes a validated invariant instead of a
    client-side filter.
  - `approve_label`, when set, must be non-blank after strip.
- One proof declaration only (the sweep is plan 031): `web_search.py`
  gains `approve_label="Approve & Search"` and a `placeholder` on the
  `query` field (e.g. "What should the agent search for?").

### 2. Wire + client types

- `schemas.py`: mirror the new keys on `ToolFieldPresentationRead` /
  `ToolPresentationRead.from_presentation` (options as `list[str]`).
- `apps/web/src/features/tools/types.ts`: add `placeholder: string`,
  `options: string[]`, `secondary: boolean` to `ToolUiField`;
  `approve_label: string` to `ToolUi`; extend `ToolUiFieldFormat` with
  `"url" | "list"`.

### 3. Client resolution (data only, no rendering)

- `tool-ui.ts` `displayValue`: `list` accepts `string[]`/`number[]` and
  joins with `", "`; `url` accepts only strings that parse as http(s)
  URLs (else resolve to nothing — a non-URL value falls back to
  Technical details rather than rendering a broken link).
- `ResolvedToolField` gains `items?: string[]` (set for `list`); 026
  renders chips/links from it.
- `editableUiFields` keeps its string filter (now backed by the
  server-side invariant).

### 4. Tests

- Contract validation tests (alongside the existing presentation
  validations in `apps/api/tests/services/agents/runtime/`): options on
  a read-only field rejected, secondary result field rejected, editable
  markdown rejected, url/list accepted, blank approve_label rejected.
- Presentation route test
  (`apps/api/tests/routes/tools/test_tool_catalog_routes.py`): new keys
  present at defaults (`placeholder: ""`, `options: []`,
  `secondary: false`, `approve_label: ""`) for an undeclared tool, and
  populated for web_search.
- `apps/web/tests/features/conversations/tool-ui.test.ts`: list join,
  url rejection of non-http values, unchanged behavior for existing
  formats.

### 5. Verify

- `cd apps/api && uv run ruff check . && uv run pytest`
- `cd apps/web && pnpm check`
- Browser network tab (or curl) against `/tools/presentations`:
  web_search shows `approve_label` and the query placeholder; every
  other entry carries the new keys at defaults.

## STOP conditions

- A new key cannot default cleanly (a serialization path drops or
  renames it) — stop; the contract must stay additive so stale clients
  and undeclared tools are unaffected.
- The `editable requires text|multiline` invariant breaks an existing
  declaration — stop and report which tool; do not weaken the rule.
- You find yourself adding entity-specific keys (file ids, share links)
  to the contract — stop; that belongs to output models + custom
  presenters (plan 029).
- You find yourself changing rendering to make a test pass — stop;
  rendering belongs to 026–028.
