# Plan 038: Human-readable tool entity references and selectors

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Status**: TODO
- **Written**: 2026-07-31 against the in-flight Plan 036 working tree.
- **Corrected**: 2026-07-31 after a full code-verification pass. The step 1
  baseline inventory, the server-side editability enforcement step, and the
  file references below come from that audit.
- **Priority**: P1 — opaque identifiers are not a usable or trustworthy
  approval interface.
- **Effort**: XL — shared presentation and resolver contracts, provider
  lookups, scoped target migrations, and approval UI.
- **Risk**: HIGH — selectors choose the exact objects an agent can read or
  mutate. Workspace boundaries, active integration context, provider scopes,
  stale references, and multi-account targeting must be enforced server-side.
- **Depends on**: 035 (typed field editors), 036 (server-owned declarations
  and presenter drift removal). Do not run concurrently with 037 — both
  extend the shared field editors and the governed execution surfaces.

## Goal

Operators work with names and context: “Spring Brand Campaign,” “Invoice from
Acme,” “Customer follow-ups,” or “Quarterly plan.” They do not know campaign,
message, record, memory, artifact, document, file, or agent IDs. A locked ID is
safer than a free-text ID editor, but it is still a poor approval surface: the
operator cannot tell what they are approving and cannot choose another target.

After this plan, a tool field that identifies a product or provider entity is
declared as a first-class entity reference. The UI shows a human-readable
label and supporting context, and editable references use a searchable,
paginated selector. Stable IDs remain in the execution and audit payloads, but
are never the primary user-facing value and are never typed by the operator.
The server resolves and revalidates every selection in the current workspace,
conversation, and active integration context immediately before execution.

Google Ads campaigns and Gmail messages are the proof cases. The implementation
must establish a reusable contract and then sweep all identifier arguments; it
must not solve those two providers with presenter-local lookup code.

## Product decisions

1. **Labels for people, IDs for machines.** The selector and approval summary
   render a label, optional description, and scope label. Raw IDs may appear in
   a deliberately opened technical-details view for support, but never as the
   field label, editable text, or only description.
2. **The API is authoritative.** Client-supplied labels are display hints only.
   Authorization and execution use server-resolved identifiers. Approval or
   direct re-run re-resolves the reference; deleted, inaccessible, stale, or
   mismatched targets block execution with a specific error.
3. **References are scoped.** External IDs are not globally unique. A provider
   reference identifies both the active integration resource (for example a
   mailbox, Ads customer, or Airtable base) and the provider entity. The UI
   shows that scope when more than one compatible resource is active.
4. **No silent fan-out of an entity ID.** A Gmail message from one mailbox, an
   Airtable record from one base, or a Google Ads campaign from one customer is
   executed only against its referenced scope. Existing tools that apply one
   unscoped ID to every active-context entry must migrate before declaring that
   field selector-backed.
5. **No provider calls from presentation code.** Provider and internal entity
   lookup lives behind one authenticated API and provider-owned resolver
   definitions. React presenters consume the shared field system only.
6. **Declarations are enforced, server-side.** The server's editability
   declarations are the contract: a field declared non-editable cannot be
   overridden at resume/re-run time, and an entity field changes only via a
   validated reference — not merely hidden or shaped by the client. Retargeting
   is a feature, not a bug: after this plan the operator *can* change which
   record, campaign, or message a call targets (the agent may have picked the
   wrong one), by selecting from labeled choices — never by supplying an ID.
7. **Scope is never a user edit.** Account, mailbox, and base identity come
   from the active context, are not tool parameters, and are never
   independently editable. Selecting an entity carries its scope along, and
   that scope must resolve to a compatible active-context entry — choosing a
   different entity is the only way scope ever changes.

## Current problems (verified 2026-07-31)

- `google_ads_update_campaign_status` accepts `campaign_ids: list[str]` and
  applies the same list to every compatible active-context customer —
  `run_context_fan_out` (`services/integrations/context/fan_out.py`) iterates
  all compatible entries and the tool passes the one list per entry
  (`integrations/google_ads/tools/update_campaign_status.py:49-86`). Plan 036
  correctly leaves it locked pending this plan; a free-form list editor cannot
  identify campaign names or account scope.
