// apps/web/src/integrations/google_ads/components/create-keywords-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { canonicalMoney } from "@/integrations/google_ads/lib/campaign-bidding"
import {
  ADDITION_BADGES,
  ADDITION_LABELS,
  ADDITION_TABS,
  additionSummary,
  type CreateKeywordsResult,
  type KeywordAdditionOutcome,
} from "@/integrations/google_ads/lib/create-keywords-result"
import { MATCH_TYPE_LABELS } from "@/integrations/google_ads/lib/negative-keywords"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { formatCurrencyAmount } from "@/lib/format"

const COLUMNS: DataColumn[] = [
  { key: "keyword", kind: "text", label: "Keyword", width: 240 },
  { key: "match", kind: "text", label: "Match Type", width: 110 },
  { key: "ad_group", kind: "text", label: "Ad Group", width: 180 },
  { key: "campaign", kind: "text", label: "Campaign", width: 180, hidden: true },
  { key: "bid", kind: "text", label: "Bid", width: 120 },
  { key: "outcome", kind: "text", label: "Outcome", width: 120 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

/** One row per keyword, opening on the failures when there are any. */
export function CreateKeywordsOutcome({ result }: { result: CreateKeywordsResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.rows.map((row) => ({
        ad_group: row.adGroupName,
        bid: row.cpcBid
          ? result.currency
            ? formatCurrencyAmount(canonicalMoney(row.cpcBid), result.currency)
            : row.cpcBid
          : "Ad group's bid",
        campaign: row.campaignName,
        details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        keyword: row.text,
        match: MATCH_TYPE_LABELS[row.matchType],
        outcome: ADDITION_LABELS[row.outcome],
        token: row.outcome,
      })),
    [result]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-new-keywords.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={ADDITION_BADGES[row["token"] as KeywordAdditionOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "keyword")
          return (
            <span className="grid gap-0.5">
              <span className="wrap-anywhere whitespace-normal">{cellText(row["keyword"])}</span>
              {cellText(row["details"]) ? (
                <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
                  {cellText(row["details"])}
                </span>
              ) : null}
            </span>
          )
        return null
      }}
      rowNoun={["keyword", "keywords"]}
      rows={rows}
      summary={
        <span>
          {additionSummary(result.rows)}
          {result.status === "PAUSED" ? " · added paused" : ""}
        </span>
      }
      tabs={ADDITION_TABS}
    />
  )
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
