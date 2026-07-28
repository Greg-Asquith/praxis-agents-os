// apps/web/src/integrations/bigquery/components/table-list.tsx

import { Badge } from "@/components/ui/badge"
import { formatDateTime } from "@/lib/format"
import type { BigQueryDataset } from "@/integrations/bigquery/lib/results"

export function BigQueryTableList({ datasets }: { datasets: BigQueryDataset[] }) {
  if (datasets.length === 0) {
    return <p className="text-muted-foreground py-4 text-center text-sm">No datasets selected.</p>
  }
  return (
    <div className="grid gap-4">
      {datasets.map((dataset) => (
        <section className="grid min-w-0 gap-2" key={dataset.dataset}>
          <div className="flex min-w-0 items-baseline justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate text-sm font-medium">{dataset.displayName}</h3>
              <code className="text-muted-foreground block truncate text-xs">
                {dataset.dataset}
              </code>
            </div>
            <Badge variant="outline">
              {String(dataset.tables.length)} {dataset.tables.length === 1 ? "table" : "tables"}
            </Badge>
          </div>
          {dataset.tables.length > 0 ? (
            <div className="border-border/70 divide-border/70 divide-y overflow-hidden rounded-lg border">
              {dataset.tables.map((table) => (
                <div
                  className="hover:bg-muted/25 flex min-w-0 flex-wrap items-start gap-2 px-3 py-2.5"
                  key={table.table}
                >
                  <div className="min-w-44 flex-1">
                    <code className="block truncate text-sm">{table.table}</code>
                    {table.description ? (
                      <p className="text-muted-foreground mt-0.5 line-clamp-2 text-xs">
                        {table.description}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-1.5">
                    <Badge variant="secondary">{table.tableType.replaceAll("_", " ")}</Badge>
                    {table.rowCount !== null ? (
                      <Badge variant="outline">
                        {new Intl.NumberFormat().format(table.rowCount)} rows
                      </Badge>
                    ) : null}
                    <span className="text-muted-foreground text-xs">
                      Synced {formatDateTime(table.lastSyncedAt, "medium", "short")}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="border-border/70 text-muted-foreground rounded-lg border border-dashed px-3 py-4 text-center text-sm">
              No cached tables in this dataset.
            </p>
          )}
        </section>
      ))}
    </div>
  )
}
