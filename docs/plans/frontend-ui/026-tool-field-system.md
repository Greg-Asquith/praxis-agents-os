# Plan 026: One tool field system — labeled wells everywhere

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-17, anchors verified against the working tree at
  `19ace81` with plan 022 applied. Part of the tool-surface series —
  see the series preamble in plan 025 and
  `reference-tool-card.png` for the north star and its four threads.
- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM — pure presentation, no data-path changes. The
  risk is visual regression across every tool row (this renderer is
  used by all of them) — QA must cover each row type in both themes.
- **Depends on**: 025 (needs `url`/`list` formats and the extended
  `ToolUiField`). Web-only.

## Goal

If a tool call is to read as an app surface, its values need to look
like an app's fields. Today they render in three unrelated systems:
read-only args as a cramped two-column `<dl>` in a muted box, editable
args as real form inputs, and results as `<pre>`/markdown wells. The
reference card renders *everything* as one system — a label above a
field-shaped well — so the surface reads as a form whether or not you
can type in it. This plan builds that single renderer and swaps every
tool-row surface onto it. It is the shared vocabulary the rest of the
series composes: 027's approval card interleaves these wells with live
inputs, 028's activity cards and outcome rows are built from them, and
029's interactive views sit alongside them.

## Current state (verified 2026-07-17, working tree at `19ace81` + 022)

- `ToolFieldList`
  (`apps/web/src/features/conversations/components/tool-friendly-blocks.tsx:9-31`)
  splits fields into inline (`<dl>` grid, `:20-25`) vs block
  (`BlockField`, `:69-84`) by format and value length (`isInlineField`,
  `:54-56`). Block fields render markdown in a well or raw text in a
  `<pre>`.
- Editable approval fields render separately as `Field`/`FieldLabel` +
  `Input`/`Textarea` (`approval-decision-fields.tsx:32-60`) — a
  different look from the read-only `<dl>` above them
  (`tool-call-row.tsx:108`).
- Free-text results render via `TextBlock` (`tool-call-row.tsx:119`);
  delegation rows use `TextBlock` for Task/Result/Error
  (`delegation-tool-row.tsx:89-109`); the file rows use it liberally
  (`file-tool-row.tsx:94-99,161-167,289-302`).
- `ResolvedToolField` is `{key,label,value,format}` plus 025's `items`
  (`tool-ui.ts:13-18`).
- shadcn `Field`/`FieldLabel` primitives exist via the plan-015 form
  kit (`src/components/ui/field.tsx`).

## Design decisions (this plan)

- **One component set, three modes.** `ToolField` renders
  label-above-value; the value slot is (a) a read-only well, (b) a live
  input (`Input`/`Textarea`/`Select` — wired by 027's callers), or (c)
  a block well for markdown/long text. Same paddings, radius, and label
  typography in all modes, so read-only wells and inputs sit in one
  column without a visible seam.
- **Wells can host interactivity.** The well is a container, not always
  dead text: `url` values render as real links, `list` items as chips,
  and 029 will drop entity rows (file cards with actions) into the same
  label-above-content shell. Design the API so the value slot accepts
  arbitrary children, with the string-rendering path as the default.
- **Read-only wells look like fields, not disabled inputs.** Well =
  `bg-muted/40` (or a dedicated token if contrast demands one), rounded
  to match `Input`, full-contrast `text-foreground` value text. No
  `disabled` attribute semantics — screen readers should meet labeled
  display text, not unusable form controls (label as a `<p>`, value in
  a `<div>`, mirroring `BlockField`'s current structure).
- **Density survives.** Short text/boolean/bytes/datetime fields flow
  two-up on `sm+` via grid; multiline/markdown/list/url and interactive
  children span full width. Dashboard density, form clarity.
- **Format renderers**: `url` → link styled with the `--link` token,
  `target="_blank" rel="noreferrer"`, text = host + truncated path;
  `list` → resolved `items` as quiet chips (`bg-muted` rounded spans),
  falling back to the joined string; `markdown` keeps
  `MessageMarkdown`; long text keeps a scroll-capped well
  (`max-h-80 overflow-auto` as today).
- **`TextBlock` call sites migrate; `TechnicalDetails` does not.** The
  JSON disclosure (`tool-friendly-blocks.tsx:33-52`) stays exactly as
  is — the technical escape hatch, deliberately not field-shaped.

## Steps

### 1. Build the renderer

- New `apps/web/src/features/conversations/components/tool-field.tsx`:
  `ToolField` (one resolved field, read-only) and `ToolFieldGrid` (the
  two-up flow wrapper). Props stay minimal: `field: ResolvedToolField`
  plus an optional `children` override for the value slot. Export the
  well class (e.g. `toolFieldWellClass`) so 027's inputs and 029's
  entity views share exact geometry.
- Implement the format renderers per the decisions above. Reuse
  `MessageMarkdown`; no new dependencies.

### 2. Swap the read-only surfaces

- `tool-friendly-blocks.tsx`: `ToolFieldList` becomes a thin wrapper
  over `ToolFieldGrid` (or is replaced at both call sites in
  `tool-call-row.tsx:108,118`); delete
  `InlineField`/`BlockField`/`isInlineField` and the `<dl>` markup.
- `tool-call-row.tsx:119`: free-text results render as a `ToolField`
  labeled "Result" instead of `TextBlock`.
- `delegation-tool-row.tsx:89-109`: Task, Result, Error, and the
  pending-approval count adopt `ToolField` (Error takes a destructive
  label/border accent). The metadata chips (`:117-148`) are unchanged.
- File/skill/todo custom rows are **not** swept here (that is 029/031
  territory) — but if `TextBlock` ends up with no callers after the
  sweep plans, it dies there, not here. Keep knip green either way.

### 3. Editable parity

- `approval-decision-fields.tsx`: restyle `ApprovalEditableFields` so
  its rows use `ToolField`'s label typography and well geometry, and
  inputs pick up 025's `placeholder`. Full interleaving into one column
  is 027; here it just has to stop looking like a different product.

### 4. Verify

- `cd apps/web && pnpm check`.
- Visual QA against `pnpm dev`, both themes, desktop + mobile widths:
  - Web search (auto): open row shows Search/provider wells, Answer as
    a markdown well.
  - Web search (approval): editable input and read-only wells share
    geometry seamlessly.
  - A delegation row with output and an error; a failed tool row.
  - Long values scroll inside their well; nothing overflows the row;
    chips wrap.
  - Keyboard focus rings intact on links/inputs; contrast ≥ 4.5:1 for
    value text on wells in both themes.

## STOP conditions

- A surface cannot adopt the renderer without losing information — stop
  and record it rather than adding a bespoke variant.
- Contrast on the well background fails in either theme — stop and add
  a token; no hand-tuned one-off colors.
- You need a new dependency for chips/selects — stop; shadcn primitives
  and Tailwind must suffice.
