// apps/web/src/integrations/google_ads/components/targeting-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { cellText } from "@/integrations/ads/lib/cell-text"
import {
  EDIT_OUTCOME_BADGES,
  EDIT_OUTCOME_LABELS,
  EDIT_OUTCOME_TABS,
  type EditOutcome,
  editOutcomeSummary,
} from "@/integrations/google_ads/lib/edit-outcomes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import {
  rowChange,
  SETTING_TITLES,
  type UpdateTargetingResult,
} from "@/integrations/google_ads/lib/update-targeting-result"

const COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign", width: 220 },
  { key: "setting", kind: "text", label: "Setting", width: 110 },
  { key: "before", kind: "text", label: "Before", width: 130 },
  { key: "after", kind: "text", label: "After", width: 170 },
  { key: "outcome", kind: "text", label: "Outcome", width: 110 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

/** One row per campaign and setting, opening on the failures when there are any. */
export function TargetingOutcomeTable({ result }: { result: UpdateTargetingResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.rows.map((row) => {
        const { after, before } = rowChange(row)
        return {
          after: row.outcome === "failed" ? "—" : after,
          before,
          campaign: row.campaignName || "—",
          details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
            .filter(Boolean)
            .join(" · "),
          outcome: EDIT_OUTCOME_LABELS[row.outcome],
          setting: SETTING_TITLES[row.setting],
          token: row.outcome,
        }
      }),
    [result.rows]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-targeting-changes.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={EDIT_OUTCOME_BADGES[row["token"] as EditOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "campaign" && row["token"] === "failed" && row["details"])
          return (
            <FailedCampaign details={cellText(row["details"])} name={cellText(row["campaign"])} />
          )
        if (column.key === "campaign" || column.key === "before" || column.key === "after")
          return (
            <span className="wrap-anywhere whitespace-normal">{cellText(row[column.key])}</span>
          )
        return null
      }}
      rowNoun={["row", "rows"]}
      rows={rows}
      summary={<span>{editOutcomeSummary(result.rows, { weight: (row) => row.count })}</span>}
      tabs={EDIT_OUTCOME_TABS}
    />
  )
}

function FailedCampaign({ details, name }: { details: string; name: string }) {
  return (
    <span className="grid gap-0.5">
      <span className="wrap-anywhere">{name}</span>
      <span className="text-destructive text-xs wrap-anywhere">{details}</span>
    </span>
  )
}
