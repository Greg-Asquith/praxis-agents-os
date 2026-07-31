# Plan 036: Editability sweep — every approvable argument editable

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
- **Effort**: L
- **Risk**: MEDIUM — mostly declarative, but step 2 (custom presenters stop
  hand-copying approval fields) touches every approval-capable presenter,
  and one declaration mistake makes a governed argument editable that
  shouldn't be. Review the table below field by field.
- **Depends on**: 035 (typed editing formats: `number`, `keyvalue`,
  editable `markdown`/`list`).

## Goal

UI-022 built argument editing and UI-031 swept presentations, but editable
coverage stalled at six tools. This plan is the full-catalog audit (below)
plus the work to close it: **every argument a user can be asked to approve
is either editable or deliberately locked, and the decision is recorded
here.** It also removes the structural cause of drift: custom presenters
hand-copy `ApprovalField[]` instead of consuming the server declaration —
which is exactly how Airtable's backend-declared editable `fields` became
read-only in the UI
(`apps/web/src/integrations/airtable/presenters/write.tsx:18-22` wins over
`apps/api/integrations/airtable/tools/create_record.py:106`).

## The audit (verified 2026-07-30 at `c4777c1`)

How a tool reaches an approval card, for reference:
(a) `default_policy=approval` (downgradable per agent unless
`supports_auto=False`); (b) per-agent `tool_policies` upgrade of any
configurable tool — **including every read tool**; (c) in-body
`ApprovalRequired` (`write_file`, core-kind `save_memory`/`update_memory`);
(d) run-envelope `require_approval` for external writes on
scheduled/event/delegated runs (`dispatch.py:335-354`). Auto-mounted tools
(memory, files) can't be policy-upgraded, so only (c) applies to them.
`write_todos`, `read_todos`, `build_chart`, `list_delegate_agents` have
`supports_approval=False` and never show a card — out of scope.

### Approval-capable tools

| Tool (definition) | Card via | Editable today | Target state |
|---|---|---|---|
| `web_search` (`native/web_search.py:115`) | a | `query`, `model_provider` | ✔ done (reference declaration) |
| `write_file` (`files/write_file.py:38`) | c | `name` | `name` only. `content` stays locked — it is staged to object storage and display-redacted (`staged_tool_content.py:139`); recorded as rejected below. |
| `save_memory` (`memory.py:76`) | c | none | `title` (text), `content` (markdown, editable), `scope` (options `agent/user/workspace`), `kind` (options `core/note`), `memory_type` (options `fact/preference/episode/outcome`, currently undeclared), `importance` (number, from 035), `expires_in_days` (number, secondary). |
| `update_memory` (`memory.py:233`) | c | none — **no arg_fields at all** | Declare: `memory_id` (locked), `title`, `content` (markdown), `importance` (number), `expires_in_days` (number, secondary) — all editable. |
| `forget_memory` (`memory.py:296`) | never (auto-mounted, no in-body approval) | none | Declare read-only `memory_id` + `reason` fields for transcript quality; editability n/a. |
| `create_artifact` (`artifacts.py:26`) | a, d | none | `title` editable (text). `content` editable (multiline). `artifact_type` stays locked — changing type at approval invalidates content (rejected below). |
| `update_artifact` (`artifacts.py:80`) | a, d | none | `title`, `content` editable; `artifact_id` locked. |
| `delegate_to_agent` (`delegation/build_delegation_tools.py:44`) | d, child approvals | none — presenter passes `fields={[]}` (`delegation-tool-row.tsx`) | `task` editable (multiline); `agent_id` locked. Requires the delegation presenter to consume declared fields (step 2). |
| `gmail_send_message` (`gmail/tools/send_message.py:89`) | a, d | `subject`, `body_text` | Add `to`, `cc`, `bcc` as editable `list` (035); `cc`/`bcc` secondary. |
| `google_ads_update_campaign_status` (`google_ads/tools/update_campaign_status.py:89`) | a (mandatory, `supports_auto=False`), d | `status` | Keep `campaign_ids` locked. An opaque, customer-scoped identifier is not a human-editable list; Plan 038 adds named, scoped campaign selectors and fixes multi-customer targeting. |
| `airtable_create_record` (`airtable/tools/create_record.py:83`) | a, d | declared but dropped by presenter | `table` editable (text), `fields` editable `keyvalue` (035). Presenter consumes server declaration (step 2). |
| `airtable_update_record` (`airtable/tools/update_record.py:89`) | a, d | same drift | Same; `record_id` locked. |

