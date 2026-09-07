// apps/web/src/integrations/google_ads/components/update-campaign-budget-amounts.tsx

import type { DataColumn, DataRow } from "@/components/ui/data-table"
import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsBeforeAfter } from "@/integrations/google_ads/components/before-after"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import {
  budgetPeriodLabel,
  campaignBudgetIdentity,
  formatCampaignBudgetAmount,
  formatDailyEstimate,
  type CampaignBudgetWithCurrency,
} from "@/integrations/google_ads/lib/campaign-budgets"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { outcomeDetails, outcomeKind, outcomeLabel } from "@/integrations/google_ads/lib/outcomes"
import { formatCurrencyAmount, formatPercentageChange } from "@/lib/format"

export const OUTCOMES = ["updated", "already_set", "failed", "unverified"] as const

export type BudgetAmountOutcome = (typeof OUTCOMES)[number]

export type BudgetAmountUpdate = {
  amount: string
  budget: CampaignBudgetWithCurrency
}

export type UpdateBudgetArgs = {
  updates: BudgetAmountUpdate[]
}

export type BudgetAmountResult = {
  campaignLabelCount: number
  campaignLabelsTruncated: boolean
  errorCode: string | null
  message: string | null
  outcome: BudgetAmountOutcome
  previousAmount: string
  reference: CampaignBudgetWithCurrency
  requestedAmount: string
}

export type UpdateBudgetResult = {
  campaignLabelsTruncated: boolean
  counts: Record<BudgetAmountOutcome, number>
  rows: BudgetAmountResult[]
  samplesTruncated: boolean
}

export function renderUpdateBudgetApprovalSummary(args: UpdateBudgetArgs) {
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Proposed campaign budget amounts"
      countLine={approvalCountLine(args.updates.length, "budget")}
    >
      {args.updates.map((update) => (
        <GoogleAdsEntityCard
          key={campaignBudgetIdentity(update.budget)}
          title={update.budget.label}
          meta={
            <>
              {budgetPeriodLabel(update.budget.period)} ·{" "}
              {update.budget.referenceCount === null
                ? "Unavailable"
                : approvalCountLine(update.budget.referenceCount, "campaign")}
            </>
          }
          trailing={
            <GoogleAdsBeforeAfter
              ariaLabel={`${formatCampaignBudgetAmount(update.budget)} before, ${formatCurrencyAmount(update.amount, update.budget.currencyCode)} after`}
              current={formatCampaignBudgetAmount(update.budget)}
              proposed={formatCurrencyAmount(update.amount, update.budget.currencyCode)}
            />
          }
        />
      ))}
    </GoogleAdsApprovalSection>
  )
}

export function renderUpdateBudgetOutcome(result: UpdateBudgetResult, columns: DataColumn[]) {
  const rows = result.rows.map<GoogleAdsOutcomeRow>((row) => ({
    budget: row.reference.label,
    change: formatPercentageChange(Number(row.previousAmount), Number(row.requestedAmount)),
    details: outcomeDetails(
      row.message,
      null,
      row.reference.period === "DAILY"
        ? `Requested: ${formatDailyEstimate(row.requestedAmount, row.reference.currencyCode)}`
        : null
    ),
    errorCode: row.errorCode,
    linkedCampaigns: approvalCountLine(
      row.reference.referenceCount ?? row.campaignLabelCount,
      "campaign"
    ),
    outcome: row.outcome,
    period: budgetPeriodLabel(row.reference.period),
    previous: formatCurrencyAmount(row.previousAmount, row.reference.currencyCode),
    previousRaw: row.previousAmount,
    requested: formatCurrencyAmount(row.requestedAmount, row.reference.currencyCode),
    requestedRaw: row.requestedAmount,
    after:
      row.outcome === "updated" || row.outcome === "already_set"
        ? formatCurrencyAmount(row.requestedAmount, row.reference.currencyCode)
        : "Unconfirmed",
  }))
  return (
    <div className="grid gap-2">
      <GoogleAdsOutcomeTable
        columns={columns}
        exportFilename="campaign-budget-amounts.csv"
        outcomes={OUTCOMES.map((token) => ({
          kind: outcomeKind(token),
          label: outcomeLabel(token),
          count: result.counts[token],
        }))}
        renderCell={renderBudgetChangeCell}
        rows={rows}
        truncated={result.samplesTruncated}
      />
      {result.campaignLabelsTruncated ? (
        <p className="text-muted-foreground text-xs">
          Some linked campaign names are omitted from the retained result.
        </p>
      ) : null}
    </div>
  )
}

function renderBudgetChangeCell(column: DataColumn, row: DataRow) {
  if (column.key !== "change") {
    return null
  }
  const previous = Number(row["previousRaw"])
  const requested = Number(row["requestedRaw"])
  const change = typeof row["change"] === "string" ? row["change"] : "—"
  if (!Number.isFinite(previous) || !Number.isFinite(requested) || previous <= 0) {
    return <span>{change}</span>
  }
  const maximum = Math.max(previous, requested)
  return (
    <div aria-label={`Requested change: ${change} from the previous amount`} className="grid gap-1">
      <div className="bg-muted h-1.5 overflow-hidden rounded-full">
        <div
          className="bg-muted-foreground/45 h-full rounded-full"
          style={{ width: `${String(Math.max(3, (previous / maximum) * 100))}%` }}
        />
      </div>
      <div className="bg-muted h-1.5 overflow-hidden rounded-full">
        <div
          className={
            requested >= previous
              ? "bg-success h-full rounded-full"
              : "bg-warning h-full rounded-full"
          }
          style={{ width: `${String(Math.max(3, (requested / maximum) * 100))}%` }}
        />
      </div>
      <span className="text-muted-foreground text-xs tabular-nums">{change}</span>
    </div>
  )
}
