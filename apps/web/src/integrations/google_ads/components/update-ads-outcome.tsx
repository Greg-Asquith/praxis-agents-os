// apps/web/src/integrations/google_ads/components/update-ads-outcome.tsx

import { useMemo, useState, type ComponentProps } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  EDIT_OUTCOME_BADGES,
  EDIT_OUTCOME_LABELS,
  EDIT_OUTCOME_TABS,
} from "@/integrations/google_ads/lib/edit-outcomes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import {
  adsOutcomeSummary,
  changeLines,
  inReview,
  type AdOutcomeRow,
  type UpdateAdsResult,
} from "@/integrations/google_ads/lib/update-ads-result"

const COLUMNS: DataColumn[] = [
  { key: "ad", kind: "text", label: "Ad", width: 220 },
  { key: "adGroup", kind: "text", label: "Ad Group", width: 160 },
  { key: "before", kind: "text", label: "Before", width: 200 },
  { key: "after", kind: "text", label: "After", width: 200 },
  { key: "outcome", kind: "text", label: "Outcome", width: 110 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

type BadgeVariant = NonNullable<ComponentProps<typeof Badge>["variant"]>

function outcomeBadge(row: AdOutcomeRow): { label: string; variant: BadgeVariant } {
  if (row.approvalStatus === "DISAPPROVED") return { label: "Disapproved", variant: "destructive" }
  if (inReview(row)) return { label: "In Review", variant: "warning" }
  return { label: EDIT_OUTCOME_LABELS[row.outcome], variant: EDIT_OUTCOME_BADGES[row.outcome] }
}

/** One row per ad with what came out and went in, opening on the failures when there are any. */
export function UpdateAdsOutcome({ result }: { result: UpdateAdsResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const badges = useMemo(() => result.rows.map(outcomeBadge), [result])
  const rows = useMemo(
    () =>
      result.rows.map((row, index) => {
        const lines = changeLines(row.before, row.after ?? row.requested)
        return {
          ad: row.name,
          adGroup: row.adGroupName,
          after: row.outcome === "failed" ? "—" : lines.after,
          before: lines.before,
          details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
            .filter(Boolean)
            .join(" · "),
          index: String(index),
          outcome: badges[index]?.label ?? "",
          token: row.outcome,
        }
      }),
    [badges, result]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-ad-changes.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome") {
          const badge = badges[Number(row["index"])]
          return badge ? <Badge variant={badge.variant}>{badge.label}</Badge> : null
        }
        if (column.key === "ad" && row["token"] === "failed" && cellText(row["details"]))
          return (
            <span className="grid gap-0.5">
              <span className="wrap-anywhere whitespace-normal">{cellText(row["ad"])}</span>
              <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
                {cellText(row["details"])}
              </span>
            </span>
          )
        if (["ad", "adGroup", "before", "after"].includes(column.key))
          return (
            <span className="wrap-anywhere whitespace-normal">{cellText(row[column.key])}</span>
          )
        return null
      }}
      rowNoun={["ad", "ads"]}
      rows={rows}
      summary={<span>{adsOutcomeSummary(result)}</span>}
      tabs={EDIT_OUTCOME_TABS}
    />
  )
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
