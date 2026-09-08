// apps/web/src/integrations/outlook_mail/components/record-list.tsx

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParsedFanOutData } from "@/components/tool-ui/fan-out"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { OutlookFanOut } from "@/integrations/outlook_mail/components/fan-out"
import { pluralize } from "@/lib/format"

export function OutlookRecordList({
  columns,
  defaultOpen,
  details,
  emptyLabel,
  exportFilename,
  noun,
  nounPlural,
  result,
  title,
}: {
  columns: DataColumn[]
  defaultOpen: boolean
  details?: FanOutDetail[] | undefined
  emptyLabel: string
  exportFilename: string
  noun: string
  nounPlural: string
  result: ParsedFanOutData<DataRow[]>
  title: string
}) {
  return (
    <OutlookFanOut
      defaultOpen={defaultOpen}
      details={details}
      emptyLabel="No mailboxes returned a result."
      entries={result.entries}
      title={title}
    >
      {(_entry, index) => {
        const rows = result.data[index]
        if (!rows) return null
        return rows.length > 0 ? (
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
        ) : (
          <p className="text-muted-foreground py-3 text-center text-sm">{emptyLabel}</p>
        )
      }}
    </OutlookFanOut>
  )
}
