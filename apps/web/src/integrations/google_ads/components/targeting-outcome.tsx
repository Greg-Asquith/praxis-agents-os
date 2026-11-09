// apps/web/src/integrations/google_ads/components/targeting-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataTableTab } from "@/components/ui/data-table"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import {
  rowChange,
  SETTING_TITLES,
  targetingOutcomeSummary,
  type TargetingOutcome,
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

const LABELS: Record<TargetingOutcome, string> = {
  already_set: "Already Set",
  failed: "Failed",
  unverified: "Unconfirmed",
  updated: "Changed",
}

const BADGES = {
  already_set: "secondary",
  failed: "destructive",
  unverified: "warning",
  updated: "success",
} as const

function outcomeTab(id: TargetingOutcome | "all", hideWhenEmpty = false): DataTableTab {
  return {
    hideWhenEmpty,
    id,
    label: id === "all" ? "All" : LABELS[id],
    match: (row) => id === "all" || row["token"] === id,
  }
}

const TABS: DataTableTab[] = [
  outcomeTab("all"),
  outcomeTab("updated"),
  outcomeTab("already_set"),
  outcomeTab("failed"),
  outcomeTab("unverified", true),
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
          outcome: LABELS[row.outcome],
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
            <Badge variant={BADGES[row["token"] as TargetingOutcome]}>
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
      summary={<span>{targetingOutcomeSummary(result)}</span>}
      tabs={TABS}
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

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