- `gmail_read_message` accepts one `message_id` and fans it out to every active
  mailbox even though Gmail message IDs are mailbox-scoped
  (`integrations/gmail/tools/read_message.py:32-59`); an ID valid in one
  mailbox produces error entries for every other. `gmail_search_messages`
  returns subject, sender, date, snippet, and message ID per message, but
  mailbox identity exists only on the surrounding fan-out envelope
  (`GmailFanOutEntry`, `integrations/gmail/tools/schemas.py`), not on the
  message — and none of it is represented as a reusable reference.
- `airtable_update_record` combines editable table text with a locked
  `record_id` and broadcasts the pair to every writable base in context (the
  base is always the context entry's `external_id`; the tool description
  literally says "in every writable Airtable base"). Record identity is base-
  and table-scoped.
- Core identifier fields (`memory_id`, `artifact_id`, `document_id`, `file_id`,
  `agent_id`, `write_file.file_id`) are declared as locked text; transcripts
  show raw UUIDs under friendly labels. Workspace-scoped list/get services
  exist for all five entity types, but only the files list supports text
  search (`services/files/list_files.py:52-57`) and no service offers batch
  ID hydration — resolvers need both.
- `ToolFieldPresentation` supports ten scalar/structured formats plus a static
  `options` tuple (`services/agents/runtime/tools/contract.py:104-114`).
  Nothing marks a field as an entity reference, declares cardinality or
  dependent fields, or names a resolver.
- Import-time validation forbids scope-bearing parameters on integration tools
  (`_INTEGRATION_PARAMETER_DENYLIST`, `contract.py:48-60` — `customer_id`,
  `base_id`, `mailbox`, `connection_id`, `resource_id`, …). Scoped references
  must carry scope inside a structured, server-validated reference type and
  evolve this rule deliberately; removing the denylist is not acceptable.
- **Editability declarations are a client-side hint only.** The approval
  resume path hands `override_args` to pydantic-ai unchecked beyond
  input-schema validation (`services/agent_runs/resume_run_stream.py:196-201`);
  nothing in app code enforces the server's own declarations. Today that means
  a crafted request can rewrite a field the UI presents as locked. After this
  plan the same gap would be worse: entity fields are *meant* to be
  retargetable, but only through validated references resolved in the active
  context — without enforcement, a raw-ID override would bypass the entire
  reference layer. Step 2 closes this first.

## Reference contract

Add an explicit contract rather than overloading `text` or `list`:

- Extend the Python-owned presentation schema with `entity` and `entity_list`
  field formats and an `entity_kind` token. Add optional `depends_on` field
  keys for scoped lookups such as an Airtable record depending on `table`.
  Import-time validation requires an entity kind for entity formats, forbids
  it for other formats, and verifies dependencies name arguments in the tool's
  input schema.
- Serialize the new metadata through `GET /tools/presentations` and update the
  generated/manual web contract types. `entity` accepts one reference;
  `entity_list` accepts a bounded list. Neither has a free-text fallback.
- Use a shared wire shape for resolved choices:
  `{value, label, description?, scope_label?, icon?}`. `value` is opaque to the
  UI and may be a structured reference, not only a string. Do not make the
  browser concatenate or parse provider IDs. For provider entities, `value`
  embeds scope as the active-context resource UUID (`integration_resource_id`
  — the same identifier persisted by context selections, context groups, and
  integration audit events) plus the provider entity ID; the server re-derives
  `connection_id` and `external_id` from it. Internal entities use the row
  UUID.
- Add a provider/internal resolver registry parallel to the integration plugin
  contract. Provider resolvers ride `IntegrationProviderPlugin` next to
  `preview_definitions` and are validated in `loader._validate_plugin`;
  internal resolvers register beside the runtime tool catalog. Each resolver
  declares its entity kind, search/resolve functions, maximum page size, and
  whether it requires active integration context. Duplicate entity kinds and
  undeclared provider resolvers fail at startup. Name the concept distinctly
  from the existing per-call `effect_scope_resolver` hook on
  `RuntimeToolDefinition`.

## Steps

