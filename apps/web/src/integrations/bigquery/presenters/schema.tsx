// apps/web/src/integrations/bigquery/presenters/schema.tsx

import { BigQuerySchemaFields } from "@/integrations/bigquery/components/schema-fields"
import { bigQuerySchema } from "@/integrations/bigquery/lib/results"
import { bigQueryProvider } from "@/integrations/bigquery/provider"
import { defineIntegrationResultPresenter } from "@/integrations/read-presenter"
import { formatDateTime } from "@/lib/format"

export const bigQuerySchemaPresenter = defineIntegrationResultPresenter(bigQueryProvider, {
  ariaLabel: "BigQuery table schema",
  details: (schema) => [
    { label: "Table", value: schema.table },
    { label: "Fields", value: String(schema.fields.length) },
    { label: "Last synced", summary: false, value: formatDateTime(schema.lastSyncedAt) },
  ],
  heading: "Get BigQuery Table Schema",
  parseResult: bigQuerySchema,
  progressLabel: "Reading BigQuery table schema…",
  render: (schema) => <BigQuerySchemaFields schema={schema} />,
  tool: "bigquery_get_table_schema",
})