### Read tools — editable when policy-upgraded to approval

These never show a card by default, but any agent can be configured to
require approval on them (path b). Today that card renders their arguments
read-only, which makes the upgrade path pointless for steering. Declare the
primary steering argument editable; it costs nothing when the tool runs
auto. (This is also the prerequisite state for Plan 037's edit-and-re-run.)

| Tool | Editable target |
|---|---|
| `google_ads_run_report` (`run_report.py:66`) | `query` (already `multiline` — add `editable=True`, placeholder with a minimal GAQL example) |
| `bigquery_run_query` (`bigquery/tools/run_query.py:92`) | `query` (multiline) |
| `gmail_search_messages` (`search_messages.py:62`) | `query` (text), `limit` (number, secondary) |
| `gmail_read_message` (`read_message.py:62`) | `message_id` locked (no meaningful edit) |
| `search_knowledge` (`kb.py:75`) | `query` (text), `limit` (number, secondary) |
| `read_document` (`kb.py:164`) | `document_id` locked |
| `airtable_list_records` (`list_records.py:73`) | `table` (text), `filter_by_formula` (text, secondary), `view` (text, secondary), `max_records` (number, secondary) |
| `airtable_get_record` (`get_record.py:64`) | `table` (text); `record_id` locked |
| `google_ads_list_accounts`, `bigquery_list_tables`, `bigquery_get_table_schema`, `list_files`, `read_file`, `search_memory` | No editable fields (no meaningful steering argument, or auto-mounted and never carded); ensure arg_fields exist where arguments are user-relevant. |

## Steps

1. **Backend declarations** — apply the two tables above to each
   `ToolPresentation`. Patterns to follow: `web_search.py:139-154`
   (editable + placeholder + options), `send_message.py:111-122`. Every
   field left non-editable in an approval-capable tool must appear in the
   "locked by decision" list of this plan when you finish — no silent
   omissions. Enum options must mirror the domain literals
   (`services/memories/domain.py:30-32`, artifact types at
   `artifacts.py:26`) — add a test asserting options == the Literal values
   so they cannot drift.
2. **Presenters consume the server declaration** — the drift fix. In
   `apps/web/src`:
   - Delete the hardcoded field arrays: `SEND_FIELDS`
     (`gmail/presenters/send.tsx:13-19`), `CAMPAIGN_FIELDS`
     (`google_ads/presenters/campaign-status.tsx:19-38`),
     `CREATE_FIELDS`/`UPDATE_FIELDS`
     (`airtable/presenters/write.tsx:18-22`).
   - Custom approval-handling presenters get their `ApprovalField[]` from
     `useToolPresentations()` (the same source `tool-call-row.tsx:96-109`
     and `memory-tool-row.tsx:50-79` already use), keeping only layout
     around the shared `ApprovalRequestFields`. A presenter may still
     *add* read-only context (e.g. Airtable's `AirtableFieldGrid` preview)
     but never redefines editability.
   - Delegation: `delegation-tool-row.tsx` passes the declared
     `delegate_to_agent` fields instead of `[]`.
3. **Approval-card capacity check** — `save_memory` now declares 7 fields.
   Verify the card stays scannable: primary fields open, `secondary`
   fields behind the existing "+ Add" affordance, undeclared args still in
   "Other Options". Adjust `secondary` flags, not the card.
4. **Tests**:
   - API: extend the presentation snapshot/contract tests to cover every
     changed declaration; the options-mirror-Literal tests from step 1.
   - Web: per-presenter tests asserting fields come from the presentation
     provider (kill a hardcoded-array regression); an Airtable write
     approval test proving `fields` edits reach `override_args` as an
     object.

## Locked by decision (do not re-propose)

- `write_file.content` — staged/redacted; editing it means editing a blob
  the card deliberately does not display. Revisit only with a real staged
  content editor.
- `create_artifact.artifact_type` — type/content coherence.
- Identifier args (`memory_id`, `artifact_id`, `record_id`, `message_id`,
  `document_id`, `agent_id`, `file_id`) — editing an opaque id invites
  approving an action against an unseen target. Plan 038 replaces raw-ID
  surfaces with human-readable, server-resolved entity selectors.
- `google_ads_update_campaign_status.campaign_ids` — campaign IDs are opaque
  and customer-scoped, so a free-form list is neither usable nor safe. Plan 038
  introduces scoped campaign references and a name-based selector.
- `write_file.file_id` and `write_file.expected_current_revision_id` — target
  identity and optimistic-concurrency guard. `content_ref` is replay-only
  staged-storage plumbing and is intentionally omitted from the card.
- `web_search.model` — the optional model must remain compatible with the
  selected provider; the provider is the supported user-facing steering
  choice and omission selects its safe default.
- `save_memory.duplicate_of` and `save_memory.save_as_new` — near-duplicate
  resolution controls used only after the service returns an explicit
  duplicate result; they are not ordinary approval-time fields.
- `search_knowledge.filters` and `read_document.range` — structured filter and
  range objects do not fit the flat typed editors. They remain locked until a
  dedicated structured control exists.
- `read_file.mode`, `forget_memory.reason`, and
  `bigquery_get_table_schema.table` — transcript context only on tools that do
  not normally request approval; this sweep does not turn them into steering
  controls.

## STOP conditions

- If Plan 035 has not landed, stop — `number`/`keyvalue`/`list`/markdown
  editability will fail import-time validation.
- If any presenter needs editability the server doesn't declare, stop and
  add the server declaration instead of a client-side field.
- If making `kind` editable on `save_memory` lets a core-memory approval
  resume as `kind="note"` *without* re-checking anything it should, read
  `memory.py:116` first: replay runs with `tool_call_approved=True`, so a
  core→note downgrade is safe (strictly less privileged). If you find the
  reverse path (note→core without a card), stop and report — that would be
  an approval bypass.

## Verification

- `make check` at repo root (API contract tests + full web gate).
- Manual (`make dev`): (1) core `save_memory` — edit title, scope, type,
  importance on the card, approve, verify the memory row; (2) set a test
  agent's `google_ads_run_report` policy to approval, confirm the GAQL
  query is editable on the card; (3) Airtable create — edit a `fields`
  value in the keyvalue grid, approve, confirm the record payload.

## Completion notes

- Runtime declarations now expose all safe steering fields with their real
  types, enum options, and secondary placement. Opaque identifiers remain
  locked; campaign IDs were deliberately not made editable after maintainer
  review and are now covered by Plan 038's named, scoped selector design.
- Gmail, Google Ads, Airtable, and delegation presenters consume the
  server-owned declaration passed through the presenter contract. The shared
  undeclared-argument fallback moved into the generic tool-UI seam so provider
  packages do not depend on conversation-feature internals.
- API declaration tests pin editable and locked field sets, formats, secondary
  fields, the GAQL placeholder, and enum options against their Python Literal
  domains. Presenter tests pin declaration object identity, and Airtable tests
  prove key/value edits produce object-shaped `override_args`.
- Verification completed: API focused gate `44 passed, 10 skipped`; full API
  suite excluding the independently broken active-context selection test file
  `1369 passed`; full web `pnpm check` `445 passed` plus lint, Prettier, knip,
  dependency-cruiser, and production build.
- Repo-root `make check` was run. Ruff, formatting, migrations, and the Plan 036
  tests passed, but the API suite exposed six pre-existing failures in
  `tests/services/integrations/context/test_selection_ops.py`: commit
  `7093493d` added a membership check while that fixture still creates no
  membership. The file fails identically in isolation and is outside this
  plan's scope. Manual provider QA was unavailable because no safe configured
  Gmail/Google Ads/Airtable test accounts or browser session were present;
  mocked provider and approval-flow coverage passed instead.
