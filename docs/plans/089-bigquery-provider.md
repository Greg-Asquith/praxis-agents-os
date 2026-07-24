# Plan 089: Google BigQuery provider — service accounts, dataset context, cached schemas, SELECT-only queries

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md` and record the provider in the roadmap's
> Phase 4a table.
>
> **Notes pre-flight (run before Step 1)**: this plan is bound by
> `docs/architecture/integration-packaging.md` (D10 — self-contained
> provider package, import laws, per-provider extras),
> `docs/architecture/governance.md` §1/§2 (resource selection RBAC, read
> tools default `auto`), and `docs/architecture/threat-model.md` channel
> (g) (integration-fetched content). It absorbs `FOLLOW_UPS.md` item 8's
> service-account generalization trigger. Re-read those sections; the
> notes win over this plan.
>
> **Drift check (run first)**:
> `git diff --stat c9a8cfd..HEAD -- apps/api/services/integrations/ apps/api/services/agents/runtime/tools/ apps/api/models/integrations.py apps/api/models/integration_context.py apps/api/services/jobs/ apps/api/core/settings/integrations.py apps/api/integrations/`
> Any change to the anchors quoted in "Current state" is a STOP-grade
> mismatch — re-verify the excerpt against the tree before continuing.

## Status

- **Priority**: P2
- **Effort**: L (four slices; one migration; one new provider package)
- **Risk**: MEDIUM (customer-supplied credentials and real query spend,
  but read-only capability, no new auth mechanism, and every substrate it
  rides — connect flow, discovery, context, fan-out, jobs, audit — is
  landed and tested)
- **Depends on**: 037/038 (**DONE** — credential + connect substrate,
  including the service-account connect flow), 039 (**DONE** — discovery
  engine), 040 (**DONE** — context groups + active-context resolution),
  041 (**DONE** — provider packaging precedent, shared untrusted-content
  carrier, bounded provider HTTP), 030 (**DONE** — jobs harness).
  **No Phase 4b dependency**: slices A–D are self-contained; the semantic
  schema-search follow-up (Maintenance notes) is the only piece that
  waits on 045.
- **Category**: Phase 4a extension — first provider added after the D4
  set, under decision D14 (roadmap §2) and the D10 packaging law.
- **Planned at**: commit `c9a8cfd`, 2026-07-24. Anchors verified against
  that tree.
- **Execution progress**: TODO.

## Decisions taken

1. **Service-account only, workspace-shared.** Manifest:
   `auth_modes=("service_account",)`, `owner_scope="workspace"`,
   `requires_discovery=True`, `resource_types=("bigquery_dataset",)`,
   `capability_flags={"read"}`, no `event_delivery`. No OAuth mode ships
   (superseded decisions, item 1), so roadmap D12's per-service OAuth
   client isolation does not bind — the revocation boundary is the
   customer's own IAM on the supplied service account. The landed connect
   flow (`connect_service_account.py`, `ServiceAccountConnectRequest`) is
   reused unchanged: raw JSON goes to the secrets provider, the
   credential row stores only a versioned secret reference, and the
   connection lands workspace-owned in `discovery_pending`.
2. **Generalize the Google service-account helper instead of branching
   (absorbs FOLLOW_UPS item 8).** `GoogleServiceAccountTokenProvider`
   already mints JWT-bearer tokens for any scope; the validation
   messages in `services/integrations/credentials/google_service_account.py`
   hardcode `google_ads`. This plan parameterizes the provider key in
   those helpers and has both providers pass their own. No provider
   branches enter the discovery engine or credential service. Token
   scope for BigQuery: `https://www.googleapis.com/auth/bigquery` —
   the `bigquery.readonly` scope cannot create query jobs, so read-only
   is enforced by IAM posture plus decision 8, not by scope.
3. **Recommended IAM posture is documented, enforced posture is
   layered.** `connect_help` (plain-language, per the non-technical
   operator standard) tells the operator to grant the service account
   `roles/bigquery.jobUser` on its own project and
   `roles/bigquery.dataViewer` on the projects or datasets it should
   read — and nothing writable. Praxis does not trust that posture:
   SELECT-only is independently enforced at the API authority layer
   (decision 8), so an over-granted key still cannot be driven to write
   through Praxis tools.
