# Knowledge Base integration sources

Read this before changing integration imports, source refresh, or access-loss
cleanup. See [agent context architecture](../architecture/agent-context.md)
for the broader context model. Backend paths are relative to `apps/api/`.

## Import and refresh lifecycle

A provider-neutral Knowledge Base source contribution and the
Notion page adapter provide bounded search, preview, and canonical Markdown
fetch operations through `IntegrationKnowledgeSourceDefinition`. Loader
validation requires declared resource types. `ProviderRead` exposes
`knowledge_source_supported` and `knowledge_source_resource_types` without a
provider-name branch. Integration documents bind through nullable
`integration_resource_id`, retain provider identity in `external_id` and
`external_url`, and track access with `source_sync_status` and
`source_synced_at`. URL and integration documents are the refreshable source
types.

### Access and ingestion

The import service creates private documents by default,
and ingestion resolves the creator's personal grant on a dedicated runtime
session carrying workspace and user context. The workspace-owned job session
remains workspace-only, and provider calls run after the dedicated session
commits. Import and ingestion revalidate workspace and source access after
provider reads before they persist content. Definitive access loss clears
canonical content and chunks before completing without retry, so document
reads return no cached content after definitive loss. Search excludes every
refreshable source that is not `ready`.
### Management and reconciliation

`GET /kb/integration-sources/search`, `POST /kb/integration-sources/preview`,
and `POST /kb/documents/from-integration` are editor-gated provider-neutral
management routes. Manual refresh uses
`POST /kb/documents/{document_id}/reprocess`. An ownerless, bounded
`kb.reconcile_sources` maintenance job uses `services/kb/reconcile_sources.py`
and `services/kb/ensure_reconcile_job.py` to select due URL and integration
documents, then coalesces ordinary workspace-owned `kb.ingest_document` jobs
with manual refreshes. Keep both job shapes unchanged so the in-flight job
constraint continues to coalesce them.
Successful and failed refresh attempts advance the source synchronisation
timestamp so persistently unavailable sources cannot monopolise later scans.
`KB_SOURCE_REFRESH_INTERVAL_SECONDS` controls the scan interval, and
`KB_SOURCE_SCAN_BATCH_SIZE` bounds each pass. URL refreshes retain the guarded
public-address fetch path, send stored validators only on the first hop, and
map `401`, `403`, `404`, and `410` to definitive access loss.

## Import and refresh UI

The Knowledge Base import menu offers an integration provider only when the
provider catalogue declares `knowledge_source_supported` and the current user
has a usable personal connection. The provider-neutral flow selects one
available resource, searches pages or accepts a supported page URL, previews
the bounded source, and reviews the import before submission. New imports
default to **Private**; clearing that option must explain that everyone in
the workspace can search the page content. URL and integration documents
show their source synchronisation state and last-refreshed time in list and
detail views and use the existing reprocess mutation for **Refresh**. Keep
provider marks behind the integration registry and keep Knowledge Base
feature code independent of provider packages.
