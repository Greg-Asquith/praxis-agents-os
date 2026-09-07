// apps/web/src/integrations/google_ads/components/create-campaign-budget.tsx

import { Badge } from "@/components/ui/badge"
import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import {
  budgetPeriodLabel,
  formatDailyEstimate,
  type CampaignBudgetReference,
} from "@/integrations/google_ads/lib/campaign-budgets"
import { approvalCountLine, GOOGLE_ADS_VERIFICATION } from "@/integrations/google_ads/lib/copy"
import { outcomeLabel } from "@/integrations/google_ads/lib/outcomes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { formatCurrencyAmount } from "@/lib/format"

export type CreateBudgetArgs = {
  accounts: { currencyCode: string; label: string }[]
  amount: string
  deliveryMethod: "ACCELERATED" | "STANDARD"
  explicitlyShared: boolean
  name: string
  period: "CUSTOM_PERIOD" | "DAILY"
}

export type CreateBudgetResult = CreateBudgetArgs & {
  currencyCode: string
  errorCode: string | null
  message: string | null
  outcome: "created" | "failed" | "unverified"
  reference: CampaignBudgetReference | null
}

export function renderCreateBudgetApprovalSummary(args: CreateBudgetArgs) {
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Proposed campaign budget"
      title={args.name}
      countLine={approvalCountLine(args.accounts.length, "account")}
    >
      {args.accounts.map((account) => (
        <GoogleAdsEntityCard
          key={`${account.label}:${account.currencyCode}`}
          title={account.label}
          meta={
            args.period === "DAILY" ? formatDailyEstimate(args.amount, account.currencyCode) : null
          }
          trailing={
            <>
              {formatCurrencyAmount(args.amount, account.currencyCode)}
              {args.period === "DAILY" ? " per day" : " total"}
            </>
          }
        />
      ))}
      <p className="text-muted-foreground text-xs">
        {budgetPeriodLabel(args.period)} ·{" "}
        {googleAdsTokenLabel(args.deliveryMethod, "Delivery unavailable")} ·{" "}
        {args.explicitlyShared ? "Shared" : "Not shared"}
      </p>
    </GoogleAdsApprovalSection>
  )
}

export function renderCreateBudgetOutcome(result: CreateBudgetResult) {
  const successful = result.outcome === "created"
  return (
    <section
      aria-label={`${result.name} campaign budget outcome`}
      className="border-border bg-muted/35 grid gap-3 rounded-lg border px-3 py-3"
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{result.name}</p>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {budgetPeriodLabel(result.period)} ·{" "}
            {googleAdsTokenLabel(result.deliveryMethod, "Delivery unavailable")} ·{" "}
            {result.explicitlyShared ? "Shared" : "Not shared"}
          </p>
        </div>
        <Badge
          variant={successful ? "success" : result.outcome === "failed" ? "destructive" : "warning"}
        >
          {outcomeLabel(result.outcome)}
        </Badge>
      </div>
      <div>
        <p className="text-xl font-semibold tracking-tight tabular-nums">
          {formatCurrencyAmount(result.amount, result.currencyCode)}
        </p>
        <p className="text-muted-foreground text-xs">
          {result.period === "DAILY"
            ? formatDailyEstimate(result.amount, result.currencyCode)
            : "Campaign total"}
        </p>
      </div>
      {successful && result.reference ? (
        <p className="text-muted-foreground text-xs">Budget ID {result.reference.budgetId}</p>
      ) : (
        <p
          className={
            result.outcome === "failed"
              ? "text-destructive text-sm"
              : "text-warning-foreground text-sm"
          }
        >
          {result.message ??
            (result.outcome === "failed"
              ? "Google Ads did not create this campaign budget."
              : GOOGLE_ADS_VERIFICATION)}
          {result.errorCode ? ` · ${result.errorCode}` : ""}
        </p>
      )}
    </section>
  )
}
