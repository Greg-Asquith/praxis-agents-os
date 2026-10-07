// apps/web/src/integrations/outlook_mail/components/record-table.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"

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
      rowNoun={[noun, nounPlural]}
      pageSize={25}
      rows={rows}
    />
  )
}
