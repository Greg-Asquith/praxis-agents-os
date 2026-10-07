// apps/web/src/integrations/meta_ads/components/outcome-table.tsx

import type { ReactNode } from "react"

import { OutcomeSummary } from "@/components/tool-ui/outcome-summary"
import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import {
  countByKind,
  outcomeKind,
  outcomeLabel,
  outcomeTone,
  type OutcomeKind,
  type OutcomeToken,
} from "@/integrations/meta_ads/lib/outcomes"
import { titleCaseToken } from "@/lib/format"

export type MetaAdsOutcomeRow = DataRow & {
  outcome: OutcomeToken
  details?: string
  errorCode?: string | null
}

const BADGE_VARIANTS = {
  applied: "success",
  failed: "destructive",
  skipped: "secondary",
  unverified: "warning",
} as const

export function MetaAdsOutcomeTable({
  columns,
  rows,
  exportFilename,
  renderCell,
}: {
  columns: DataColumn[]
  rows: MetaAdsOutcomeRow[]
  exportFilename: string
  renderCell?: (column: DataColumn, row: DataRow) => ReactNode | null
}) {
  const tableColumns: DataColumn[] = [
    ...columns,
    { key: "outcome", kind: "status", label: "Outcome" },
  ]
  if (rows.some((row) => Boolean(row.details)))
    tableColumns.push({ key: "details", kind: "text", label: "Details" })
  if (rows.some((row) => row.errorCode))
    tableColumns.push({ key: "errorCode", kind: "badge", label: "Error Code" })
  const tableRows = rows.map((row) => ({
    ...row,
    outcome: outcomeLabel(row.outcome),
    outcomeKind: outcomeKind(row.outcome),
    errorCode: row.errorCode ? titleCaseToken(row.errorCode, row.errorCode) : "",
  }))
  return (
    <DataTable
      columns={tableColumns}
      rows={tableRows}
      exportFilename={exportFilename}
      pageSize={25}
      summary={
        <OutcomeSummary
          items={countByKind(rows).map((item) => ({ ...item, tone: outcomeTone(item.kind) }))}
        />
      }
      renderCell={(column, row) => {
        if (column.key === "outcome") {
          const kind = row["outcomeKind"] as OutcomeKind
          return <Badge variant={BADGE_VARIANTS[kind]}>{String(row["outcome"])}</Badge>
        }
        if (column.key === "errorCode") {
          return typeof row["errorCode"] === "string" && row["errorCode"] ? (
            <Badge variant="outline">{row["errorCode"]}</Badge>
          ) : null
        }
        return renderCell?.(column, row) ?? null
      }}
    />
  )
}

export function MetaAdsFailureTargets({
  description,
  targets,
}: {
  description: string
  targets: readonly string[]
}) {
  return (
    <div className="grid gap-2">
      <p className="text-destructive text-sm">{description}</p>
      {targets.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {Array.from(new Set(targets)).map((target) => (
            <Badge key={target} variant="secondary">
              {target}
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  )
}
