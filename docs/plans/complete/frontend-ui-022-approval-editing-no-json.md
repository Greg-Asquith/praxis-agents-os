# Plan 022: Approval editing — labeled fields, zero JSON

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-17
- **Written**: 2026-07-16 (anchors verified against the live tree at
  `01104f7`)
- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM-HIGH — approvals are a high-risk product surface
  (wrong override args resume a run with arguments the user did not
  intend), and this plan has a small backend step. The escape hatch is
  that removing editability is always safe: a tool whose fields cannot
  be edited simply offers approve/decline, which is today's behavior
  minus the JSON box.
- **Depends on**: 005 (DONE). Includes an `apps/api` step — the gate
  covers both apps. Independent of 016–021.

## Completed implementation

- Runtime tool field presentations now expose an `editable` flag. Validation
  keeps result fields display-only, and Web Search marks only its string query
  as editable.
- Approval decisions store per-field string edits. Changed values are trimmed
  and merged into the complete original argument object; unchanged or
  whitespace-only edits send no override, and declining clears every edit.
- Awaiting Web Search approvals show the query once as a labeled, pre-filled
  input. Other arguments stay read-only, tools without editable fields retain
  Approve/Decline only, and delegation approvals no longer expose raw input.
- The JSON editor, disclosure, parsing, and JSON-specific validation copy were
  removed. The shared `isRecord` guard validates unknown tool payloads without
  duplicating local record helpers.
- `pnpm check`, `uv run ruff check .`, and the database-backed `make api-test`
  gate passed (698 API tests). Browser automation was intentionally not used
  per maintainer instruction.

## Goal

A non-technical user asked to approve a Web Search should be able to
**change what gets searched** by typing in a labeled text box — and
should never, anywhere in the product, see a JSON textarea. The
"Advanced: Edit the Request" JSON field is deleted, not restyled.
Editability becomes a per-field property a tool declares in its
presentation, and the approval block renders those fields as ordinary
pre-filled inputs.

## Current state (verified 2026-07-16 at `01104f7`)

- **The offending UI**
  (`features/conversations/components/approval-decision-fields.tsx:6-37`):
  `ApprovalOverrideInputField` is a `<details>` labeled "Advanced: Edit
  the Request" containing a monospace textarea labeled "Edited Request
  (JSON)". It renders for every non-denied approval
  (`approval-decision-block.tsx:57-69`), including delegation approvals
  (`delegation-tool-row.tsx:95`).
- **The data path**: `LocalApprovalDecision.overrideArgs` is a raw JSON
  string (`approval-decisions.ts:6-9`); `buildResumeDecisions` parses it
  with `parseOverrideArgs` (`approval-decisions.ts:116-131`) and submits
  `override_args: Record<string, unknown> | null` on
  `AgentRunResumeDecision` (`types.ts:101-106`). `PendingToolApproval`
  carries the original `args` (`types.ts:112-117`).
- **Field presentations already exist**: tools declare
  `ToolFieldPresentation(key, label, format)` server-side
  (`apps/api/services/agents/runtime/tools/contract.py:59-64`), exposed
  through `ToolFieldPresentationRead`
  (`.../tools/schemas.py:10-13`) and
  `routes/tools/list_presentations.py`; the web client consumes them as
  `ToolUiField` (`features/tools/types.ts:27-31`) and resolves display
  values in `features/conversations/tool-ui.ts:47-60`.