1. **Inventory and migration map.** Re-verify the baseline below against the
   execution-time tree, then extend it with anything new. Classify every field
   whose value is an opaque identifier or list of identifiers — including
   fields currently omitted from presentations — as internal, provider-scoped,
   compound/dependent, or genuinely technical. No identifier field is silently
   left as ordinary editable text/list.

   Baseline (verified 2026-07-31):

   | Field | Today | Class | Target |
   |---|---|---|---|
   | `update_memory.memory_id` (`tools/memory.py:279`) | locked text | internal | editable `entity` selector (memory) |
   | `forget_memory.memory_id` (`tools/memory.py:365`) | locked text | internal | `entity` (memory) — display hydration only; tool is never carded |
   | `save_memory.duplicate_of` / `save_as_new` | undeclared | internal duplicate-resolution control | stays technical (036 locked decision) |
   | `update_artifact.artifact_id` (`tools/artifacts.py:112`) | locked text | internal | editable `entity` selector (artifact) |
   | `read_document.document_id` (`tools/kb.py:193`) | locked text | internal | editable `entity` selector (knowledge document) |
   | `search_knowledge.filters.document_ids` (`tools/kb.py:32,116`) | undeclared, nested | internal | stays locked with the structured `filters` object (036 decision) |
   | `read_file.file_id` (`tools/files/read_file.py:51`) | locked text | internal | editable `entity` selector (file) |
   | `write_file.file_id` (`tools/files/write_file.py:76`) | locked text | internal | editable `entity` selector (file), secondary |
   | `write_file.expected_current_revision_id` (`write_file.py:77-80`) | locked text | technical | stays hidden — optimistic-concurrency token |
   | `write_file.content_ref` (`staged_tool_content.py`) | undeclared, redacted | technical | stays hidden — staged-storage plumbing |
   | `delegate_to_agent.agent_id` (`delegation/build_delegation_tools.py:66`) | locked text | internal | editable `entity` selector (agent), restricted to the caller's allowed delegates |
   | `gmail_read_message.message_id` (`gmail/tools/read_message.py:79`) | locked text | provider, mailbox-scoped | editable `entity` selector (Gmail message); mailbox scope rides the reference |
   | `airtable_get_record.record_id` (`get_record.py:82`) | locked text | provider, base+table-scoped | editable `entity` selector (record), depends on `table` |
   | `airtable_update_record.record_id` (`update_record.py:112`) | locked text | provider, base+table-scoped | editable `entity` selector (record), depends on `table` |
   | `airtable_*.table`, `airtable_list_records.view` | editable text | provider names-or-IDs operators already know | stays text in this plan; may gain a selector separately |
   | `google_ads_update_campaign_status.campaign_ids` (`update_campaign_status.py:113-117`) | locked list | provider, customer-scoped | editable `entity_list` selector (campaigns); customer scope rides each reference |
   | `bigquery_get_table_schema.table` (`get_table_schema.py:137`) | locked text | human-meaningful table name; ambiguity across datasets already raises a retry | stays text — record as genuinely non-opaque |

2. **Server-side enforcement of declarations.** Before any selector work,
   make the server enforce its own contract at the approval-resume boundary
   (and any future governed re-run path): reject `override_args` whose values
   differ from the recorded original args on any field not declared
   `editable`, with a specific error. Once entity formats land, extend the
   rule rather than relaxing it: entity fields accept overrides only as
   structured references that re-resolve to an accessible entity in a
   compatible active-context scope — a raw-ID override of an entity field is
   refused. Enforce in app code — do not rely on pydantic-ai's schema
   validation, which checks shape, not authorization. Add tests proving a
   non-editable-field override is refused, an editable-field override still
   works, and (later) an entity retarget succeeds via reference and fails via
   raw ID. This step stands alone and makes decision 6 true even if later
   steps slip.
3. **Backend reference resolution API.** Add a workspace/conversation-scoped
   endpoint for exact-value hydration and debounced search. Follow the
   existing conversation-scoped read precedent
   (`GET /integrations/conversations/{conversation_id}/context`, declared with
   `require_read`) and the validated `kind` + `ref` parameter pattern of
   `routes/integrations/get_preview.py`; add a per-route
   `require_rate_limit(custom_limit=…)`. The request carries `tool_name`,
   `field_key`, current dependent args, search text or exact opaque values,
   and a bounded cursor/page size. The server must:
   - require active workspace membership and access to the conversation;
   - rebuild the agent's mounted/available tool set and verify the declared
     field/entity kind rather than trusting client metadata — note
     `list_tool_presentations` is not permission-filtered, so it is not a
     template for this check;
   - resolve active context server-side and expose only compatible resources;
     honor delegation visibility (`allowed_agent_ids`) for the agent resolver;
   - bound search, provider calls (through the `request_with_retries`
     timeout/retry seam), response size, and timeouts; rate-limit the
     endpoint consistently with other provider reads;
   - return no secrets or provider payloads beyond the option contract; and
   - audit external resolver failures without turning routine typeahead reads
     into noisy security events.
