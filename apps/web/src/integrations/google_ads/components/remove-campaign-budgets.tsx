// apps/web/src/integrations/google_ads/components/remove-campaign-budgets.tsx

import type { DataColumn } from "@/components/ui/data-table"
import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import {
  budgetPeriodLabel,
  campaignBudgetIdentity,
  formatCampaignBudgetAmount,
  type CampaignBudgetWithCurrency,
} from "@/integrations/google_ads/lib/campaign-budgets"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { outcomeKind, outcomeLabel } from "@/integrations/google_ads/lib/outcomes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

export const OUTCOMES = ["removed", "failed", "unverified"] as const

type RemovalOutcome = (typeof OUTCOMES)[number]

export type RemovalArgs = {
  budgets: CampaignBudgetWithCurrency[]
}

export type RemovalResultRow = {
  errorCode: string | null
  message: string | null
  outcome: RemovalOutcome
  previousStatus: string
  reference: CampaignBudgetWithCurrency
  resultingStatus: string | null
}

export type RemovalResult = {
  counts: Record<RemovalOutcome, number>
  rows: RemovalResultRow[]
  samplesTruncated: boolean
}

export function renderRemovalApprovalSummary(args: RemovalArgs) {
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Campaign budgets selected for permanent removal"
      tone="destructive"
      countLine={approvalCountLine(args.budgets.length, "budget")}
    >
      <p className="text-muted-foreground text-xs">Each budget has zero linked campaigns.</p>
      {args.budgets.map((budget) => (
        <GoogleAdsEntityCard
          key={campaignBudgetIdentity(budget)}
          title={budget.label}
          meta={
            <>
              {budgetPeriodLabel(budget.period)} ·{" "}
              {budget.referenceCount === null
                ? "Unavailable"
                : approvalCountLine(budget.referenceCount, "campaign")}
            </>
          }
          trailing={formatCampaignBudgetAmount(budget)}
        />
      ))}
    </GoogleAdsApprovalSection>
  )
}

export function renderRemovalOutcomeTable(result: RemovalResult, columns: DataColumn[]) {
  const rows = result.rows.map<GoogleAdsOutcomeRow>((row) => ({
    amount: formatCampaignBudgetAmount(row.reference),
    budget: row.reference.label,
    budgetId: row.reference.budgetId,
    details: row.message ?? "",
    errorCode: row.errorCode,
    linkedCampaigns:
      row.reference.referenceCount === null
        ? "Unavailable"
        : approvalCountLine(row.reference.referenceCount, "campaign"),
    outcome: row.outcome,
    period: budgetPeriodLabel(row.reference.period),
    previousStatus: googleAdsTokenLabel(row.previousStatus, row.previousStatus),
    resultingStatus:
      row.resultingStatus === null
        ? "Unverified"
        : googleAdsTokenLabel(row.resultingStatus, row.resultingStatus),
  }))
  return (
    <GoogleAdsOutcomeTable
      columns={columns}
      exportFilename="removed-campaign-budgets.csv"
      outcomes={OUTCOMES.map((token) => ({
        kind: outcomeKind(token),
        label: outcomeLabel(token),
        count: result.counts[token],
      }))}
      rows={rows}
      truncated={result.samplesTruncated}
    />
  )
}
