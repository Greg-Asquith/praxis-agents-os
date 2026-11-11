// apps/web/src/integrations/google_ads/components/update-ad-groups-outcome.tsx

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
  AD_GROUP_SETTING_TITLES,
  adGroupValueText,
} from "@/integrations/google_ads/lib/update-ad-groups"
import type {
  AdGroupOutcomeRow,
  UpdateAdGroupsResult,
} from "@/integrations/google_ads/lib/update-ad-groups-result"

const COLUMNS: DataColumn[] = [
  { key: "ad_group", kind: "text", label: "Ad Group", width: 220 },
  { key: "campaign", kind: "text", label: "Campaign", width: 180, hidden: true },
  { key: "setting", kind: "text", label: "Setting", width: 140 },
  { key: "before", kind: "text", label: "Before", width: 150 },
  { key: "after", kind: "text", label: "After", width: 150 },
  { key: "outcome", kind: "text", label: "Outcome", width: 110 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

function afterText(row: AdGroupOutcomeRow, currency: string | null): string {
  return row.outcome === "failed" || !row.readBack
    ? "—"
    : adGroupValueText(row.setting, row.after, currency)
}

/** One row per ad group and setting, opening on the failures when there are any. */
export function UpdateAdGroupsOutcome({ result }: { result: UpdateAdGroupsResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.rows.map((row) => ({
        ad_group: row.adGroupName,
        after: afterText(row, result.currency),
        before: adGroupValueText(row.setting, row.before, result.currency),
        campaign: row.campaignName,
        details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        outcome: EDIT_OUTCOME_LABELS[row.outcome],
        setting: AD_GROUP_SETTING_TITLES[row.setting],
        token: row.outcome,
      })),
    [result]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-ad-group-changes.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={EDIT_OUTCOME_BADGES[row["token"] as EditOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "ad_group" && row["token"] === "failed" && cellText(row["details"]))
          return (
            <span className="grid gap-0.5">
              <span className="wrap-anywhere whitespace-normal">{cellText(row["ad_group"])}</span>
              <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
                {cellText(row["details"])}
              </span>
            </span>
          )
        if (column.key === "ad_group" || column.key === "before" || column.key === "after")
          return (
            <span className="wrap-anywhere whitespace-normal">{cellText(row[column.key])}</span>
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
