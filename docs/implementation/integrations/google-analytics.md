# Google Analytics implementation

Read this when changing Google Analytics connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

Start with the [backend package](../../../apps/api/integrations/google_analytics/)
and [frontend module](../../../apps/web/src/integrations/google_analytics/index.ts).

## Backend contracts

Google Analytics contributes workspace OAuth and service-account connection,
a bearer-only Data/Admin REST client, and bounded Admin API discovery of
read-only GA4 properties. Its five code-eligible read tools discover
standard/custom report fields, check which candidate fields can be added to a
compatible standard report, and run structured standard or realtime reports
with local request validation and header-typed metric values, and list the
Google Ads accounts linked to each selected
property without exposing link creator email addresses. Standard reports also
expose access-restriction and sampling metadata. Accounts remain property
metadata, and discovery must not add per-property enrichment calls. Its OAuth
settings stay in the provider package
and use a Google Cloud client isolated from every other Google service.

Standard and realtime reports preview row lists while retaining headers,
aggregates, and report metadata. Field discovery previews both dimensions
and metrics. These tools declare their public budget from the configured
structured-result limit and describe complete-data retrieval through Files
and permitted native code helpers. See the
[retained-result contract](../tool-dispatch.md#retained-results-and-artifacts).

Standard reports omit a total row limit by default and fetch successive
10,000-row pages internally until the provider's `rowCount` is reached.
An explicit `limit` requests a top-N or limited result; `offset` remains an
explicit starting position. Changed report metadata, repeated pages, and
premature empty pages fail without returning a partial report. Provider
aggregates and sampling metadata remain attached to the combined result.

Realtime reports request up to the provider's 250,000-row maximum by default.
The [realtime API](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runRealtimeReport)
has no offset or page token. A larger reported `rowCount` therefore remains
an explicit provider limitation, separate from the saved-result preview.
Field discovery returns every matching dimension and metric by default;
its optional limit only applies when explicitly requested.

Complete responses use the existing retained JSON File byte limit and tool
timeouts. Standard reports, realtime reports, and field discovery share one
allowance across every selected property. Pagination uses the remaining
allowance, and normalised rows, metadata, and errors count towards the result.
Overflow stops further pages and properties, then fails the whole invocation.
Only the runtime preview shortens successful large results; the saved File
retains all returned rows.

## Frontend contracts

Google Analytics contributes its logo, catalogue description,
connection guidance, and guarded report, realtime, report-field,
compatibility, and linked-Google-Ads-account presenters over the shared
fan-out and table kits.
