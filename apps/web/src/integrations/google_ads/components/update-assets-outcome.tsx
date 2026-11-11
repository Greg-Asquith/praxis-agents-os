// apps/web/src/integrations/google_ads/components/update-assets-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { cellText } from "@/integrations/ads/lib/cell-text"
import { ASSET_TYPE_LABELS } from "@/integrations/google_ads/lib/new-assets"
import { TARGET_KIND_LABELS } from "@/integrations/google_ads/lib/update-assets"
import {
  ASSET_OUTCOME_BADGES,
  ASSET_OUTCOME_TABS,
  assetOutcomeLabel,
  assetOutcomeSummary,
  type AssetOutcome,
  type UpdateAssetsResult,
} from "@/integrations/google_ads/lib/update-assets-result"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

const COLUMNS: DataColumn[] = [
  { key: "asset", kind: "text", label: "Asset", width: 220 },
  { key: "type", kind: "text", label: "Type", width: 100 },
  { key: "target", kind: "text", label: "Where", width: 220 },
  { key: "outcome", kind: "text", label: "Outcome", width: 140 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

const ACTION_LABELS = { add: "Add", change: "Edit", remove: "Remove" } as const

/** One row per asset and target, opening on the failures when anything failed. */
export function UpdateAssetsOutcome({ result }: { result: UpdateAssetsResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.rows.map((row) => ({
        action: ACTION_LABELS[row.action],
        asset: row.assetLabel,
        details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        outcome: assetOutcomeLabel(row),
        target:
          row.targetName && row.targetKind
            ? `${row.targetName} · ${TARGET_KIND_LABELS[row.targetKind]}`
            : "Everywhere it's used",
        token: row.outcome,
        type: ASSET_TYPE_LABELS[row.assetType],
      })),
    [result.rows]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-assets.csv"
      onTabChange={setTab}
      pageSize={10}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={ASSET_OUTCOME_BADGES[row["token"] as AssetOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "asset")
          return (
            <span className="grid gap-0.5 whitespace-normal">
              <span className="wrap-anywhere">
                <span className="text-muted-foreground">{cellText(row["action"])}: </span>
                {cellText(row["asset"])}
              </span>
              {row["token"] === "failed" && row["details"] ? (
                <span className="text-destructive text-xs wrap-anywhere">
                  {cellText(row["details"])}
                </span>
              ) : null}
            </span>
          )
        return null
      }}
      rowNoun={["change", "changes"]}
      rows={rows}
      summary={<span>{assetOutcomeSummary(result.rows)}</span>}
      tabs={ASSET_OUTCOME_TABS}
    />
  )
}
