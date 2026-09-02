// apps/web/src/integrations/google_ads/presenters/create-campaign-budget.tsx

import { Badge } from "@/components/ui/badge"
import {
  budgetPeriodLabel,
  deliveryMethodLabel,
  formatDailyEstimate,
  parseCampaignBudgetReference,
  sharingLabel,
  type CampaignBudgetReference,
} from "@/integrations/google_ads/lib/campaign-budgets"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { formatCurrencyAmount } from "@/lib/format"
import { isNullableString, isRecord, parsePositiveDecimal } from "@/lib/guards"

type CreateBudgetArgs = {
  accounts: { currencyCode: string; label: string }[]
  amount: string
  deliveryMethod: "ACCELERATED" | "STANDARD"
  explicitlyShared: boolean
  name: string
  period: "CUSTOM_PERIOD" | "DAILY"
}

type CreateBudgetResult = CreateBudgetArgs & {
  currencyCode: string
  errorCode: string | null
  message: string | null
  outcome: "created" | "failed" | "unverified"
  reference: CampaignBudgetReference | null
}

export const googleAdsCreateCampaignBudgetPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-create-campaign-budget",
  variants: {
    google_ads_create_campaign_budget: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Create",
        label: "Create Google Ads Campaign Budget",
        parseArgs: createBudgetArgs,
        prompt: "Review the amount and delivery settings before creating this budget.",
        renderSummary: (value, fallback) =>
          renderCreateBudgetApprovalSummary(createBudgetArgs(value) ?? fallback),
        title: "Create Campaign Budget",
      },
      deniedDescription: "This campaign budget creation was declined. Nothing was created.",
      details: (args) =>
        args
          ? [
              { label: "Budget", value: args.name },
              { label: "Period", value: budgetPeriodLabel(args.period) },
            ]
          : [],
      emptyLabel: "No Google Ads accounts created a campaign budget.",
      failedDescription: "The creation did not finish. No campaign budget was confirmed.",
      heading: "Create Campaign Budget",
      malformedDescription:
        "The system couldn't verify this account's campaign budget result. Check Google Ads before taking further action.",
      parseResult: createBudgetResult,
      progressLabel: "Creating Google Ads campaign budget…",
      renderOutcome: renderCreateBudgetOutcome,
      resultAriaLabel: "Google Ads campaign budget creation results",
      resultFailure:
        "The system couldn't verify the campaign budget creation. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads campaign budget creation",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads created this campaign budget. Check Google Ads before retrying.",
      waitingLabel: "Waiting for campaign budget approval…",
    }),
  },
})

function renderCreateBudgetApprovalSummary(args: CreateBudgetArgs) {
  return (
    <section
      aria-label="Proposed campaign budget"
      className="border-border bg-muted/35 grid gap-2 rounded-lg border px-3 py-2.5"
    >
      <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
        <p className="truncate text-sm font-medium">{args.name}</p>
      </div>
      <div className="grid gap-1 sm:grid-cols-2">
        {args.accounts.map((account) => (
          <div
            className="bg-card rounded-md border px-2.5 py-2"
            key={`${account.label}:${account.currencyCode}`}
          >
            <p className="truncate text-xs font-medium">{account.label}</p>
            <p className="mt-0.5 text-sm font-semibold tabular-nums">
              {formatCurrencyAmount(args.amount, account.currencyCode)}
              {args.period === "DAILY" ? " per day" : " total"}
            </p>
            {args.period === "DAILY" ? (
              <p className="text-muted-foreground mt-0.5 text-xs">
                {formatDailyEstimate(args.amount, account.currencyCode)}
              </p>
            ) : null}
          </div>
        ))}
      </div>
      <p className="text-muted-foreground text-xs">
        {budgetPeriodLabel(args.period)} · {deliveryMethodLabel(args.deliveryMethod)} ·{" "}
        {sharingLabel(args.explicitlyShared)}
      </p>
    </section>
  )
}

