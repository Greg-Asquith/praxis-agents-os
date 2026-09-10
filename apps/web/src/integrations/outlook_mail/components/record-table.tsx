// apps/web/src/integrations/outlook_mail/components/record-table.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { pluralize } from "@/lib/format"

export function OutlookRecordTable({
  columns,
  emptyLabel,
  exportFilename,
  noun,
  nounPlural,
  rows,
}: {
  columns: DataColumn[]
  emptyLabel: string
  exportFilename: string
  noun: string
  nounPlural: string
  rows: DataRow[]
}) {
  if (rows.length === 0) {
    return <EmptyResult>{emptyLabel}</EmptyResult>
  }
  return (
    <DataTable
      columns={columns}
      exportFilename={exportFilename}
      header={
        <p className="text-muted-foreground text-xs">
          {String(rows.length)} {pluralize(rows.length, noun, nounPlural)}
        </p>
      }
      pageSize={25}
      rows={rows}
    />
  )
}
