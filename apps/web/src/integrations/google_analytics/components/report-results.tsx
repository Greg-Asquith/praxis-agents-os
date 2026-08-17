// apps/web/src/integrations/google_analytics/components/report-results.tsx

import { Badge } from "@/components/ui/badge"
import { DataTable } from "@/components/ui/data-table"
import { formatDataCell, type DataRow } from "@/components/ui/data-table-model"
import type { GoogleAnalyticsReport } from "@/integrations/google_analytics/lib/report-model"

export function GoogleAnalyticsReportResults({
  externalId,
  realtime = false,
  report,
}: {
  externalId: string
  realtime?: boolean
  report: GoogleAnalyticsReport
}) {
  const notes = reportNotes(report)
  return (
    <div className="grid min-w-0 gap-3">
      {realtime ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium">Right now (last 30 minutes)</p>
          <Badge variant="outline">Live window</Badge>
        </div>
      ) : null}
      <AggregateLines report={report} />
      {report.rows.length > 0 && report.columns.length > 0 ? (
        <DataTable
          columns={report.columns}
          exportFilename={`google-analytics-${externalId}-${realtime ? "realtime" : "report"}.csv`}
          rows={report.rows}
          truncationNote={
            report.truncated
              ? `${report.rows.length.toLocaleString()} of ${report.rowCount.toLocaleString()} rows shown.`
              : null
          }
        />
      ) : (
        <p className="text-muted-foreground py-4 text-center text-sm">No report rows returned.</p>
      )}
      {notes.length > 0 ? (
        <ul className="text-muted-foreground grid gap-1 text-xs">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function AggregateLines({ report }: { report: GoogleAnalyticsReport }) {
  const groups = [
    { label: "Totals", rows: report.totals },
    { label: "Minimum", rows: report.minimums },
    { label: "Maximum", rows: report.maximums },
  ]
  const lines = groups.flatMap((group) =>
    group.rows.map((row, index) => ({ index, label: group.label, row }))
  )

  return lines.length > 0 ? (
    <div className="border-border bg-muted/25 grid gap-2 rounded-md border px-3 py-2 text-xs">
      {lines.map(({ index, label, row }) => (
        <AggregateLine key={`${label}:${String(index)}`} label={label} report={report} row={row} />
      ))}
    </div>
  ) : null
}

function AggregateLine({
  label,
  report,
  row,
}: {
  label: string
  report: GoogleAnalyticsReport
  row: DataRow
}) {
  const context = report.columns.flatMap((column) => {
    const value = row[column.key]
    const formatted = formatDataCell(column, value)
    return !column.isMetric &&
      value !== undefined &&
      !(typeof value === "string" && value.startsWith("RESERVED_"))
      ? [{ key: column.key, value: `${column.label} ${formatted}` }]
      : []
  })
  const metrics = report.columns.flatMap((column) =>
    column.isMetric && row[column.key] !== undefined
      ? [
          {
            key: column.key,
            value: `${column.label} ${formatDataCell(column, row[column.key])}`,
          },
        ]
      : []
  )
  if (metrics.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="font-medium">{label}</span>
      {context.map((item) => (
        <span className="text-muted-foreground" key={item.key}>
          {item.value}
        </span>
      ))}
      {metrics.map((item) => (
        <span className="text-muted-foreground" key={item.key}>
          {item.value}
        </span>
      ))}
    </div>
  )
}

function reportNotes(report: GoogleAnalyticsReport): string[] {
  return [
    ...(report.metadata.sampled
      ? report.metadata.samplingNotes.length > 0
        ? report.metadata.samplingNotes.map((note) => `Sampled: ${note}.`)
        : ["Sampled data was used for this report."]
      : []),
    ...(report.metadata.thresholded
      ? ["Some data was withheld by Google Analytics privacy thresholds."]
      : []),
    ...(report.metadata.dataLossFromOtherRow
      ? ["Some rows were grouped as “(other)” by Google Analytics."]
      : []),
  ]
}
