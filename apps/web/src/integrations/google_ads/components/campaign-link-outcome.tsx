// apps/web/src/integrations/google_ads/components/campaign-link-outcome.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"

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
  { key: "outcome", kind: "status", label: "Outcome" },
]
const ERROR_COLUMNS: DataColumn[] = [
  ...COLUMNS,
  { key: "message", kind: "text", label: "Details" },
  { key: "errorCode", kind: "badge", label: "Error Code" },
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
  const successLabel = action === "LINK" ? "Linked" : "Unlinked"
  const skippedLabel = action === "LINK" ? "Already linked" : "Not linked"
  const {
    failed: failedCount,
    skipped: skippedCount,
    succeeded: succeededCount,
  } = campaignOutcomeCounts(result)
  const rows: DataRow[] = result.campaigns.map((campaign) => ({
    campaign: campaign.campaignName || campaign.campaignId,
    campaignId: campaign.campaignId,
    errorCode: campaign.errorCode ?? "",
    message: campaign.message ?? "",
    outcome: campaignOutcomeLabel(campaign.outcome),
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
      <DataTable
        columns={failedCount > 0 ? ERROR_COLUMNS : COLUMNS}
        exportFilename={action === "LINK" ? "linked-campaigns.csv" : "unlinked-campaigns.csv"}
        header={
          <StatGroup className="px-3 pt-2">
            <Stat
              label={successLabel}
              tone={succeededCount > 0 ? "success" : undefined}
              value={succeededCount}
            />
            <Stat
              label={skippedLabel}
              tone={skippedCount > 0 ? "warning" : undefined}
              value={skippedCount}
            />
            <Stat
              label="Failed"
              tone={failedCount > 0 ? "danger" : undefined}
              value={failedCount}
            />
          </StatGroup>
        }
        pageSize={25}
        rows={rows}
      />
    </div>
  )
}

function campaignOutcomeLabel(outcome: CampaignLinkCampaignOutcome["outcome"]) {
  switch (outcome) {
    case "already_linked":
      return "Already linked"
    case "linked":
      return "Linked"
    case "not_linked":
      return "Not linked"
    case "unlinked":
      return "Unlinked"
    case "failed":
      return "Failed"
  }
}

function campaignOutcomeCounts(result: CampaignLinkResult) {
  let failed = 0
  let skipped = 0
  let succeeded = 0
  for (const campaign of result.campaigns) {
    if (campaign.outcome === "failed") {
      failed += 1
    } else if (campaign.outcome === "already_linked" || campaign.outcome === "not_linked") {
      skipped += 1
    } else {
      succeeded += 1
    }
  }
  return { failed, skipped, succeeded }
}