4. **Discoverable assets are datasets, and only datasets.**
   `discover_resources` walks `projects.list` → `datasets.list` with the
   bounded shared HTTP client and emits one
   `DiscoveredIntegrationResource` per dataset:
   `resource_type="bigquery_dataset"`,
   `external_id="<project_id>.<dataset_id>"`, `writable=False` always,
   and `permissions_metadata` carrying `project_id`, `dataset_id`, and
   the dataset **location** (needed at query time — BigQuery jobs must
   run in the data's location). Datasets then ride the landed 039
   reconcile/selection machinery and the landed 040 context groups with
   zero new code — which delivers "datasets assigned to context groups"
   for free. Tables are deliberately **not** `IntegrationResource` rows:
   cardinality is 10–1000× datasets, selection UX is dataset-level, and
   table metadata belongs in the schema cache (decision 5).
5. **A Praxis-side schema cache, provider-neutral in shape.** New core
   table `integration_table_schemas` (next free `core_00NN` migration),
   named and shaped so a future warehouse provider (Snowflake, Postgres)
   reuses it rather than minting a sibling:
   - `id`, `resource_id` FK → `integration_resources` (CASCADE),
     `table_external_id` (table name within the dataset), unique on
     `(resource_id, table_external_id)`.
   - `table_type` (`table`/`view`/`materialized_view`/`external`),
     `description`, `schema_fields` JSONB (ordered fields:
     name/type/mode/description, nested RECORD fields flattened with
     dotted paths), `partitioning` JSONB (type, field,
     `require_partition_filter`), `clustering_fields` JSONB,
     `row_count`, `size_bytes`, `provider_last_modified_at`.
   - `availability` (`available`/`removed`), `first_synced_at`,
     `last_synced_at`.
   Rows are reconciled idempotently in the 039 mold (insert / update /
   mark `removed`; never hard-deleted by the sync) and hard-deleted by
   the existing integrations retention sweep when their resource row is
   swept. Agent-facing schema tools read **only** this cache — the
   BigQuery API is never called to answer "what tables and fields
   exist".
6. **Schema ingestion is a job with a manifest-declared trigger seam.**
   New job kind `integrations.sync_table_schemas` (kind is generic;
   payload is ids-only per 030 discipline; subject =
   `integration_connection`, so the partial-unique in-flight index gives
   one sync per connection for free). To avoid provider branches in the
   engine, `IntegrationProviderPlugin` gains one optional field,
   `metadata_sync_job_kind: str | None = None`; the discovery handler
   and the resource-selection service enqueue that kind after a
   successful discovery / selection change when the plugin declares it.
   The handler itself lives in the provider package's registration seam
   and syncs **enabled** datasets only, via `tables.list` + `tables.get`
   (schema, description, partitioning, clustering, `numRows`,
   `lastModified` in two calls; no query spend). Periodic freshness
   rides the existing `integrations.rediscover_stale` cadence — a
   completed periodic re-discovery chains the same enqueue, so schemas
   are at most `INTEGRATIONS_REDISCOVERY_INTERVAL_SECONDS` stale.
   Bounds: `BIGQUERY_SCHEMA_SYNC_MAX_TABLES` (default 500) per dataset;
   hitting the cap records a truncation note in the connection's
   `provider_metadata` — no silent partial coverage.
7. **Three read tools, cache-first.** All `effect=read`,
   `default_policy="auto"`, `supports_approval=True`, bound to
   `bigquery_dataset` via `IntegrationToolBinding`, presented through
   server-declared `ToolPresentation` (new `bigquery` icon token; no
   frontend module needed under the default-first UI law):
   - `bigquery_list_tables()` — cache-only; per active dataset: table
     name, type, description, row count, last-synced timestamp.
   - `bigquery_get_table_schema(table)` — cache-only; full field list
     including nested fields, partitioning (with an explicit "this
     table REQUIRES a partition filter" line when
     `require_partition_filter` is set), clustering, and the exact
     backticked fully-qualified name to use in SQL.
   - `bigquery_run_query(query)` — the live tool (decision 8).
   Tool docstrings state the dialect contract once: GoogleSQL, backticked
   `` `project.dataset.table` `` names, single statement.
8. **The query pipeline is dry-run-first; the dry run is the
   authorization and accuracy authority.** `bigquery_run_query` does
   not regex-guess at SQL. Pipeline:
   1. Resolve the active context. All context BigQuery datasets must
      belong to **one** connection (one credential signs the job); a
      context spanning two BigQuery connections raises `ModelRetry`
      telling the model to ask the user to narrow the context.
   2. **Dry run** (`jobs.insert` with `dryRun=true`):
      - Google-side syntax/semantic errors return as `ModelRetry`
        carrying Google's message verbatim — this is the agent's
        self-correction loop, and it is free.
      - `statementType` must be `SELECT`. DML, DDL, scripts,
        multi-statement, and `CALL` are rejected by the API's own
        classification — stronger than any local parser.
      - `referencedTables` must all fall inside the active context's
        enabled datasets. Anything else → `ModelRetry` naming the
        offending table. This — not string inspection — is the
        boundary that keeps agents inside their assigned context.
      - `totalBytesProcessed` must not exceed
        `BIGQUERY_MAX_BYTES_BILLED` (default 1 GiB
        [default — confirm at review]) → `ModelRetry` advising a
        narrower query or partition filter, quoting the estimate.
   3. **Real job**: `maximumBytesBilled` set to the same cap (Google
      enforces the backstop even if our estimate was wrong), `location`
      from the dataset's cached metadata, job timeout from
      `BIGQUERY_QUERY_TIMEOUT_SECONDS` (default 60), `useQueryCache`
      left on, and job **labels** stamping workspace/agent/run ids
      (lowercased per label constraints) so BigQuery-side cost
      attribution matches Praxis audit rows.
   4. **Results**: rows capped by the existing
      `INTEGRATION_REPORT_MAX_ROWS`; the typed `output_model` carries
      rows, `total_rows`, `truncated`, `total_bytes_processed`, and
      `cache_hit`. Cell values are strings; result content is wrapped
      in the 041 shared untrusted-content carrier (decision 9).
9. **Gate G6**: warehouse cell values are integration-fetched content —
   threat-model channel (g) covers the class; this plan adds the
   BigQuery adversarial fixture (a query whose result cell contains an
   injection payload) and pins the carrier framing deterministically,
   with a graded case in the 055 eval layer.
10. **Packaging per D10**: everything provider-specific lives in
    `apps/api/integrations/bigquery/` (manifest, settings mixin,
    client, discovery, sync handler registration, `tools/` one module
    per tool). Google API access uses the shared bounded `httpx2`
    request path against the REST API directly — **no
    `google-cloud-bigquery` SDK dependency** (superseded decisions,
    item 5); no pyproject extra is needed. Engine-side deltas are
    exactly: the `metadata_sync_job_kind` plugin field (decision 6),
    the parameterized service-account helper (decision 2), the
    `bigquery` icon token, and the migration.

## Superseded decisions

1. **Per-user OAuth mode** — rejected. Operator requirement is
   workspace-shared service accounts; a user-delegated mode would add a
   second credential posture and D12 OAuth-client isolation obligations
   for no current product need. Revisit only on real demand.
2. **Tables as discoverable resources** — rejected for cardinality and
   selection UX; the schema cache (decision 5) is the table surface.
3. **Local SQL parsing as the SELECT guard** — rejected. A regex/parser
   can be evaded and drifts from GoogleSQL; the dry run's
   `statementType` + `referencedTables` is authoritative and also
   powers the self-correction loop.
4. **Write tools (DML/DDL/load)** — out of scope for v1. If ever added
   they default to `approval` with `supports_auto=False` per governance
   §2, and require revisiting decision 3's IAM guidance.
5. **`google-cloud-bigquery` SDK** — rejected. The three REST surfaces
   used (`datasets.list`/`tables.*`, `jobs.insert` dry run,
   `jobs.query`) are thin; the shared bounded HTTP client keeps retry,
   timeout, and Retry-After behavior uniform with the other providers
   and avoids a heavyweight per-provider extra.
6. **Sample-row / value profiling in the schema cache** — deferred, not
   ingested silently. Top-N values for low-cardinality columns would
   measurably improve literal accuracy in WHERE clauses, but it copies
   customer data into Praxis and needs its own consent, privacy, and
   retention treatment. Recorded in Maintenance notes as an explicit
   opt-in follow-up.

## Why this matters

This is the first analytics-warehouse provider: agents that can read a
customer's BigQuery answer the reporting questions the agency product
exists for. It is also the cheapest possible proof of three seams built
in Phase 4a — service-account credentials beyond Google Ads
(FOLLOW_UPS 8), dataset-shaped discovery feeding context groups, and a
provider-owned metadata cache over the jobs harness — before Snowflake
or Postgres providers repeat the pattern. The schema cache is the
accuracy lever: agents write good SQL when the full table/field/type/
description inventory is one cheap tool call away, and the dry-run loop
turns Google's own validator into the agent's error feedback.

## Current state

Verified at `c9a8cfd`:

- `services/integrations/manifest.py:9` — `AUTH_MODES` includes
  `service_account`; `:14` `IntegrationProviderManifest`.
- `services/integrations/plugin.py:149` — `IntegrationProviderPlugin`
  (`manifest`, `discover_resources`, `tool_definitions`, …); `:27`
  `DiscoveredIntegrationResource`.
- `services/integrations/loader.py:15` — allowlist-driven load;
  registers manifests, plugins, and tool definitions.
- `services/integrations/connections/connect_service_account.py:31` —
  landed service-account connect: secrets-provider write, reference-only
  credential, workspace-owned connection, `enqueue_discovery`.
- `services/integrations/credentials/google_service_account.py:24,68` —
  parser + `GoogleServiceAccountTokenProvider` (any scope); messages
  currently hardcode `google_ads` (decision 2 target).
- `services/integrations/discovery/run_discovery.py:47` — engine;
  idempotent reconcile `:273`; `recompute_connection_status` law.
- `models/integrations.py:100,175` — `IntegrationConnection`
  (workspace XOR user owner), `IntegrationResource` (unique
  `(connection_id, resource_type, external_id)`).
- `models/integration_context.py:12,48,78` — context groups, members,
  per-conversation `ActiveContextSelection`.
- `services/integrations/context/fan_out.py:35`,
  `domain.py:64` — resolution + compatibility filtering the query tool
  consumes (single-execution shape per decision 8.1, not per-resource
  fan-out; the GAQL fan-out precedent is per-account because GAQL is
  account-relative — BigQuery SQL is fully qualified).
- `services/agents/runtime/tools/contract.py:63` — `VALID_TOOL_ICONS`
  (add `bigquery`); `:46` parameter denylist (tools accept no
  connection/account ids — context is server-resolved).
- `integrations/google_ads/` — the template package: manifest with
  `service_account`, bounded client, discovery, `tools/run_report.py`
  (bounded SQL-report precedent), `operations/run_report.py`
  (`bounded_query`, `INTEGRATION_REPORT_MAX_ROWS`).
- `services/jobs/registry.py:32` `@job_handler`;
  `services/jobs/handlers/extract_file_markdown.py:26` — ingestion-job
  template; `models/jobs.py:74` in-flight dedup index.
- `core/settings/integrations.py:9,70` —
  `INTEGRATIONS_ENABLED_PROVIDERS`, `INTEGRATION_REPORT_MAX_ROWS`.
- `alembic/versions/core/0020_add_kb_documents_and_chunks.py` — latest
  core migration; this plan takes the next free number.
- No `bigquery` code exists anywhere in the tree.

## Commands you will need

| Purpose            | Command                                                      | Expect                        |
| ------------------ | ------------------------------------------------------------ | ----------------------------- |
| Full gate          | `make check`                                                 | green                         |
| API tests only     | `make api-test`                                              | green, DB-backed suites run   |
| Migration drift    | `make api-migration-check` (or the `make check` subset)      | no drift                      |
| New migration      | `cd apps/api && uv run alembic revision ...` (core branch)   | `core_00NN` file              |
| Provider on        | add `bigquery` to `INTEGRATIONS_ENABLED_PROVIDERS` in `.local/` env | loader registers it     |

## Scope

**In scope**
- `apps/api/integrations/bigquery/` (new package: `__init__.py`,
  `settings.py`, `client.py`, `discover_resources.py`,
  `sync_table_schemas.py`, `operations/`, `tools/`).
- `apps/api/models/integration_table_schema.py` + `core_00NN` migration.
- `services/integrations/plugin.py` (one optional field),
  `services/integrations/credentials/google_service_account.py`
  (parameterize provider key), discovery handler + selection service
  (generic enqueue of `metadata_sync_job_kind`), retention sweep (cache
  rows follow their resource).
- `services/agents/runtime/tools/contract.py` (`bigquery` icon token)
  and the frontend icon map entry.
- `core/settings/integrations.py` orchestration knobs only if shared;
  provider knobs live in `integrations/bigquery/settings.py` (byte cap,
  timeout, sync table cap).
- Threat-model fixture + 055 graded case; docs (`apps/api/AGENTS.md`
  provider list, architecture notes if the packaging note's provider
  table is updated).

**Out of scope (do NOT touch)**
- Gmail / Google Ads / Airtable packages (except the shared
  service-account helper call sites), the dispatch choke point, the
  discovery engine's reconcile logic, connect routes, context-group
  services, the KB pipeline (044–047), and any write-capable BigQuery
  surface.

## Git workflow

Branch `advisor/089-bigquery-provider`; one commit per slice; no commit
without explicit human approval per AGENTS.md.

## Execution slices

- **Slice A — provider package + discovery**: package skeleton,
  manifest, settings, bounded client, generalized service-account
  helper (decision 2), `discover_resources` (decision 4), enablement +
  loader/manifest tests, connect→discover→select QA against a real
  sandbox project. Gate: dataset resources appear and are selectable
  into context groups with zero engine changes beyond decision 2.
- **Slice B — schema cache + sync job**: migration + model (decision
  5), `metadata_sync_job_kind` seam (decision 6), sync handler with
  idempotent reconcile + bounds, trigger wiring (post-discovery,
  post-selection, periodic), retention. Gate: cache rows exist for
  enabled datasets only; re-running the job is a no-op; disabling a
  dataset stops future syncs.
- **Slice C — tools**: `bigquery_list_tables`,
  `bigquery_get_table_schema` (cache-only),
  `bigquery_run_query` with the decision-8 pipeline; typed output
  models; untrusted-content wrapping; G6 fixture + eval case; audit
  via the standard per-call integration audit seam. Gate: DML/DDL and
  out-of-context tables are rejected in tests via recorded dry-run
  responses; byte-cap and row-cap truncation are pinned.
- **Slice D — UI + docs + live QA**: `bigquery` icon token + frontend
  icon entry; verify the integrations UI service-account connect path
  (the JSON paste form is write-only, mirroring the API-key flow — if
  042 shipped no service-account form, add it here as the generic
  manifest-driven form, not a BigQuery-specific one); plain-language
  connect help; docs; live QA checklist (connect, discover, group,
  query, cap-hit, injection fixture).

## Test plan

- Manifest/loader registration and packaging-law import test (the
  suite-local pattern from D11).
- Discovery reconcile idempotency with recorded `datasets.list`
  responses (transport-mocked, per D11).
- Sync handler: insert/update/remove reconcile, `require_partition_filter`
  captured, table-cap truncation note, enabled-only scope.
- Query tool: statement-type rejection, out-of-context
  `referencedTables` rejection, byte-cap rejection with quoted
  estimate, multi-connection context rejection, label stamping, row
  truncation metadata, location passed from cached dataset metadata —
  all against recorded dry-run/job fixtures.
- G6: injection payload in a result cell arrives framed; deterministic
  carrier test + graded eval case.
- RBAC: selection and connect remain owner/editor-gated exactly as the
  landed routes enforce; no new routes are added.

## Done criteria

- [ ] `bigquery` loads from the allowlist; manifest validates;
      packaging import laws hold.
- [ ] Datasets discover, select, and join context groups end to end.
- [ ] `integration_table_schemas` populated by the job; cache answers
      both schema tools with no provider I/O.
- [ ] `bigquery_run_query` enforces SELECT-only, context containment,
      and byte/row caps via dry run; errors round-trip as `ModelRetry`.
- [ ] Results are untrusted-framed; fixture and eval case land.
- [ ] `make check` green; live QA checklist executed against a real
      sandbox project (or its unavailability recorded in this plan).
- [ ] FOLLOW_UPS item 8 updated (absorbed here); README status row
      flipped; roadmap Phase 4a table updated.

## STOP conditions

- The landed service-account connect flow requires any change beyond
  decision 2's message parameterization — stop; the connect substrate
  is shared with Google Ads and changes need their own review.
- The dry-run API cannot deliver `statementType` or `referencedTables`
  for a query class the tool must support — stop and report before
  substituting local SQL parsing.
- The `metadata_sync_job_kind` seam turns out to need more than one
  optional plugin field (e.g. engine-side provider knowledge) — stop;
  that is a packaging-law violation in the making.
- Any test requires live Google credentials to pass — stop; live access
  is QA-only, tests use recorded transport fixtures per D11.

## Maintenance notes

- **Semantic schema search** (deferred): when a workspace's enabled
  datasets exceed roughly 200 cached tables, `bigquery_list_tables`
  stops being a usable index. The follow-up embeds one document per
  table (name + description + field lines) via the landed 043
  embeddings service and adds `bigquery_search_tables`; it should ride
  the 045 hybrid-search substrate rather than a provider-local index.
  Becomes a numbered plan when picked up.
- **Sample-value profiling** (deferred, opt-in): top-N distinct values
  for low-cardinality columns sharply improve WHERE-clause literals but
  copy customer data into Praxis — needs explicit operator opt-in,
  privacy/retention treatment, and its own review.
- **Verified query library** (deferred): operator- or agent-curated
  exemplar queries per dataset (the strongest known accuracy lever
  after schema descriptions). Natural fit for the KB or skills once
  044–047 land.
- **Column descriptions are the operator's lever**: connect help and
  docs should say plainly that filling in BigQuery table/column
  descriptions is the single best way to make agents write accurate
  SQL — the cache and tools surface them everywhere they exist.
- **Second warehouse provider**: the schema-cache table and the
  `metadata_sync_job_kind` seam are the reuse surface; a Snowflake or
  Postgres provider should need only its own package.
