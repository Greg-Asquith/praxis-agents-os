// apps/web/src/integrations/google_ads/components/search-terms-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { MATCH_TYPE_LABELS } from "@/integrations/google_ads/lib/negative-keywords"
import { ACTION_LABELS } from "@/integrations/google_ads/lib/search-terms"
import {
  SEARCH_TERM_OUTCOME_TABS,
  SEARCH_TERM_TOKEN_BADGES,
  SEARCH_TERM_TOKEN_LABELS,
  searchTermOutcomeSummary,
  searchTermToken,
  type OptimiseSearchTermsResult,
  type SearchTermToken,
} from "@/integrations/google_ads/lib/search-terms-result"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

/** One table with the outcome per search term; it opens on failures when there are any. */
export function SearchTermsOutcome({ result }: { result: OptimiseSearchTermsResult }) {
  const { rows } = result
  const [tab, setTab] = useState(rows.some((row) => row.outcome === "failed") ? "failed" : "all")
  const columns = useMemo<DataColumn[]>(
    () => [
      { key: "term", kind: "text", label: "Search Term", width: 240 },
      { key: "action", kind: "text", label: "Action", width: 120 },
      { key: "match", kind: "text", label: "Match Type", width: 110 },
      { key: "target", kind: "text", label: "Target", width: 200 },
      {
        key: "cost",
        kind: "currency",
        label: "Cost",
        align: "right",
        currencyCode: result.currency,
        isMetric: true,
        unit: "currency-units",
      },
      { key: "outcome", kind: "text", label: "Outcome", width: 140 },
      { key: "details", kind: "text", label: "Details", hidden: true },
    ],
    [result.currency]
  )
  const tableRows = useMemo(
    () =>
      rows.map((row) => {
        const token = searchTermToken(row)
        return {
          action: ACTION_LABELS[row.action],
          cost: row.cost,
          details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
            .filter(Boolean)
            .join(" · "),
          match: MATCH_TYPE_LABELS[row.matchType],
          outcome: SEARCH_TERM_TOKEN_LABELS[token],
          target: row.targetName,
          term: row.term,
          token,
        }
      }),
    [rows]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={columns}
      exportFilename="google-ads-search-terms.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={SEARCH_TERM_TOKEN_BADGES[row["token"] as SearchTermToken]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "term")
          return (
            <span className="grid gap-0.5 whitespace-normal">
              <span className="wrap-anywhere">{cellText(row["term"])}</span>
              {row["token"] === "failed" && row["details"] ? (
                <span className="text-destructive text-xs wrap-anywhere">
                  {cellText(row["details"])}
                </span>
              ) : null}
            </span>
          )
        return null
      }}
      rowNoun={["search term", "search terms"]}
      rows={tableRows}
      summary={<span>{searchTermOutcomeSummary(rows)}</span>}
      tabs={SEARCH_TERM_OUTCOME_TABS}
    />
  )
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