- **Web Search** (`apps/api/services/agents/runtime/tools/native/web_search.py:96-108`)
  declares arg fields `query` ("Search") and `model_provider` ("Search
  provider"); `query` is a required string, exactly the field a user
  would want to change.
- **Approval flow**: `use-inline-approvals.ts` holds the decision map
  and auto-submits when the last undecided request is approved
  (lines 58-68); `approval-submit-bar.tsx` sends staged decisions.
- Existing tests: `apps/web/tests/features/conversations/approval-decisions.test.ts`,
  `tool-ui.test.ts`; backend presentation tests under
  `apps/api/tests/routes/tools/`.

## Design decisions (this plan)

- **Editability is declared server-side, per arg field.** The tool
  author knows which arguments are safe and meaningful to hand-edit;
  the client never guesses from arg shape.
- **Only string-valued args get the flag** for now. Edited values submit
  as strings. No number/boolean/nested editing in this plan — a tool
  that needs it extends the format later.
- **Override args are always the full merged object**: original args
  with edited keys replaced. The client never sends a partial object,
  so it does not matter whether the runtime treats `override_args` as
  replace-or-merge.
- **No disclosure, no "Advanced".** When an awaiting-approval tool has
  editable fields, they render directly as labeled, pre-filled inputs
  inside the approval block. A tool with no editable fields shows no
  editing UI at all — and that is fine, because **Decline + "Tell the
  agent why" is the universal correction path** and already speaks
  plain language.

## Steps

### 1. Backend: `editable` flag on field presentations

- `contract.py:59`: add `editable: bool = False` to
  `ToolFieldPresentation`. In `validate_definition`, reject
  `editable=True` on `result_fields` (only args are editable).
- `schemas.py:10`: expose `editable` on `ToolFieldPresentationRead`;
  thread it through `list_tool_presentations` /
  `routes/tools/list_presentations.py` (follow how `format` flows).
- `web_search.py:104`: mark the `query` field
  `editable=True`. Leave `model_provider` read-only — provider choice
  is agent business, not something a non-technical approver should
  retarget. Do not flag any file-tool fields in this plan.
- Extend the existing presentation route/contract tests to cover the new
  key and its default (`false` when undeclared).

### 2. Frontend types and decision model

- `features/tools/types.ts:27`: add `editable: boolean` to `ToolUiField`.
- `approval-decisions.ts`: replace `overrideArgs: string` with
  `edits: Record<string, string>` (fieldKey → edited text) on
  `LocalApprovalDecision`. Delete `parseOverrideArgs`. In
  `buildResumeDecisions`, build `override_args` only when at least one
  edit differs from the original value: start from
  `normalizeToolArgs(approval.args)` as a record, overwrite edited keys
  with their trimmed string values, and submit the merged object;
  otherwise send `override_args: null`. An edit emptied back to the
  original (or to whitespace when the original was set) counts as "no
  edit" for that key. `buildResumeDecisions` therefore needs the
  original args — it already receives `PendingToolApproval[]`, which
  carries them.
- Denial still clears edits (`denyDecision`), approval preserves them
  (`approveDecision`) — same shape as today's string field.

### 3. Frontend UI: labeled inputs replace the JSON box

- Delete `ApprovalOverrideInputField` from
  `approval-decision-fields.tsx` and its render in
  `approval-decision-block.tsx:57-69` and anywhere else.
- New `ApprovalEditableFields` in `approval-decision-fields.tsx`: given
  the tool's editable `ToolUiField`s and the activity args, render one
  `Field` per editable field — `FieldLabel` from the presentation label
  ("Search"), an `Input` (or `Textarea` when `format === "multiline"`)
  seeded from the current arg value, wired to
  `decision.edits[field.key]`. No JSON, no monospace, no "Advanced".
- `tool-call-row.tsx` already resolves the tool's `ui` (line 60); pass
  the editable arg fields into `ApprovalDecisionBlock` and hide those
  keys from the read-only `ToolFieldList` above it while awaiting
  approval (the value shows once, in the input). After a decision
  resolves, rows render read-only exactly as today.
- Editing a field on an already-"approved" staged decision keeps it
  approved but must not bypass the merged-args rebuild; editing on a
  "pending" decision leaves it pending. Preserve the auto-submit
  behavior in `use-inline-approvals.ts:58-68` — typing must never
  trigger submission; only the Approve button does.
- `delegation-tool-row.tsx:95` passes no editable fields — delegation
  approvals get approve/decline plus the denial message only.
- Nudge the correction path: denial placeholder in
  `ApprovalDenialMessageField` becomes example-shaped for redirection,
  e.g. "For example: search for UK pricing instead".

### 4. Tests

- Update `approval-decisions.test.ts`: merged-object construction, the
  "unchanged edit sends null" rule, denial clearing edits, and the
  validation message when a decision is missing (the JSON error strings
  are gone).
- Add a `tool-ui`-adjacent unit test only if a new pure helper appears
  (e.g. `editableUiFields`); do not component-test the input rendering.

### 5. Verify

- `cd apps/web && pnpm check` and, for the API,
  `cd apps/api && uv run ruff check . && uv run pytest` (the
  presentation tests do not need `TEST_DATABASE_URL`, but run the full
  suite if the local test database is up).
- Manual QA against `pnpm dev` with an agent whose Web Search policy is
  approval, both themes, desktop + mobile:
  - Ask the agent to search; the approval block shows the prompt plus a
    "Search" input pre-filled with the query. Approving untouched
    resumes with `override_args: null` (verify in the network tab).
  - Edit the query, approve — the run resumes and the tool row/result
    reflect the edited query; the read-only field list shows the final
    value.
  - Grep check: `grep -rn "JSON" apps/web/src/features/conversations`
    returns no user-facing approval copy.
  - A tool without editable fields (e.g. a file write) shows only
    approve/decline; declining shows the message box with the new
    placeholder.
  - Keyboard-only pass: tab into the input, edit, reach Approve; typing
    never auto-submits.

## STOP conditions

- The runtime rejects or mangles a merged full-args override for
  web_search (e.g. resumed run drops `model_provider`) — stop and
  report; do not switch to sending partial objects without confirming
  the backend's override semantics.
- `PendingToolApproval.args` turns out to be unavailable or non-record
  for a tool that declares editable fields — stop; do not seed inputs
  from empty and silently submit fabricated args.
- Any surviving path would still show raw JSON to the user (including
  error strings) — stop and list them; "ZERO edit-the-JSON" is the
  acceptance bar, not a styling preference.