4. **Shared selector UI.** Extend `ApprovalRequestFields` and the shared tool
   field renderer with a searchable combobox (multi-select for `entity_list`).
   No combobox exists in the codebase today; vendor the Base UI Combobox
   (`@base-ui/react` ≥ 1.6 ships it) into `components/ui` following the
   existing Select/Popover wrapper pattern. Promote the file-local
   `useDebouncedValue` from `knowledge-search-panel.tsx` into a shared hook,
   and use TanStack Query with the workspace-scoped query-key convention for
   debounced, cancellable, paginated lookup and exact-value hydration. Render
   label, description, and scope; preserve selection while pages change;
   support keyboard and screen-reader operation; show
   loading/empty/error/stale states. A reference that cannot be resolved
   renders “Target unavailable” and disables approval/run — it never falls
   back to displaying the raw ID. Secondary reference fields continue to use
   the existing “+ Add” affordance.
5. **Internal resolvers.** Implement workspace-filtered resolvers for agents,
   memories, artifacts, knowledge documents, and files using existing services
   and permission rules. Extend those services with name search (only files
   has it today) and batch ID hydration rather than fetching pages client-side.
   Reuse the per-entity visibility rules — `visible_memory_filter` for
   memories, private-document filtering for KB, `allowed_agent_ids` for
   delegate agents — never a raw workspace query. Labels use the entity's
   current title/name; descriptions disambiguate with type, owner/scope, or
   recency where useful. Deleted or inaccessible rows never hydrate as valid
   choices. Migrate `agent_id`, `memory_id`, `artifact_id`, `document_id`, and
   `file_id` declarations to the new formats without changing runtime argument
   names.
6. **Google Ads proof case — scoped campaign targets.** Add a provider resolver
   that queries campaign ID, name, status, and customer scope with bounded GAQL.
   Replace the unscoped `campaign_ids` input with a typed list of scoped campaign
   references (or an equivalently validated server-owned reference token), with
   scope carried as `integration_resource_id`. Thread the reference type past
   `_INTEGRATION_PARAMETER_DENYLIST` as a registered structured model — a
   narrow, typed exemption, not a relaxed rule. Add a targeted execution mode
   beside `run_context_fan_out` that groups targets by referenced context entry,
   verifies each is still in `compatible_entries`, mutates only those
   customers, and fails closed when a referenced resource is no longer
   compatible; it must not apply every ID to every customer. Re-resolve ID,
   name, customer, access, and current status before the approval resumes. The
   card shows campaign names and account labels, with status remaining the
   separate editable enum. Preserve stable IDs in provider/audit payloads and
   provide an explicit compatibility error for old pending calls rather than
   guessing scope.
7. **Gmail proof case — message references.** Make Gmail search output a typed
   message reference containing mailbox scope plus message ID and display
   metadata (subject, sender, date) — today mailbox identity exists only on
   the fan-out envelope, so this moves it onto each message. Migrate
   `gmail_read_message` to consume the scoped reference and execute only
   against that mailbox via the targeted execution mode from step 6. Its field
   hydrates and searches by Gmail query through the generic resolver; the
   selector shows subject as label and sender/date/mailbox as context. Missing
   subject uses a human fallback such as “(no subject),” never the message ID.
8. **Provider sweep.** Add scoped resolvers and typed references for Airtable
   records (dependent on table and base) and any provider IDs found in step 1.
   For `airtable_update_record`, selecting a record must establish its base and
   table; changing the table clears an incompatible record selection. Provider
   writes target only the selected scopes. Table/schema names that are already
   meaningful to operators may remain text or gain selectors separately; do
   not misclassify human names as opaque IDs.
