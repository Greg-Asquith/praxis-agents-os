# Plan 035: Typed argument editing — the contract beyond strings

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Status**: DONE
- **Completed**: 2026-07-31
- **Written**: 2026-07-30 against HEAD `c4777c1` (clean working tree).
- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM — touches the approval merge path that produces
  `override_args`. A wrong coercion silently changes what an approved tool
  executes. Every coercion must be covered by tests on both sides.
- **Depends on**: nothing pending (022/025/026/027 all landed). Plans 036
  and 037 depend on this one.

## Goal

Approval editing (UI-022) is string-only, twice over: the backend contract
rejects `editable=True` on any format except `text`/`multiline`
(`apps/api/services/agents/runtime/tools/contract.py:364`), and the client
independently refuses to edit any argument whose original value is not a
string (`apps/web/src/components/tool-ui/approval-card.tsx:533`, hard
submission error at
`apps/web/src/features/conversations/approval-decisions.ts:121`).

That locks out exactly the arguments users most need to correct before
approving:

- `save_memory.importance` (int 1–5) and `expires_in_days` (int) — numbers.
- `save_memory.content` — declared `format="markdown"`, so it cannot be
  editable even though its value is a plain string.
- `gmail_send_message.to/cc/bcc` and
  `google_ads_update_campaign_status.campaign_ids` — `list[str]`.
- `airtable_create_record.fields` / `airtable_update_record.fields` —
  `dict[str, Any]`. The backend already declares these `editable=True`
  (`apps/api/integrations/airtable/tools/create_record.py:106`), but the
  value is an object, so the declaration is a silent no-op.

