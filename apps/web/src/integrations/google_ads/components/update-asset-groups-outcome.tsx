// apps/web/src/integrations/google_ads/components/update-asset-groups-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { cellText } from "@/integrations/ads/lib/cell-text"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { GROUP_CHANGE_LABELS } from "@/integrations/google_ads/lib/update-asset-groups"
import {
  GROUP_OUTCOME_BADGES,
  GROUP_OUTCOME_LABELS,
  GROUP_OUTCOME_TABS,
  groupOutcomeSummary,
  type GroupOutcome,
  type UpdateAssetGroupsResult,
} from "@/integrations/google_ads/lib/update-asset-groups-result"

const COLUMNS: DataColumn[] = [
  { key: "group", kind: "text", label: "Asset Group", width: 200 },
  { key: "setting", kind: "text", label: "Setting", width: 140 },
  { key: "before", kind: "text", label: "Before", width: 180 },
  { key: "after", kind: "text", label: "After", width: 200 },
  { key: "outcome", kind: "text", label: "Outcome", width: 120 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

/** One row per change, opening on the failures when anything failed. */
export function UpdateAssetGroupsOutcome({ result }: { result: UpdateAssetGroupsResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.rows.map((row) => {
        const removed = row.action === "remove"
        return {
          // A setting with nothing in it is a URL option the change cleared.
          after: removed ? "" : row.item || "Cleared",
          before: row.action === "set" ? (row.before ?? "") : removed ? row.item : "",
          details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
            .filter(Boolean)
            .join(" · "),
          group: row.campaignName
            ? `${row.assetGroupName} · ${row.campaignName}`
            : row.assetGroupName,
          outcome: GROUP_OUTCOME_LABELS[row.outcome],
          setting: GROUP_CHANGE_LABELS[row.kind],
          token: row.outcome,
        }
      }),
    [result.rows]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-asset-groups.csv"
      onTabChange={setTab}
      pageSize={10}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={GROUP_OUTCOME_BADGES[row["token"] as GroupOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "after" && row["token"] === "failed" && row["details"])
          return (
            <span className="grid gap-0.5 whitespace-normal">
              <span className="wrap-anywhere">{cellText(row["after"])}</span>
              <span className="text-destructive text-xs wrap-anywhere">
                {cellText(row["details"])}
              </span>
            </span>
          )
        return null
      }}
      rowNoun={["change", "changes"]}
      rows={rows}
      summary={<span>{groupOutcomeSummary(result.rows)}</span>}
      tabs={GROUP_OUTCOME_TABS}
    />
  )
}