9. **Approval, replay, and history semantics.** Effective args submitted by an
   approval or future “Edit & Run Again” action contain the exact structured
   references selected by the user. Validate them against the tool's Pydantic
   schema and the step 2 editability rule, then re-resolve at dispatch.
   Persist original/effective references and resolved labels so historical
   transcript rows remain intelligible even if an entity is later renamed or
   deleted. Transcript `parts` are strictly re-validated as pydantic-ai
   messages on read-back (`persistence.py`), so labels persist in the
   per-tool-call metadata sidecar (the `metadata_json["approval_results"]` /
   `display_args` seam), never inside `parts`. Audit records retain stable IDs
   and scopes. Redact only under existing sensitive-data rules.
10. **Tests and compatibility.** Add contract validation and route permission
    tests; step 2 editability-enforcement tests; denylist-exemption tests
    (a reference type passes, a bare `customer_id` parameter still fails at
    import); targeted-execution tests; resolver pagination/bounds tests;
    cross-workspace and cross-context rejection tests; stale/deleted reference
    tests; multi-account Google Ads and multi-mailbox Gmail tests proving no
    cross-scope fan-out; UI hydration, search, keyboard, multi-select,
    loading/error, and unresolved-reference tests. Update presentation
    snapshots. Old completed history with raw IDs may use server hydration for
    display; old pending approvals with ambiguous unscoped external IDs must
    be blocked and regenerated, never auto-approved.

## Out of scope

- Replacing stable IDs in database, provider, persisted tool-call, or audit
  records. This is a human-interface and validated-reference layer.
- A generic picker for arbitrary free-text fields such as GAQL, SQL, Gmail
  search syntax, email addresses, Airtable formulas, or memory content.
- Client-side provider SDKs, client-held integration credentials, or fetching
  an entire provider dataset up front.
- Fuzzy model-based entity matching at execution time. Search may be fuzzy,
  but the user selects an exact server-resolved reference.

## STOP conditions

- If a resolver can return an entity outside the current workspace,
  conversation access, active integration context, or provider scope, stop.
- If a provider-scoped ID would still be fanned out to multiple context entries
  after migration, stop; the reference shape or runtime routing is incomplete.
- If approval can proceed when exact-value hydration fails or the target has
  become inaccessible, stop; stale references must fail closed.
- If the UI must parse IDs, infer scope, or trust labels to build executable
  args, stop and move that logic behind the API contract.
- If old ambiguous pending calls cannot be distinguished from new scoped
  references, stop and add an explicit schema/version discriminator; do not
  infer a target.
- If step 2's enforcement breaks an existing flow that legitimately overrides
  a non-editable field, stop and report it — that flow is depending on the
  vulnerability, and the fix is a server declaration change, not a carve-out.
- If threading scoped references requires broadly relaxing
  `_INTEGRATION_PARAMETER_DENYLIST` rather than a narrow exemption for
  registered reference types, stop; the denylist is a security boundary.

## Verification

- `make check` at repo root.
- Manual (`make dev`), light and dark themes:
  1. With two Google Ads customers active, search by campaign name, select one
     campaign from each account, verify both account labels on the card, approve,
     and confirm each mutation reaches only its selected customer.
  2. With two Gmail mailboxes active, select a message by subject/sender, open
     or approve the read, and confirm only the selected mailbox is called.
  3. Select an internal memory/artifact/file by name; rename or delete it in a
     second tab before approval and confirm refresh or a fail-closed stale state.
  4. Submit a resume decision that overrides a locked field via the API
     directly and confirm a specific rejection (step 2).
  5. Exercise keyboard-only search, selection, removal, loading, empty, provider
     error, pagination, and unresolved historical reference states.
  6. Inspect persisted tool calls and audit events: stable IDs/scopes are
     retained, human labels render in the transcript, and no credential or
     provider payload leaks through the resolver response.

## Completion standard

The plan is complete only when every identifier found in step 1 is either an
entity/entity-list field backed by an authorized resolver or explicitly listed
here with a durable reason it is genuinely technical and should remain hidden
from operators; when editability declarations are enforced server-side and
entity retargeting works only through validated references (step 2); and when
Google Ads and Gmail pass the multi-context proof cases. Shipping only a nicer
read-only label or disabling ID editing does not satisfy this plan.
