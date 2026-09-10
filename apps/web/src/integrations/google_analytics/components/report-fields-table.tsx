// apps/web/src/integrations/google_analytics/components/report-fields-table.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"

const FIELD_COLUMNS: DataColumn[] = [
  { key: "ui_name", kind: "text", label: "Name" },
  { key: "api_name", kind: "id", label: "API name" },
  { key: "category", kind: "text", label: "Category" },
  { key: "custom", kind: "badge", label: "Definition" },
]

export function GoogleAnalyticsReportFieldsTable({
  count,
  externalId,
  fields,
  kind,
  label,
  truncated,
}: {
  count: number
  externalId: string
  fields: DataRow[]
  kind: string
  label: string
  truncated: boolean
}) {
  return (
    <section aria-label={label} className="grid min-w-0 gap-2">
      <h3 className="text-sm font-medium">{label}</h3>
      {fields.length > 0 ? (
        <DataTable
          columns={FIELD_COLUMNS}
          exportFilename={`google-analytics-${externalId}-${kind}.csv`}
          rows={fields}
          truncationNote={
            truncated && fields.length < count
              ? `${fields.length.toLocaleString()} of ${count.toLocaleString()} fields shown.`
              : null
          }
        />
      ) : (
        <EmptyResult>No {kind} matched.</EmptyResult>
      )}
    </section>
  )
}
