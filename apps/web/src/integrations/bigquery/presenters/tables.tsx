// apps/web/src/integrations/bigquery/presenters/tables.tsx

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { BigQueryTableList } from "@/integrations/bigquery/components/table-list"
import { BigQueryToolHeading } from "@/integrations/bigquery/components/tool-heading"
import { bigQueryDatasets } from "@/integrations/bigquery/lib/results"
import type { ToolRowPresenter } from "@/integrations/contract"

export const bigQueryTablesPresenter: ToolRowPresenter = {
  key: "bigquery-list-tables",
  matches: (activity) => activity.name === "bigquery_list_tables",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <section
          aria-busy="true"
          aria-label="Listing BigQuery tables"
          className="border-border/70 grid gap-3 rounded-lg border p-3"
        >
          <BigQueryToolHeading>List BigQuery Tables</BigQueryToolHeading>
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-4/5" />
        </section>
      )
    }
    const datasets = bigQueryDatasets(activity.result)
    if (!datasets) {
      return null
    }
    const tableCount = datasets.reduce((count, dataset) => count + dataset.tables.length, 0)
    return (
      <ToolResultCard
        ariaLabel="BigQuery table results"
        defaultOpen={defaultOpen}
        details={[
          { label: "Datasets", value: String(datasets.length) },
          { label: "Tables", value: String(tableCount) },
        ]}
        heading={<BigQueryToolHeading>List BigQuery Tables</BigQueryToolHeading>}
        trailing={<Badge variant="success">Done</Badge>}
      >
        <BigQueryTableList datasets={datasets} />
      </ToolResultCard>
    )
  },
}
