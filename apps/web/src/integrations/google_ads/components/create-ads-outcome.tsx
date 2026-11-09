// apps/web/src/integrations/google_ads/components/create-ads-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataTableTab } from "@/components/ui/data-table"
import { statusLabel } from "@/integrations/google_ads/lib/status-change"
import {
  createAdsSummary,
  reviewLabel,
  type CreateAdsResult,
  type CreatedAdOutcome,
} from "@/integrations/google_ads/lib/create-ads-result"

const COLUMNS: DataColumn[] = [
  { key: "adGroup", kind: "text", label: "Ad Group", width: 220 },
  { key: "campaign", kind: "text", label: "Campaign", hidden: true },
  { key: "headline", kind: "text", label: "Headline 1", width: 260 },
  { key: "status", kind: "text", label: "Status", width: 100 },
  { key: "review", kind: "text", label: "Review", width: 150 },
  { key: "outcome", kind: "text", label: "Outcome", width: 120 },
]

const OUTCOME_LABELS: Record<CreatedAdOutcome, string> = {
  created: "Created",
  failed: "Failed",
  unverified: "Unconfirmed",
}

const BADGES = { created: "success", failed: "destructive", unverified: "warning" } as const

function outcomeTab(id: CreatedAdOutcome | "all", label: string): DataTableTab {
  return {
    id,
    label,
    match: (row) => id === "all" || row["token"] === id,
    hideWhenEmpty: id !== "all",
  }
}

const TABS: DataTableTab[] = [
  outcomeTab("all", "All"),
  outcomeTab("created", "Created"),
  outcomeTab("failed", "Failed"),
  outcomeTab("unverified", "Unconfirmed"),
]

/** Each created ad with its status and Google's review; a rejected build says nothing was made. */
export function CreateAdsOutcome({ result }: { result: CreateAdsResult }) {
  const nothingCreated = result.ads.every((ad) => ad.outcome === "failed")
  const [tab, setTab] = useState(
    result.ads.some((ad) => ad.outcome === "failed") && !nothingCreated ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.ads.map((ad, index) => ({
        adGroup: ad.adGroupName,
        campaign: ad.campaignName ?? "—",
        details: ad.message ?? "",
        headline: ad.headline,
        key: String(index),
        outcome: OUTCOME_LABELS[ad.outcome],
        review: reviewLabel(ad),
        status: ad.outcome === "created" ? statusLabel(liveStatus(ad.status)) : "—",
        token: ad.outcome,
      })),
    [result.ads]
  )
  const reason = nothingCreated ? result.ads.find((ad) => ad.message)?.message : null
  return (
    <div className="grid gap-3">
      {nothingCreated ? (
        <p className="text-destructive text-sm wrap-anywhere">
          {reason ?? "Google rejected the request, so nothing was created."} Fix the ads and ask the
          agent to try again.
        </p>
      ) : null}
      <DataTable
        activeTab={tab}
        columns={COLUMNS}
        exportFilename="google-ads-created-ads.csv"
        onTabChange={setTab}
        pageSize={25}
        renderCell={(column, row) => {
          if (column.key === "outcome")
            return (
              <Badge variant={BADGES[row["token"] as CreatedAdOutcome]}>
                {String(row["outcome"])}
              </Badge>
            )
          if (column.key === "headline" && row["token"] !== "created" && !nothingCreated)
            return (
              <span className="grid gap-0.5">
                <span className="wrap-anywhere">{String(row["headline"])}</span>
                <span className="text-destructive text-xs wrap-anywhere">
                  {String(row["details"])}
                </span>
              </span>
            )
          return null
        }}
        rowNoun={["ad", "ads"]}
        rows={rows}
        summary={<span>{createAdsSummary(result)}</span>}
        tabs={TABS}
      />
    </div>
  )
}

function liveStatus(value: string | null) {
  return value === "ENABLED" || value === "PAUSED" || value === "REMOVED" ? value : null
}
