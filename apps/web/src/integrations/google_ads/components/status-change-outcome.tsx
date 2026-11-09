// apps/web/src/integrations/google_ads/components/status-change-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataTableTab } from "@/components/ui/data-table"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { statusLabel, STATUS_KIND_TITLES } from "@/integrations/google_ads/lib/status-change"
import {
  outcomeLabel,
  resultSummary,
  type StatusChangeResult,
  type StatusOutcome,
} from "@/integrations/google_ads/lib/status-change-result"

const COLUMNS: DataColumn[] = [
  { key: "item", kind: "text", label: "Item", width: 260 },
  { key: "kind", kind: "text", label: "Kind", width: 110 },
  { key: "campaign", kind: "text", label: "Campaign", width: 200 },
  { key: "before", kind: "text", label: "Before", width: 90 },
  { key: "after", kind: "text", label: "After", width: 90 },
  { key: "outcome", kind: "text", label: "Outcome", width: 130 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

const BADGES = {
  updated: "success",
  already_set: "secondary",
  failed: "destructive",
  unverified: "warning",
} as const

function outcomeTab(id: StatusOutcome | "all", label: string, hideWhenEmpty = false): DataTableTab {
  return {
    id,
    label,
    match: (row) => id === "all" || row["token"] === id,
    hideWhenEmpty,
  }
}

const TABS: DataTableTab[] = [
  outcomeTab("all", "All"),
  outcomeTab("updated", "Changed"),
  outcomeTab("already_set", "Already Set"),
  outcomeTab("failed", "Failed"),
  outcomeTab("unverified", "Unconfirmed", true),
]

/** Every item's before, after, and outcome, opening on the failures when there are any. */
export function StatusChangeOutcome({ result }: { result: StatusChangeResult }) {
  const [tab, setTab] = useState(
    result.objects.some((object) => object.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.objects.map((object) => ({
        after: object.outcome === "failed" ? "—" : statusLabel(object.after),
        before: statusLabel(object.before),
        campaign: object.campaignName || "—",
        details: [object.message, object.errorCode ? googleAdsTokenLabel(object.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        item: object.name,
        kind: STATUS_KIND_TITLES[object.kind],
        outcome: outcomeLabel(object),
        token: object.outcome,
      })),
    [result.objects]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-status-changes.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={BADGES[row["token"] as StatusOutcome]}>
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
      summary={<span>{resultSummary(result)}</span>}
      tabs={TABS}
    />
  )
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
