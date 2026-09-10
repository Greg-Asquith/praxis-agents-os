// apps/web/src/integrations/bigquery/presenters/tables.tsx

import { BigQueryTableList } from "@/integrations/bigquery/components/table-list"
import { bigQueryDatasets } from "@/integrations/bigquery/lib/results"
import { bigQueryProvider } from "@/integrations/bigquery/provider"
import { defineIntegrationResultPresenter } from "@/integrations/read-presenter"

export const bigQueryTablesPresenter = defineIntegrationResultPresenter(bigQueryProvider, {
  ariaLabel: "BigQuery table results",
  details: (datasets) => [
    { label: "Datasets", value: String(datasets.length) },
    {
      label: "Tables",
      value: String(datasets.reduce((count, dataset) => count + dataset.tables.length, 0)),
    },
  ],
  heading: "List BigQuery Tables",
  parseResult: bigQueryDatasets,
  progressLabel: "Listing BigQuery tables…",
  render: (datasets) => <BigQueryTableList datasets={datasets} />,
  tool: "bigquery_list_tables",
})
