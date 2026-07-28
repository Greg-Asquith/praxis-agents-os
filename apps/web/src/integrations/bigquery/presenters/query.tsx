// apps/web/src/integrations/bigquery/presenters/query.tsx

import { Badge } from "@/components/ui/badge"
import { DataTable, DataTableSkeleton } from "@/components/ui/data-table"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { BigQueryToolHeading } from "@/integrations/bigquery/components/tool-heading"
import { bigQueryQueryResult } from "@/integrations/bigquery/lib/results"
import type { ToolRowPresenter } from "@/integrations/contract"
import { formatBytes } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const bigQueryQueryPresenter: ToolRowPresenter = {
  key: "bigquery-run-query",
  matches: (activity) => activity.name === "bigquery_run_query",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <section
          aria-busy="true"
          aria-label="Running BigQuery query"
          className="border-border/70 grid gap-3 rounded-lg border p-3"
        >
          <BigQueryToolHeading>Run BigQuery Query</BigQueryToolHeading>
          <DataTableSkeleton label="Running BigQuery query…" />
        </section>
      )
    }
    const result = bigQueryQueryResult(activity.result)
    if (!result) {
      return null
    }
    const query = queryArgument(activity.args)
    return (
      <ToolResultCard
        ariaLabel="BigQuery query results"
        defaultOpen={defaultOpen}
        details={[
          ...(query ? [{ label: "GoogleSQL query", summary: false, value: query }] : []),
          { label: "Rows", value: `${String(result.rows.length)} of ${String(result.totalRows)}` },
          { label: "Processed", value: formatBytes(result.totalBytesProcessed) },
          { label: "Query cache", summary: false, value: result.cacheHit ? "Hit" : "Miss" },
        ]}
        heading={<BigQueryToolHeading>Run BigQuery Query</BigQueryToolHeading>}
        trailing={
          <Badge variant={result.truncated ? "warning" : "success"}>
            {result.truncated ? "Limited" : "Done"}
          </Badge>
        }
      >
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
          <p className="text-muted-foreground py-4 text-center text-sm">
            {result.truncated && result.totalRows > 0
              ? "The result exceeded the safe output limit. Narrow the query or select fewer columns."
              : "The query returned no rows."}
          </p>
        )}
      </ToolResultCard>
    )
  },
}

function queryArgument(value: unknown): string | null {
  if (!isRecord(value) || typeof value["query"] !== "string") {
    return null
  }
  return value["query"]
}
