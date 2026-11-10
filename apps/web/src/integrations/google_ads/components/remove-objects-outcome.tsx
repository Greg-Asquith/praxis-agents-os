// apps/web/src/integrations/google_ads/components/remove-objects-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataTableTab } from "@/components/ui/data-table"
import { REMOVAL_KIND_TITLES } from "@/integrations/google_ads/lib/remove-objects"
import {
  REMOVAL_OUTCOME_BADGES,
  REMOVAL_OUTCOME_LABELS,
  removalResultSummary,
  type RemovalOutcome,
  type RemoveObjectsResult,
} from "@/integrations/google_ads/lib/remove-objects-result"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

const COLUMNS: DataColumn[] = [
  { key: "item", kind: "text", label: "Item", width: 260 },
  { key: "kind", kind: "text", label: "Kind", width: 120 },
  { key: "campaign", kind: "text", label: "Campaign", width: 200 },
  { key: "also", kind: "text", label: "Also Removed", width: 200 },
  { key: "outcome", kind: "text", label: "Outcome", width: 140 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

const TABS: DataTableTab[] = (
  ["all", "removed", "already_removed", "failed", "unverified"] as const
).map((id) => ({
  hideWhenEmpty: id === "already_removed" || id === "unverified",
  id,
  label: id === "all" ? "All" : REMOVAL_OUTCOME_LABELS[id],
  match: (row) => id === "all" || row["token"] === id,
}))

/** Every item's outcome, opening on the failures when there are any. */
export function RemoveObjectsOutcome({ result }: { result: RemoveObjectsResult }) {
  const [tab, setTab] = useState(
    result.objects.some((object) => object.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.objects.map((object) => ({
        also: object.alsoRemoved || "—",
        campaign: object.campaignName ?? "—",
        details: [object.message, object.errorCode ? googleAdsTokenLabel(object.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        item: object.name,
        kind: REMOVAL_KIND_TITLES[object.kind].one,
        outcome: REMOVAL_OUTCOME_LABELS[object.outcome],
        token: object.outcome,
      })),
    [result.objects]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-removals.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={REMOVAL_OUTCOME_BADGES[row["token"] as RemovalOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "item" && row["token"] === "failed" && cellText(row["details"]))
          return (
            <span className="grid gap-0.5">
              <span className="wrap-anywhere">{cellText(row["item"])}</span>
              <span className="text-destructive text-xs wrap-anywhere">
                {cellText(row["details"])}
              </span>
            </span>
          )
        return null
      }}
      rowNoun={["item", "items"]}
      rows={rows}
      summary={<span>{removalResultSummary(result)}</span>}
      tabs={TABS}
    />
  )
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
