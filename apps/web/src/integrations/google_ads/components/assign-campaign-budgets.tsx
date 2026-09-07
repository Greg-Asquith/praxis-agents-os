// apps/web/src/integrations/google_ads/components/assign-campaign-budgets.tsx

import type { DataColumn } from "@/components/ui/data-table"
import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsBeforeAfter } from "@/integrations/google_ads/components/before-after"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import {
  budgetPeriodLabel,
  type CampaignBudgetReference,
} from "@/integrations/google_ads/lib/campaign-budgets"
import type { CampaignReference } from "@/integrations/google_ads/lib/campaigns"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { outcomeKind, outcomeLabel } from "@/integrations/google_ads/lib/outcomes"

export const OUTCOMES = ["assigned", "already_set", "failed", "unverified"] as const

type AssignmentOutcome = (typeof OUTCOMES)[number]

export type AssignmentArgs = {
  campaigns: CampaignReference[]
  destination: CampaignBudgetReference
  routes: AssignmentRoute[]
}

export type AssignmentRoute = {
  campaign: CampaignReference
  destinationBudget: CampaignBudgetReference
  previousBudget: CampaignBudgetReference
}

export type AssignmentResultRow = {
  campaign: CampaignReference
  errorCode: string | null
  message: string | null
  outcome: AssignmentOutcome
  previousBudget: CampaignBudgetReference
  requestedBudget: CampaignBudgetReference
}

export type AssignmentResult = {
  counts: Record<AssignmentOutcome, number>
  destination: CampaignBudgetReference
  rows: AssignmentResultRow[]
  samplesTruncated: boolean
}

export function renderAssignmentApprovalSummary(args: AssignmentArgs) {
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Proposed campaign budget routes"
      title={`Destination budget: ${args.destination.label}`}
      countLine={approvalCountLine(args.routes.length, "campaign")}
    >
      {args.routes.map((route) => (
        <GoogleAdsEntityCard
          key={route.campaign.campaignId}
          title={route.campaign.label}
          trailing={
            <GoogleAdsBeforeAfter
              ariaLabel={`Budget for ${route.campaign.label}`}
              current={route.previousBudget.label}
              proposed={route.destinationBudget.label}
            />
          }
        />
      ))}
      <p className="text-muted-foreground text-xs">
        {budgetPeriodLabel(args.destination.period)} ·{" "}
        {args.destination.referenceCount === null
          ? "Unavailable"
          : approvalCountLine(args.destination.referenceCount, "campaign")}{" "}
        use this budget before the change
      </p>
    </GoogleAdsApprovalSection>
  )
}

export function renderAssignmentOutcomeTable(result: AssignmentResult, columns: DataColumn[]) {
  const rows = result.rows.map<GoogleAdsOutcomeRow>((row) => ({
    campaign: row.campaign.label,
    campaignId: row.campaign.campaignId,
    details: row.message ?? "",
    errorCode: row.errorCode,
    outcome: row.outcome,
    previousBudget: row.previousBudget.label,
    requestedBudget: row.requestedBudget.label,
  }))
  return (
    <div className="grid gap-3">
      <section className="border-border bg-muted/35 rounded-lg border px-3 py-2.5">
        <p className="text-muted-foreground text-xs">Destination budget</p>
        <div className="mt-0.5 flex min-w-0 flex-wrap items-baseline justify-between gap-2">
          <p className="truncate text-sm font-medium">{result.destination.label}</p>
          <p className="text-muted-foreground text-xs">
            {budgetPeriodLabel(result.destination.period)} ·{" "}
            {result.destination.referenceCount === null
              ? "Unavailable"
              : approvalCountLine(result.destination.referenceCount, "campaign")}
          </p>
        </div>
      </section>
      <GoogleAdsOutcomeTable
        columns={columns}
        exportFilename="campaign-budget-assignments.csv"
        outcomes={OUTCOMES.map((token) => ({
          kind: outcomeKind(token),
          label: outcomeLabel(token),
          count: result.counts[token],
        }))}
        rows={rows}
        truncated={result.samplesTruncated}
      />
    </div>
  )
}