After this plan the editing contract supports four value shapes — string
(including markdown), number, string list, and flat key/value object — with
one typed merge path, so Plan 036 can sweep the whole catalog declaratively.
No raw JSON is ever shown to the user (UI-022's "zero JSON" rule stands).

## Current state (verified 2026-07-30 at `c4777c1`)

- **Formats**: `ToolFieldFormat` is
  `text | multiline | markdown | bytes | datetime | boolean | url | list`
  in both `contract.py:21-30` and
  `apps/web/src/components/tool-ui/field-resolution.ts`.
- **Backend validation** (`contract.py:348-381`): editable ⇒ format in
  {text, multiline}; options/placeholder ⇒ editable; result fields never
  editable/secondary.
- **Client editors** (`approval-card.tsx:217-399`): options ⇒ `Select`,
  multiline or >80 chars ⇒ `Textarea`, else `Input`; `secondary` + empty ⇒
  "+ Add {label}" affordance. `editableValue` (`:533`) returns `null` for
  non-strings, downgrading the field to read-only.
- **Merge** (`approval-decisions.ts:102-134`): `edits` is
  `Record<string, string>`; changed entries are spread over
  `approval.replay_args ?? approval.args`; a non-string original aborts the
  whole submission with "This request can no longer be edited."
- **Resume**: `override_args: dict[str, Any] | None` replaces the args
  object wholesale (`apps/api/services/agent_runs/schemas.py:21`,
  `resume_run_stream.py:200`); pydantic-ai re-validates on replay, and
  `approval_events.py:265-313` audits `original_args` vs `effective_args`.
  The wire contract already carries arbitrary JSON — nothing here changes.
- **Dead code**: `editableUiFields`
  (`apps/web/src/features/conversations/tool-ui.ts:66-72`) is exported and
  tested but unused.

## Design

One principle: **the declared format is the editing type**. The server
declares what a field is; the client picks the editor and the coercion from
the format alone. No per-tool client logic.

| Format | Editable? | Editor | Edit value type sent in `override_args` |
|---|---|---|---|
| `text` | yes (today) | `Input` / `Select` with options | `string` |
| `multiline` | yes (today) | `Textarea` | `string` |
| `markdown` | **newly allowed** | `Textarea` (edit as plain text; preview unchanged) | `string` |
| `number` | **new format** | `Input type="number"` (`inputMode="decimal"`) | `number` (int if the original was int-valued) |
| `list` | **newly allowed** | chip/token input over string items | `string[]` |
| `keyvalue` | **new format** | two-column label/value grid, add/remove rows | `Record<string, string \| number \| boolean>` |
| `bytes`, `datetime`, `boolean`, `url` | no (unchanged) | — | — |

`keyvalue` is deliberately flat: values render/edit as scalars only. A
nested object inside (e.g. an Airtable linked-record array) renders that row
read-only. This keeps the Airtable `fields` case honest without building a
JSON editor.

## Steps

1. **Backend contract** (`contract.py`):
   - Add `"number"` and `"keyvalue"` to `ToolFieldFormat` and
     `VALID_TOOL_FIELD_FORMATS`.
   - Change the editable-format rule (`:364`) to allow
     {text, multiline, markdown, number, list, keyvalue}.
   - Keep: options ⇒ editable, options only on string-shaped formats
     (reject options on number/list/keyvalue), result fields never
     editable.
   - Extend `apps/api/tests/services/agents/runtime/test_tool_registry.py`
     (or the contract test module) with accept/reject cases per format.
2. **Presentation wire schema**: confirm
   `apps/api/services/agents/runtime/tools/schemas.py:12-31` passes the new
   formats through unchanged (it serializes `field.format` verbatim — no
   change expected, add a test).
3. **Client types**: add `number`/`keyvalue` to `ToolFieldFormat` in
   `field-resolution.ts` and `ToolUiField` consumers
   (`apps/web/src/features/tools/types.ts`). Give both a sensible
   *read-only* rendering in `ToolFieldValue`/`resolveToolField` (number →
   localized scalar; keyvalue → the existing labeled-well grid used for
   objects) so non-editable declarations of the new formats also display
   well.
4. **Edit state goes typed**: change `ApprovalDecision.edits` from
   `Record<string, string>` to `Record<string, EditedValue>` where
   `EditedValue = string | number | string[] | Record<string, string |
   number | boolean>`. Update `approval-card.tsx`:
   - `editableValue` accepts strings (text/multiline/markdown), finite
     numbers (number), arrays of strings (list), and flat scalar objects
     (keyvalue); anything else stays read-only exactly as today.
   - Per-format editors as in the table above. Reuse the existing field
     geometry (`fieldLabelClass`/`fieldWellClass`); the chip input and
     keyvalue grid are new small components under
     `apps/web/src/components/tool-ui/`.
   - Locked/decided state re-resolves through `{ ...args,
     ...decision.edits }` as today (`:247`) — typed values flow through the
     same read-only field pipeline.
5. **Typed merge** (`approval-decisions.ts`):
   - `buildMergedArgs` compares typed values structurally (deep-equal for
     list/keyvalue, `Number` equality for number) and drops no-op edits, so
     "no override" semantics are preserved.
   - Delete the string-original hard error (`:121-123`) for supported
     formats; keep it as the fallback for value shapes the format doesn't
     accept.
   - Number fields: empty input ⇒ treat as unchanged (never send `NaN`);
     preserve int-ness when the original was an integer.
6. **Wire or delete `editableUiFields`** (`tool-ui.ts:66`): after this plan
   the natural implementation of "which fields can this card edit" is
   format-driven; either make `approval-card.tsx` use it (updated for the
   new formats) or remove it and its test. Do not leave it dead.
7. **Proof declarations** (kept minimal here — the full sweep is Plan 036):
   - `save_memory.importance` → `format="number"`, `editable=True` — proves
     number end-to-end through a real conditional-approval tool.
   - `airtable_create_record.fields` / `update_record.fields` →
     `format="keyvalue"` (they are `multiline` today, which lies about the
     value shape). Editability becomes real once Plan 036 fixes the
     presenter drift; the format change is still correct now because the
     generic read-only rendering improves.
8. **Tests**:
   - `apps/web/tests/components/tool-ui/approval-decision-fields.test.ts`:
     editor rendering + locked-state re-resolution per new format.
   - `apps/web/tests/features/conversations/approval-decisions.test.ts`:
     typed merge, no-op detection, int preservation, flat-object rows,
     rejection fallback for unsupported shapes.
   - `apps/api/tests/routes/conversations/test_turn_streaming.py` pattern
     (`:1085`) already proves non-string `override_args` replay; add one
     resume case where an int-valued edit round-trips through a
     conditional-approval tool.

## STOP conditions

- If pydantic-ai's replay rejects a coerced value the UI produced (e.g.
  string-keyed number), stop — the coercion table above is wrong and must
  be fixed at the client, not papered over server-side.
- If any existing tool's presentation fails import-time validation after
  the contract change, stop and list them; do not weaken the validator.
- Do not add a raw-JSON textarea anywhere. If a value shape doesn't fit the
  four editors, it stays read-only.

## Verification

- `cd apps/api && make check` (or the repo-root `make check`) — contract
  validation, presentation schema, resume tests.
- `cd apps/web && pnpm check` — full frontend gate.
- Manual: run `make dev`, trigger `save_memory` with `kind="core"` in a
  conversation, edit Importance on the approval card, approve, and confirm
  the persisted memory has the edited importance and the audit metadata
  shows `override_args`.
