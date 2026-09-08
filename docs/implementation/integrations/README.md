# Integration implementation guide

Read this for every integration change, then open the relevant provider
reference below. Read the
[packaging architecture](../../architecture/integration-packaging.md) before
adding providers or changing shared contracts. Backend paths are relative to
`apps/api/`; frontend paths to `apps/web/`.

## Provider references

Use these focused references for provider behaviour:

- [Google Ads](google-ads.md): keyword, campaign, and budget writes and presenters.
- [BigQuery](bigquery.md): discovery, schema cache, query bounds, and row scopes.
- [Google Analytics](google-analytics.md): property discovery and reporting.
- [Google Search Console](google-search-console.md): site routing and indexing writes.
- [Notion](notion.md): personal grants, bounded reads, and approved writes.
- [Microsoft Graph](microsoft-graph.md): Entra connections and resource discovery.

For Gmail and Airtable, follow the shared contracts here and the provider
packages under `apps/api/integrations/` and `apps/web/src/integrations/`.
For imported content, read [Knowledge Base sources](../knowledge-sources.md).

## Tools and operation runtime

The following contracts apply in this area:

- Provider packages keep each agent tool in its own module under a `tools/`
  tree. The tree may share schemas and provider-local helpers, while its
  `__init__.py` only composes exported definitions; do not accumulate a
  provider's catalogue in one `tools.py` module.
- Integration tools use the provider-neutral operation runtime under
  `services/integrations/`: context fan-out/targeting share one authorisation
  and failure-isolation loop, `run_audited_integration_operation` derives
  external-write durability from the registered `RuntimeToolDefinition`, and
  `serialize_fan_out_results` owns the safe provider-key/scope outer envelope
  and never publishes internal resource or connection UUIDs.
  `split_fan_out_tool_return` in `context/results.py` owns the model/transcript
  projection using the fixed `model_result` and `display_result` keys. Tools
  import it directly when they retain a richer transcript result. Providers
  return one `IntegrationAuditOutcome`, supply bounded pending detail for
  external writes, and subclass the shared result models only to narrow data.
  Every fixed integration tool declares an operation-specific output model;
  dynamic objects are limited to report/query rows and provider-defined record
  field values.
  Pending integration-operation evidence contains requested intent only;
  successful writes must return the one canonical terminal detail with exactly
  aligned intent outcomes and concrete provider effects. Terminal operation
  rows also record execution latency and, when the shared retrying HTTP seam
  dispatched requests, the logical request and per-request attempt counts. Intent and effect
  counts are validated independently. There is no schema-version compatibility
  layer. The runtime rejects caller-supplied tool names or context bindings
  that do not match the actually dispatched definition, and outcomes must be
  terminal. An unverified terminal outcome is persisted before the outer
  fan-out reports `unverified_mutation`. When a tool supplies bounded,
  output-model-compatible per-item ambiguity evidence through
  `unverified_result`, the error entry retains that data without changing its
  unverified status.
  Provider reads needed to build pending evidence belong in the runner's
  preparation callback so their latency, retries, and failures remain part of
  the same audited operation. The pending row is written after preparation and
  immediately before the external mutation.
  Do not add provider-local audit runners, durability booleans, denial
  callbacks, fan-out serialisers, or copied outer result fields. A genuine
  one-request/many-context topology may retain a narrowly named adapter that
  delegates persistence to the shared runner.

## Transport safety and entity resolvers

The following contracts apply in this area:

- Every integration HTTP request declares its semantic transport policy as
  `read`, `idempotent_write`, or `mutation`; HTTP method and operation names
  never imply retry safety. Reads retain bounded retries. A mutation is never
  retried after an ambiguous attempt; only a received provider rejection, such
  as a 401 followed by credential refresh, can authorise a fresh attempt.
  Transport failures expose `not_dispatched`, `rejected`, or `ambiguous`
  disposition to the shared audit runner. Unknown mutation failures and
  in-flight cancellation are ambiguous, close correlated evidence as
  `unverified_mutation`, and must not be replayed automatically.
- Provider packages keep each entity resolver in its own module under an
  `entity_resolvers/` tree, with one module per entity kind. The package
  `__init__.py` only composes exported resolver definitions so provider
  manifests stay concise as their catalogues grow.

## Connection credentials

OAuth packages declare wire behaviour and identity sources through
`OAuthProtocol`. The shared flow keeps state validation and bounded non-secret
connection metadata provider-neutral.

- Non-OAuth integration credentials remain secret references. Admins replace
  API keys and service-account keys in place through
  `PUT /integrations/connections/{connection_id}/credential`; discovery
  validates the new version asynchronously. The local-only encrypted secret
  store uses `LOCAL_SECRET_STORE_PATH`, anchored to the API root and separate
  from `LOCAL_STORAGE_ROOT`. Application-managed secrets and externally
  provisioned references use the `workspaces/{workspace_id}/` namespace;
  unnamespaced legacy references may only be reused by the workspace of an
  existing connection. Production runtime identities must be able to create
  application-managed secret resources and manage their versions while
  remaining scoped to the provider's physical Praxis secret namespace.
- Integration recovery actions derive from the connection credential's
  `auth_mode`, never from the provider's supported-mode list. OAuth may offer
  sign-in/refresh; API-key and service-account connections offer obscured,
  in-place credential replacement only when the persisted status requests it.

## Frontend package layout

Integration provider UI lives in `src/integrations/<provider>/` with
`index.ts` (the `IntegrationUiModule` default export and the only file the
registry imports), `presenters/` (tool row presenters), `components/`
(provider-specific visual components, including the logo), `lib/`
(non-visual helpers such as arg parsing and detail builders), and `api/`
(TanStack Query operations, one per file) when the provider calls the API.
Follow this layout for new providers.

## Shared write presenters

Google Ads and Search Console write presenters configure
`src/integrations/write-presenter.tsx`. This shared seam owns approval merging,
validation precedence, provenance, lifecycle states, and fan-out rendering.
Provider adapters own branding, copy, parsers, summaries, and outcome views.
Detailed unverified evidence requires the explicit `renderUnverifiedOutcome`
callback; Search Console supplies it, while Google Ads keeps its failure view.
Do not copy the state machine into provider packages.
Edited budget assignments refresh campaign and source-budget evidence through
the conversation-scoped entity lookup. The shared approval refresh query keeps
approval unavailable until the selected routes are verified, isolates stale
responses by selection, and preserves completed decisions. Provider refresh
functions own entity validation; refreshed display metadata stays out of edits.
