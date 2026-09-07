// apps/web/src/integrations/google_ads/components/outcome-table.tsx

import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  outcomeKind,
  outcomeLabel,
  outcomeTone,
  type OutcomeKind,
} from "@/integrations/google_ads/lib/outcomes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

export type GoogleAdsOutcomeRow = DataRow & {
  outcome: Parameters<typeof outcomeKind>[0]
  details?: string
  errorCode?: string | string[] | null
}

const ORDER: OutcomeKind[] = ["applied", "skipped", "failed", "unverified"]

export function GoogleAdsOutcomeTable({
  columns,
  rows,
  outcomes,
  exportFilename,
  truncated = false,
  renderCell,
}: {
  columns: DataColumn[]
  rows: GoogleAdsOutcomeRow[]
  outcomes: { kind: OutcomeKind; label: string; count: number }[]
  exportFilename: string
  truncated?: boolean
  renderCell?: (column: DataColumn, row: DataRow) => ReactNode | null
}) {
  const tableColumns: DataColumn[] = [
    ...columns,
    { key: "outcome", kind: "status", label: "Outcome" },
  ]
  if (rows.some((row) => Boolean(row.details)))
    tableColumns.push({ key: "details", kind: "text", label: "Details" })
  if (rows.some((row) => outcomeKind(row.outcome) === "failed"))
    tableColumns.push({ key: "errorCode", kind: "badge", label: "Error code" })
  const tableRows = rows.map((row) => ({
    ...row,
    outcome: outcomeLabel(row.outcome),
    outcomeKind: outcomeKind(row.outcome),
    errorCode: (Array.isArray(row.errorCode) ? row.errorCode : [row.errorCode])
      .filter((code): code is string => Boolean(code))
      .map((code) => googleAdsTokenLabel(code))
      .join(" · "),
  }))
  return (
    <DataTable
      columns={tableColumns}
      rows={tableRows}
      exportFilename={exportFilename}
      pageSize={25}
      header={
        <StatGroup className="px-3 pt-2">
          {ORDER.flatMap((kind) =>
            outcomes
              .filter((outcome) => outcome.kind === kind)
              .map((outcome) => (
                <Stat
                  key={outcome.label}
                  label={outcome.label}
                  value={outcome.count}
                  tone={outcome.count > 0 ? outcomeTone(kind) : undefined}
                />
              ))
          )}
        </StatGroup>
      }
      renderCell={(column, row) =>
        column.key === "outcome" ? (
          <Badge
            variant={
              row["outcomeKind"] === "applied"
                ? "success"
                : row["outcomeKind"] === "failed"
                  ? "destructive"
                  : row["outcomeKind"] === "unverified"
                    ? "warning"
                    : "secondary"
            }
          >
            {String(row["outcome"])}
          </Badge>
        ) : column.key === "errorCode" ? (
          typeof row["errorCode"] === "string" && row["errorCode"] ? (
            <Badge variant="outline">{row["errorCode"]}</Badge>
          ) : null
        ) : (
          (renderCell?.(column, row) ?? null)
        )
      }
      truncationNote={
        truncated ? "Showing a representative sample. Complete evidence is in the Audit Log." : null
      }
    />
  )
}
