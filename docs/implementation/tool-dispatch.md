# Tool dispatch and approval contracts

Read this before changing tool registration, result contracts, entity
references, or approval fields. Preserve the
[governance boundaries](../architecture/governance.md). Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

## Startup assembly

Process startup composes built-in job handlers, internal entity resolvers,
core runtime tools, and enabled integration providers through the idempotent
`services/runtime_catalogs/assemble_runtime_catalogs.py` operation. Registry
modules define registration and lookup only; do not add contribution imports
to their module scope. The API lifespan, worker supervisor, standalone worker
entry points, maintenance commands, eval runner, and test bootstrap must
assemble before dispatching work so invalid providers fail before the process
serves or claims work. Assembly serialises callers, and a failed attempt makes
the process unusable so partially registered catalogues cannot be retried. The
provider-native and file-tool package initialisers are namespace-only;
assembly imports their concrete contribution modules so route and utility
imports cannot populate a partial catalogue.

## Results, references, and consent

The following contracts apply in this area:

- Tools that need richer transcript evidence than the model should receive may
  return `ToolReturn` with the bounded, output-model-validated payload in
  `return_value` and an explicitly safe `public_result` in metadata. The
  metadata is persisted and streamed to the application but is never sent to
  the model. Such tools must declare `max_public_result_chars`; dispatch makes
  the public value JSON-safe, redacts sensitive-key values, applies the same
  output model, and enforces that serialised budget. Keep provider-side fields
  bounded by the tool's product limits and exclude credentials or other
  application-only metadata at the source.
- Opaque tool targets use the runtime entity-reference contract. Internal
  resolvers stay under `services/agents/runtime/entity_references`; concrete
  provider reference models and resolvers stay in their provider package and
  publish only through the generic integrations seam. Scoped provider tools
  expose provider-owned scope/entity IDs only, resolve the provider scope to
  the canonical compatible active-context resource at execution, and target
  only that resource. Never serialise integration-resource or connection UUIDs
  in a scoped reference, bypass active-context resolution, or fan an entity ID
  out across compatible accounts.
- Approval overrides are governed by the server-owned field declarations:
  locked values cannot change, and entity values must be structured references
  that are reauthorised immediately before resume.
  A tool may add trusted display-only approval arguments from resolved runtime
  context; persist them as presentation metadata and keep the original tool
  arguments as the only replayable execution payload.
  Editable `records` fields also enforce their declared minimum row count and
  required columns before resume, even when the operator approves without edits.
  An omitted secondary records field stays optional; when present, it must meet
  the same declared constraints.
  A `code_eligible=True` write backed by a provider batch operation must expose
  that operation as one bounded list-shaped call with a faithful editable
  presentation. The complete reviewed row set is the consent boundary; do not
  replace it with sequential single-row calls or workflow-scoped grants.

## Transcript approvals

The following contracts apply in this area:

- Per-tool-call UI (approvals, live status, results) renders inline in the
  tool row within the transcript, not as separate blocks.
- Declined tool rows use the **Declined** badge, never **Failed**, and show the
  operator's reason when they provided one.
- Approval presenters may consume server-owned display arguments prefixed with
  `_`; generic fallback fields hide that presentation metadata, and approval
  replay uses the separate executable argument payload.

## Retained results and artifacts

The following contracts apply in this area:

- Complete transcript-only tool results may arrive through the persisted
  tool-return `public_result` metadata while the model-facing content remains
  bounded. Present the complete result rather than its model summary; use the
  shared `DataTable` client pagination for large bounded row sets so copy and
  CSV export still operate over all rows.
- Artifact create, list, read, and update results share the dedicated
  `ArtifactToolRow`. Discovery rows must preserve structured artifact
  references as links to the management surface; reads default to the shared
  typed rendered view with an adjacent raw-content tab, show only the bounded current
  version returned by the tool, and keep image reads metadata-only without
  signed URLs.

## Entity and record editors

The following contracts apply in this area:

- Opaque tool targets render through the shared entity field system in
  `src/components/tool-ui/`: hydrate labels from the conversation-scoped API,
  use the server-supplied canonical identity for provider-neutral comparison,
  and keep provider field names out of shared tool UI. Use the shared Base UI
  combobox for editable targets, preserve structured reference values, and fail
  closed as “Target unavailable” rather than exposing a raw ID.
- Editable record approvals use the server-declared `min_rows` and column
  `required` constraints. An omitted secondary records field stays optional.
  Keep editor feedback, approval gating, and decision merge on the shared
  record-validity helper, and give repeated controls row-specific accessible
  names.
