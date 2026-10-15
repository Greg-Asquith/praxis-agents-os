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
and billed-byte bounds. Query jobs bill through the service
account's own project. BigQuery warehouse values are plain typed data under
the operator-controlled database trust boundary. Editor-gated neutral routes
manage forced-RLS table row-scope rules against the schema cache. When any
rule exists, the BigQuery query tool loads rules fresh, rewrites governed
base-table references into typed parameter filters, rejects non-base or
cache-unknown references, and sends the same rewritten query and parameters
through the dry-run and execution requests. The zero-rule request bodies
remain unchanged.

The query tool authorises the tables and views the SQL names, parsed with
sqlglot before any provider request: each must sit in an active dataset, and
every table needs its dataset in the name. A view in an active dataset is
allowed whatever it reads. BigQuery's dry run lists the tables a view reads
instead of the view itself. When the dry run lists tables from other
datasets, the tool dry-runs each named view the dry run expanded (at most 10)
and allows only the tables those views read. Naming another dataset's table
directly is still refused, as is any table the parser missed that no named
view reads. Region-level
`INFORMATION_SCHEMA` views are outside every dataset and are refused. The
schema cache stores views with their descriptions and column descriptions, as
it does tables. Row filters still reject views.

The query tool executes once, then reads every result page from that same job.
Pagination keeps the billing project and location fixed, rejects repeated page
tokens or inconsistent job metadata, and verifies the final row count.
It adds no SQL row limit and does not cut rows or large cells to fit a model
character budget. Existing File byte limits and tool timeouts bound retrieval;
an oversized or incomplete report fails without returning partial data.
Explicit SQL `LIMIT` clauses remain part of the requested query.

Large results use the shared retained File, preview envelope, and model
instructions. The query card previews rows with pagination and loads the saved
result into the same table through **Open complete result**. Row-filter notices
and query metadata remain visible. See the
[retained-result contract](../tool-dispatch.md#retained-results-and-artifacts).
