# Knowledge Base integration sources

Read this before changing integration imports, source refresh, or access-loss
cleanup. See [agent context architecture](../architecture/agent-context.md)
for the broader context model. Backend paths are relative to `apps/api/`.

## Platform authoring and ingestion

Super admins manage deployment-owned Knowledge through the explicit platform
management API. Manual entries and uploads pinned to a platform File revision
start unpublished. Platform sources cannot use workspace Files, private
entries, conversations, URLs, or integration credentials. The server supplies
provenance and applies the shared content limits, secret checks, and chunking.
Exact-content deduplication includes ownership scope and never compares a
platform entry with tenant-private content.

All routes require an authenticated active workspace membership and configured
super-admin authority. A super admin with read-only workspace membership can
manage platform entries. The routes are:

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/kb/platform/documents/` | Unpublished manual entry |
| `POST` | `/kb/platform/documents/from-file` | Unpublished entry pinned by `file_id` and `file_revision_id` |
| `GET` | `/kb/platform/documents/` | Bounded management list, including drafts |
| `GET` | `/kb/platform/documents/{document_id}` | Authenticated content and processing state |
| `PATCH` | `/kb/platform/documents/{document_id}` | Withdrawn entry updated and queued for processing |
| `POST` | `/kb/platform/documents/{document_id}/reprocess` | Fresh ingestion of a withdrawn entry |
| `POST` | `/kb/platform/documents/{document_id}/publish` | Reviewed entry published after an ingestion-version check |
| `POST` | `/kb/platform/documents/{document_id}/withdraw` | Publication withdrawn and earlier work invalidated |
| `DELETE` | `/kb/platform/documents/{document_id}` | Unpublished tombstone |

Publication supplies `expected_ingestion_version` from the reviewed response's
`meta.ingestion_version`. It requires a completed ingestion attempt, canonical
content matching its hash, and the complete stored chunk count. Lifecycle
mutations and their strict global audit events commit together. Tenant audit
queries cannot read these events.

Before editing or reprocessing a published entry, withdraw it. Processing and
failure keep it withdrawn. Successful ingestion prepares canonical content and
chunks for review; only an explicit super-admin publication makes it visible
under the platform database policy. Published entries join workspace retrieval
through the existing API and agent tools. Platform authoring controls, badges,
and copy actions in the Knowledge web interface remain pending.

Platform ingestion and embedding use separate actor-owned jobs. Each job
requires an active super admin and carries the expected ingestion version.
Provider work runs outside the document write transaction. Before saving its
result, the job locks and rechecks the document's version, deletion, and
publication state. Edits, withdrawal, and deletion invalidate earlier work.
Retries replace chunks atomically and fill only missing embeddings. Annotation
uses the existing bounded untrusted-content helper without agent tools.
Embedding writes recheck collection metadata under a short transaction lock
so concurrent jobs cannot save vectors from incompatible models.
If the initiating admin loses access during processing, another super admin can
withdraw the entry to cancel that attempt, then reprocess it under their own
authority.

Platform annotation and indexing use the platform admission budget and durable
usage ledger. Query embeddings remain workspace costs. Missing embeddings keep
the existing lexical fallback contract; they do not indicate successful semantic
indexing. `meta.embedding_status` distinguishes `pending`, `ready`, and `error`,
with a bounded `meta.embedding_error` when indexing fails. Publication stops
remaining embedding work for that entry. To retry after publication, withdraw
and reprocess it. See [AI usage accounting](ai-usage.md) for admission and
failure semantics.

A live platform document retains its pinned File revision, including while the
document is a draft or withdrawn. File retention skips pinned parents. Creating
an upload entry locks the live File until the document transaction commits.

## Published Knowledge reads

Search combines workspace documents and published platform documents in one
ranking. Both lexical and semantic candidate queries apply ownership, privacy,
source access, source-type filters, and document-ID filters before their limits.
The final result limit and optional reranker apply to that shared candidate set.
`private_only` returns only private documents created by the requesting user in
the active workspace. Query embeddings are charged once to that workspace.
Missing or failed query embeddings retain lexical fallback.

Search hits, agent results, and Knowledge references include `scope`. Duplicate
titles remain distinct document IDs. Publication grants access to reference
material, not instruction authority. Platform snippets and document content use
structured untrusted-content nodes, with framing applied to model history.
Agents fetch only bounded search results and requested document windows.

The document list accepts an optional `scope=workspace|platform` filter. Counts
and pages use the same ownership and privacy predicate. Draft, withdrawn, and
deleted platform entries are absent from ordinary search, detail, lists, and
entity pickers. Resolution rechecks publication, including saved references.
Workspace mutations remain local, including for super admins. Explicit platform
management routes retain separate authority to inspect drafts.

Local URL and integration metadata remain available for processing and recovery.
When source access is not ready, detail reads omit canonical content and summary,
and search and pickers omit the source. This does not grant access to another
user's private entry or another workspace's metadata.

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