function renderCreateBudgetOutcome(result: CreateBudgetResult) {
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
            {budgetPeriodLabel(result.period)} · {deliveryMethodLabel(result.deliveryMethod)} ·{" "}
            {sharingLabel(result.explicitlyShared)}
          </p>
        </div>
        <Badge
          variant={successful ? "success" : result.outcome === "failed" ? "destructive" : "warning"}
        >
          {successful ? "Created" : result.outcome === "failed" ? "Failed" : "Unverified"}
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
              : "Check Google Ads to confirm whether the campaign budget exists.")}
          {result.errorCode ? ` · ${result.errorCode}` : ""}
        </p>
      )}
    </section>
  )
}

function createBudgetArgs(value: unknown): CreateBudgetArgs | null {
  if (
    !isRecord(value) ||
    typeof value["name"] !== "string" ||
    !value["name"].trim() ||
    !Array.isArray(value["_account_currencies"]) ||
    value["_account_currencies"].length === 0 ||
    typeof value["explicitly_shared"] !== "boolean" ||
    (value["delivery_method"] !== "STANDARD" && value["delivery_method"] !== "ACCELERATED") ||
    !isRecord(value["amount"])
  ) {
    return null
  }
  const dailyAmount = parsePositiveDecimal(value["amount"]["daily_amount"])
  const totalAmount = parsePositiveDecimal(value["amount"]["total_amount"])
  if ((dailyAmount === null) === (totalAmount === null)) {
    return null
  }
  if (
    totalAmount !== null &&
    (value["explicitly_shared"] || value["delivery_method"] === "ACCELERATED")
  ) {
    return null
  }
  const accounts: { currencyCode: string; label: string }[] = []
  for (const account of value["_account_currencies"]) {
    if (
      !isRecord(account) ||
      typeof account["label"] !== "string" ||
      !account["label"].trim() ||
      typeof account["currency_code"] !== "string" ||
      !/^[A-Z]{3}$/.test(account["currency_code"])
    ) {
      return null
    }
    accounts.push({ currencyCode: account["currency_code"], label: account["label"].trim() })
  }
  return {
    accounts,
    amount: dailyAmount ?? totalAmount ?? "",
    deliveryMethod: value["delivery_method"],
    explicitlyShared: value["explicitly_shared"],
    name: value["name"].trim(),
    period: dailyAmount === null ? "CUSTOM_PERIOD" : "DAILY",
  }
}

function createBudgetResult(value: unknown): CreateBudgetResult | null {
  if (
    !isRecord(value) ||
    typeof value["name"] !== "string" ||
    (value["period"] !== "DAILY" && value["period"] !== "CUSTOM_PERIOD") ||
    (value["delivery_method"] !== "STANDARD" && value["delivery_method"] !== "ACCELERATED") ||
    typeof value["explicitly_shared"] !== "boolean" ||
    typeof value["currency_code"] !== "string" ||
    !/^[A-Z]{3}$/.test(value["currency_code"]) ||
    (value["outcome"] !== "created" &&
      value["outcome"] !== "failed" &&
      value["outcome"] !== "unverified")
  ) {
    return null
  }
  const amount = parsePositiveDecimal(value["amount"])
  const reference =
    value["reference"] === null || value["reference"] === undefined
      ? null
      : parseCampaignBudgetReference(value["reference"])
  if (
    amount === null ||
    !isNullableString(value["error_code"] ?? null) ||
    !isNullableString(value["message"] ?? null) ||
    (value["outcome"] === "created" && reference === null)
  ) {
    return null
  }
  return {
    accounts: [],
    amount,
    currencyCode: value["currency_code"],
    deliveryMethod: value["delivery_method"],
    errorCode: typeof value["error_code"] === "string" ? value["error_code"] : null,
    explicitlyShared: value["explicitly_shared"],
    message: typeof value["message"] === "string" ? value["message"] : null,
    name: value["name"].trim() || "Campaign budget",
    outcome: value["outcome"],
    period: value["period"],
    reference,
  }
}
