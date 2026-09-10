// apps/web/src/integrations/bigquery/presenters/query.tsx

import { Badge } from "@/components/ui/badge"
import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable } from "@/components/ui/data-table"
import { bigQueryQueryResult } from "@/integrations/bigquery/lib/results"
import { bigQueryProvider } from "@/integrations/bigquery/provider"
import { defineIntegrationResultPresenter } from "@/integrations/read-presenter"
import { compactDetails, stringDetail } from "@/integrations/tool-details"
import { formatBytes } from "@/lib/format"

export const bigQueryQueryPresenter = defineIntegrationResultPresenter(bigQueryProvider, {
  ariaLabel: "BigQuery query results",
  details: (result, args) =>
    compactDetails([
      stringDetail(args, "query", "GoogleSQL query", false),
      { label: "Rows", value: `${String(result.rows.length)} of ${String(result.totalRows)}` },
      { label: "Processed", value: formatBytes(result.totalBytesProcessed) },
      { label: "Query cache", summary: false, value: result.cacheHit ? "Hit" : "Miss" },
    ]),
  heading: "Run BigQuery Query",
  parseResult: bigQueryQueryResult,
  progressLabel: "Running BigQuery query…",
  render: (result) => (
    <>
      {result.rowFiltersApplied ? (
        <p className="bg-muted/50 text-muted-foreground mb-3 rounded-lg border px-3 py-2 text-xs">
          Row filters limited this result to allowed values.
        </p>
      ) : null}
      {result.rows.length > 0 && result.columns.length > 0 ? (
        <DataTable
          columns={result.columns}
          exportFilename="bigquery-results.csv"
          rows={result.rows}
          truncationNote={
            result.truncated
              ? `Showing ${String(result.rows.length)} of ${String(result.totalRows)} rows.`
              : null
          }
        />
      ) : (
        <EmptyResult>
          {result.truncated && result.totalRows > 0
            ? "The result exceeded the safe output limit. Narrow the query or select fewer columns."
            : "The query returned no rows."}
        </EmptyResult>
      )}
    </>
  ),
  tool: "bigquery_run_query",
  trailing: (result) => (
    <Badge variant={result.truncated ? "warning" : "success"}>
      {result.truncated ? "Limited" : "Done"}
    </Badge>
  ),
})
