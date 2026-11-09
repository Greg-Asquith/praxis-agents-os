// apps/web/src/integrations/google_ads/components/update-campaigns-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  EDIT_OUTCOME_BADGES,
  EDIT_OUTCOME_LABELS,
  EDIT_OUTCOME_TABS,
} from "@/integrations/google_ads/lib/edit-outcomes"
import type { BiddingContext } from "@/integrations/google_ads/lib/campaign-bidding"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { SETTING_TITLES, valueText } from "@/integrations/google_ads/lib/update-campaigns"
import {
  campaignsOutcomeSummary,
  type CampaignOutcome,
  type CampaignOutcomeRow,
  type UpdateCampaignsResult,
} from "@/integrations/google_ads/lib/update-campaigns-result"

const COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign", width: 220 },
  { key: "setting", kind: "text", label: "Setting", width: 140 },
  { key: "before", kind: "text", label: "Before", width: 150 },
  { key: "after", kind: "text", label: "After", width: 150 },
  { key: "outcome", kind: "text", label: "Outcome", width: 110 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

function afterText(row: CampaignOutcomeRow, context: BiddingContext): string {
  return row.outcome === "failed" || !row.readBack
    ? "—"
    : valueText(row.setting, row.after, context)
}

/** One row per campaign and setting, opening on the failures when there are any. */
export function UpdateCampaignsOutcome({ result }: { result: UpdateCampaignsResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.rows.map((row) => ({
        after: afterText(row, result.context),
        before: valueText(row.setting, row.before, result.context),
        campaign: row.campaignName,
        details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        outcome: EDIT_OUTCOME_LABELS[row.outcome],
        setting: SETTING_TITLES[row.setting],
        token: row.outcome,
      })),
    [result]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-campaign-changes.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={EDIT_OUTCOME_BADGES[row["token"] as CampaignOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "campaign" && row["token"] === "failed" && cellText(row["details"]))
          return (
            <span className="grid gap-0.5">
              <span className="wrap-anywhere whitespace-normal">{cellText(row["campaign"])}</span>
              <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
                {cellText(row["details"])}
              </span>
            </span>
          )
        if (column.key === "campaign" || column.key === "before" || column.key === "after")
          return (
            <span className="wrap-anywhere whitespace-normal">{cellText(row[column.key])}</span>
          )
        return null
      }}
      rowNoun={["change", "changes"]}
      rows={rows}
      summary={<span>{campaignsOutcomeSummary(result)}</span>}
      tabs={EDIT_OUTCOME_TABS}
    />
  )
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
