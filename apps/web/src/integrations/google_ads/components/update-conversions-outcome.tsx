// apps/web/src/integrations/google_ads/components/update-conversions-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { cellText } from "@/integrations/ads/lib/cell-text"
import {
  EDIT_OUTCOME_BADGES,
  EDIT_OUTCOME_LABELS,
  EDIT_OUTCOME_TABS,
  editOutcomeSummary,
  type EditOutcome,
} from "@/integrations/google_ads/lib/edit-outcomes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import {
  CONVERSION_SETTING_TITLES,
  conversionValueText,
} from "@/integrations/google_ads/lib/update-conversions"
import type {
  ConversionOutcomeRow,
  UpdateConversionsResult,
} from "@/integrations/google_ads/lib/update-conversions-result"

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Conversion Action", width: 240 },
  { key: "setting", kind: "text", label: "Setting", width: 200 },
  { key: "before", kind: "text", label: "Before", width: 140 },
  { key: "after", kind: "text", label: "After", width: 140 },
  { key: "outcome", kind: "text", label: "Outcome", width: 110 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

function afterText(row: ConversionOutcomeRow, currency: string | null): string {
  return row.outcome === "failed" || !row.readBack
    ? "—"
    : conversionValueText(row.setting, row.after, currency)
}

function NameCell({ details, kind, name }: { details: string; kind: string; name: string }) {
  return (
    <span className="grid gap-0.5">
      <span className="wrap-anywhere whitespace-normal">{name}</span>
      {kind === "goal" ? <span className="text-muted-foreground text-xs">Account goal</span> : null}
      {details ? (
        <span className="text-destructive text-xs wrap-anywhere whitespace-normal">{details}</span>
      ) : null}
    </span>
  )
}

/** One row per conversion action or goal and setting, opening on the failures when there are any. */
export function UpdateConversionsOutcome({ result }: { result: UpdateConversionsResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.rows.map((row) => ({
        after: afterText(row, row.currency ?? result.currency),
        before: conversionValueText(row.setting, row.before, row.currency ?? result.currency),
        details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        kind: row.kind,
        name: row.name,
        outcome: EDIT_OUTCOME_LABELS[row.outcome],
        setting: CONVERSION_SETTING_TITLES[row.setting],
        token: row.outcome,
      })),
    [result]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-conversion-changes.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={EDIT_OUTCOME_BADGES[row["token"] as EditOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "name")
          return (
            <NameCell
              details={row["token"] === "failed" ? cellText(row["details"]) : ""}
              kind={cellText(row["kind"])}
              name={cellText(row["name"])}
            />
          )
        return null
      }}
      rowNoun={["change", "changes"]}
      rows={rows}
      summary={<span>{editOutcomeSummary(result.rows)}</span>}
      tabs={EDIT_OUTCOME_TABS}
    />
  )
}
