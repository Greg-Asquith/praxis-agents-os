// apps/web/src/integrations/google_ads/components/campaign-link-outcome.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"

export type CampaignLinkError = {
  campaignId: string
  errorCode: string
  message: string
}

export type CampaignLinkResult = {
  errors: CampaignLinkError[]
  succeededIds: string[]
  skippedIds: string[]
}

const COLUMNS: DataColumn[] = [
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

export function CampaignLinkOutcome({
  action,
  result,
}: {
  action: "LINK" | "UNLINK"
  result: CampaignLinkResult
}) {
  const successLabel = action === "LINK" ? "Linked" : "Unlinked"
  const skippedLabel = action === "LINK" ? "Already linked" : "Not linked"
  const rows: DataRow[] = [
    ...result.succeededIds.map((campaignId) => ({
      campaignId,
      outcome: successLabel,
    })),
    ...result.skippedIds.map((campaignId) => ({
      campaignId,
      outcome: skippedLabel,
    })),
    ...result.errors.map((error) => ({
      campaignId: error.campaignId || "Campaign",
      errorCode: error.errorCode,
      message: error.message,
      outcome: "Failed",
    })),
  ]
  return (
    <DataTable
      columns={result.errors.length > 0 ? ERROR_COLUMNS : COLUMNS}
      exportFilename={action === "LINK" ? "linked-campaigns.csv" : "unlinked-campaigns.csv"}
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label={successLabel}
            tone={result.succeededIds.length > 0 ? "success" : undefined}
            value={result.succeededIds.length}
          />
          <Stat
            label={skippedLabel}
            tone={result.skippedIds.length > 0 ? "warning" : undefined}
            value={result.skippedIds.length}
          />
          <Stat
            label="Failed"
            tone={result.errors.length > 0 ? "danger" : undefined}
            value={result.errors.length}
          />
        </StatGroup>
      }
      pageSize={25}
      rows={rows}
    />
  )
}
