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
- Presentation argument fields must name top-level input arguments; registration
  rejects any other key. A tool whose only parameter is a reference model must
  annotate it with a `Field` description, because Pydantic AI otherwise unwraps
  that parameter and the model sends its fields without the wrapper key that
  approvals and presenters read.
- Approval overrides are governed by the server-owned field declarations:
  locked values cannot change, and entity values must be structured references
  that are reauthorised immediately before resume.
  A tool may add trusted display-only approval arguments from resolved runtime
  context; persist them as presentation metadata and keep the original tool
  arguments as the only replayable execution payload.
  Editable `datetime` fields accept local date-time strings in
  `YYYY-MM-DDTHH:MM` or `YYYY-MM-DDTHH:MM:SS` form, without an offset or zone.
  Editable `boolean` fields accept JSON booleans only. Validate effective values
  before direct or nested resume, including approvals without edits. Secondary
  scalar fields may be absent or null; primary fields require a valid value.
  Edits to declared string fields preserve the reviewed value exactly,
  including whitespace and empty HTML bodies. Tool input validation owns
  required-value rules.
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
  replay uses the separate executable argument payload. Decision merging rejects
  edits to these reserved display keys, including stale or injected edits.

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
- A failed approval submit keeps the error on the card and offers Decline
  beside Try Again. Decline reopens the request, so the operator can decline
  it or go back, correct the fields, and approve again.
- Editable record approvals use the server-declared `min_rows` and column
  `required` constraints. An omitted secondary records field stays optional.
  Keep editor feedback, approval gating, and decision merge on the shared
  record-validity helper, and give repeated controls row-specific accessible
  names.

The `services.integrations.approved_display_args` helper returns retained
server-side display evidence only for the approved run and matching tool call.
It resolves direct and Code Mode approvals and never accepts replay arguments
as evidence. Outlook send-draft uses this to check that the reviewed draft
still matches the provider before sending.

## Scalar approval editors

Editable string fields with declared options remain selectable when their
argument is absent or null. Rendering the picker preserves that original
value until an option is selected. Fields can declare `options_by_field`
and `options_by_value` to restrict choices using another argument. The
frontend filters these choices against the effective approval arguments,
replaces an incompatible selection when the controlling argument changes,
and blocks approval while a supplied value remains incompatible.

Editable date-time fields use the shared input with `type="datetime-local"`
and `step={60}`. Preserve the raw value, including supplied seconds, and remove
an edit when the input is cleared. Boolean fields use the shared labelled
checkbox in a horizontal field and submit the boolean itself. Unchanged
booleans produce no override. An absent or null editable secondary boolean
shows a No change, Yes, or No selector. Rendering or opening the selector does
not add an edit. Selecting Yes or No submits a boolean; selecting No change
removes that edit and preserves the original omission or null value. Primary
boolean fields still require a boolean value.
Both formats use compact grid cells. Decided cards display local date-time
components verbatim, including supplied seconds, independently of the browser
time zone. Timestamps with an offset or `Z` retain instant-style formatting.
Tools that need a time zone declare a separate text field. Date-only fields and
a time-zone picker remain follow-ups for a tool that needs them.

## Approval proposal identity

Stream events and approval reloads use one bounded graph projection. Each
approval identifies its owning run, root run, and suspension batch separately
from the native tool-call ID. Identical native IDs in sibling runs remain
separate decisions. Display fields never replace executable arguments.
The pending approvals list names the actual direct or nested actions,
including actions prepared by specialists.

Approval decisions compile against each leaf's owning context. The direct
path validates canonical effective arguments. The nested workflow path binds
the nested call and effective-argument digest to Code Mode decision metadata;
approving the outer workflow only carries that one nested decision. Delegation
carries the child's compiled `DeferredToolResults` in the existing parent-call
metadata. It grants no permission for later nested writes.
