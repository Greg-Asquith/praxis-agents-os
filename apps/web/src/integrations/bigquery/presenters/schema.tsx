// apps/web/src/integrations/bigquery/presenters/schema.tsx

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { BigQuerySchemaFields } from "@/integrations/bigquery/components/schema-fields"
import { BigQueryToolHeading } from "@/integrations/bigquery/components/tool-heading"
import { bigQuerySchema } from "@/integrations/bigquery/lib/results"
import type { ToolRowPresenter } from "@/integrations/contract"
import { formatDateTime } from "@/lib/format"

export const bigQuerySchemaPresenter: ToolRowPresenter = {
  key: "bigquery-get-table-schema",
  matches: (activity) => activity.name === "bigquery_get_table_schema",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <section
          aria-busy="true"
          aria-label="Reading BigQuery table schema"
          className="border-border grid gap-3 rounded-lg border p-3"
        >
          <BigQueryToolHeading>Get BigQuery Table Schema</BigQueryToolHeading>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-3/4" />
        </section>
      )
    }
    const schema = bigQuerySchema(activity.result)
    if (!schema) {
      return null
    }
    return (
      <ToolResultCard
        ariaLabel="BigQuery table schema"
        defaultOpen={defaultOpen}
        details={[
          { label: "Table", value: schema.table },
          { label: "Fields", value: String(schema.fields.length) },
          {
            label: "Last synced",
            summary: false,
            value: formatDateTime(schema.lastSyncedAt),
          },
        ]}
        heading={<BigQueryToolHeading>Get BigQuery Table Schema</BigQueryToolHeading>}
        trailing={<Badge variant="success">Done</Badge>}
      >
        <BigQuerySchemaFields schema={schema} />
      </ToolResultCard>
    )
  },
}
