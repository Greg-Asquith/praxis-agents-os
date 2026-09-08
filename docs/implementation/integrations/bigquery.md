# BigQuery implementation

Read this when changing BigQuery connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

Start with the [backend package](../../../apps/api/integrations/bigquery/)
and [frontend module](../../../apps/web/src/integrations/bigquery/index.ts).

## Backend contracts

BigQuery contributes service-account dataset discovery, a job-synchronised
table-schema cache for enabled datasets (connection jobs fan out into
independently retryable dataset jobs), two cache-backed schema tools, and a
dry-run-gated SELECT query tool with active-dataset, routine, reference-count,
byte, serialised-result, and row bounds. Query jobs bill through the service
account's own project. BigQuery warehouse values are plain typed data under
the operator-controlled database trust boundary. Editor-gated neutral routes
manage forced-RLS table row-scope rules against the schema cache. When any
rule exists, the BigQuery query tool loads rules fresh, rewrites governed
base-table references into typed parameter filters, rejects non-base or
cache-unknown references, and sends the same rewritten query and parameters
through the dry-run and execution requests. The zero-rule request bodies
remain unchanged.
