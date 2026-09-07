// apps/web/src/integrations/google_ads/components/campaign-link-outcome.tsx

import type { DataColumn } from "@/components/ui/data-table"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { countByKind } from "@/integrations/google_ads/lib/outcomes"

export type CampaignLinkCampaignOutcome = {
  campaignId: string
  campaignName: string
  errorCode: string | null
  externalRef: string | null
  message: string | null
  outcome: "already_linked" | "failed" | "linked" | "not_linked" | "unlinked"
}

export type CampaignLinkResult = {
  action: "LINK" | "UNLINK"
  campaigns: CampaignLinkCampaignOutcome[]
  negativeList: {
    externalId: string
    memberCount: number | null
    name: string
  }
}

const COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign" },
  { key: "campaignId", kind: "text", label: "Campaign ID" },
]
export function CampaignLinkApprovalSummary({
  campaignCount,
  listName,
}: {
  campaignCount: number
  listName: string
}) {
  return (
    <div className="bg-muted/50 grid gap-1 rounded-lg px-3 py-2.5">
      <p className="text-sm font-medium">{listName}</p>
      <p className="text-muted-foreground text-xs">
        {String(campaignCount)} {campaignCount === 1 ? "campaign" : "campaigns"} selected
      </p>
    </div>
  )
}

export function CampaignLinkOutcome({ result }: { result: CampaignLinkResult }) {
  const action = result.action
  const rows: GoogleAdsOutcomeRow[] = result.campaigns.map((campaign) => ({
    campaign: campaign.campaignName || campaign.campaignId,
    campaignId: campaign.campaignId,
    errorCode: campaign.errorCode ?? "",
    details: campaign.message ?? "",
    outcome: campaign.outcome,
  }))
  return (
    <div className="grid gap-3">
      <section
        aria-label="Negative keyword list summary"
        className="border-border bg-muted/35 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-lg border px-3 py-2.5"
      >
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{result.negativeList.name}</p>
          <p className="text-muted-foreground text-xs">List ID {result.negativeList.externalId}</p>
        </div>
        <p className="text-muted-foreground text-xs">
          {result.negativeList.memberCount === null
            ? "Member count unavailable"
            : `${String(result.negativeList.memberCount)} ${result.negativeList.memberCount === 1 ? "keyword" : "keywords"}`}
          {` · ${action === "LINK" ? "Apply" : "Remove"}`}
        </p>
      </section>
      <GoogleAdsOutcomeTable
        columns={COLUMNS}
        exportFilename={action === "LINK" ? "linked-campaigns.csv" : "unlinked-campaigns.csv"}
        outcomes={countByKind(rows)}
        rows={rows}
      />
    </div>
  )
}
