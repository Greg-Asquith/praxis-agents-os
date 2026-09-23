# Google Search Console implementation

Read this when changing Google Search Console connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

Start with the [backend package](../../../apps/api/integrations/google_search_console/)
and [frontend module](../../../apps/web/src/integrations/google_search_console/index.ts).

## Backend contracts

Google Search Console contributes workspace OAuth through its own isolated
Google Cloud client. It requests the full `webmasters` scope so later sitemap
actions use the same connection. Discovery
canonicalises each verified property's scheme and host while retaining its
path in the external ID, and maps
Search Console permission levels to read-only or writable resources. The
provider package contributes code-eligible reads for Search Analytics
rows, up to 200 submitted sitemaps per selected site, and indexed-status
inspection for up to ten requested URLs. Inspection routes each URL to the
longest matching selected URL-prefix property before falling back to a
matching domain property, then executes sequentially per site against the
provider's 2,000-inspection daily property quota. Query and page values,
sitemap paths, canonicals, referring URLs, and provider error text retain
untrusted-content provenance, while audit evidence contains parameters and
counts rather than provider content. Its code-eligible sitemap write routes
up to 20 URLs to selected writable properties, defaults to approval while
supporting scheduled automatic execution, and uses one non-retried mutation
per sitemap. The tool reads existing state during preparation, records the
complete pending intent immediately before mutation, and reads each sitemap
back for terminal status evidence. An ambiguous submission remains
unverified and is not replayed automatically.

The discovery callback accepts the credential value, principal label, and
connection pacing key in the shared runner's positional order. The Search
Console HTTP client uses the credential value to authenticate site discovery.

Search Analytics declares its public budget from the configured
structured-result limit and previews only site row lists on overflow.
Its description distinguishes provider pagination from retained-result
inspection and directs calculations over saved rows to `run_code`.
See the [retained-result contract](../tool-dispatch.md#retained-results-and-artifacts).

Search Analytics fetches successive provider pages internally, using at most
25,000 rows per request. Omitting `row_limit` retrieves every available page;
an explicit value requests a limited result and may span multiple pages.
`start_row` remains an explicit starting position. Repeated pages fail instead
of looping or returning a partial report. Streamed responses and combined pages
share the retained JSON File byte limit across all selected sites. Normalised
rows, provenance, site metadata, and errors count towards the combined result.
Overflow stops further pages and sites, then fails the whole invocation.
Normal tool timeouts still apply.

All retrieved rows reach the saved result before runtime previewing. This
does not remove [Search Console's source-data limits](https://developers.google.com/webmaster-tools/v1/searchanalytics/query):
query- and page-grouped data can omit rows at Google's side. Do not equate
retrieving every available page with access to every underlying search event.

### Indexing API

`GOOGLE_SEARCH_CONSOLE_INDEXING_API_ENABLED` adds the `indexing` OAuth scope
and exposes an approval-only Indexing API tool. The tool accepts up to 20
declared job posting or livestream video pages, routes them with the same
longest-property rule, and requires Search Console Owner permission before
approval. It sends one non-retried mutation per URL and reads notification
metadata for terminal evidence. It never supports automatic execution, and
ambiguous notifications remain unverified.

## Frontend contracts

Google Search Console contributes its logo, catalogue description, and
connection guidance, plus guarded Search Analytics, sitemap, and URL
Inspection presenters over the shared fan-out and table kits. Inspection
results use one compact card per requested URL with status, canonical,
referring-URL, rich-result, and Search Console report details. Sitemap
submissions configure the shared integration write presenter. The approval
view distinguishes a new sitemap from a resubmission when live status is available, validates edited URLs against the
selected writable sites, and states that Google controls whether and when it
crawls the listed URLs.

### Indexing notifications

Indexing API notifications configure the same shared write presenter with
an editable records field for the URL, notification type, and eligible page
type. The approval copy states Google's job posting and livestream video
restriction, and outcome rows distinguish quota, permission, scope, and
unverified results without promising a crawl or indexing result.
