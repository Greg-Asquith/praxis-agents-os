// apps/web/src/integrations/google_ads/presenters/create-campaign-budget.tsx

import {
  type CreateBudgetArgs,
  type CreateBudgetResult,
  renderCreateBudgetApprovalSummary,
  renderCreateBudgetOutcome,
} from "@/integrations/google_ads/components/create-campaign-budget"
import {
  budgetPeriodLabel,
  parseCampaignBudgetReference,
} from "@/integrations/google_ads/lib/campaign-budgets"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isNullableString, isRecord, parsePositiveDecimal } from "@/lib/guards"

export const googleAdsCreateCampaignBudgetPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_campaign_budget: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Create", object: "campaign budget", effect: "created" },
      approval: {
        parseArgs: createBudgetArgs,
        prompt: "Review the amount and delivery settings before creating this budget.",
        renderSummary: (value, fallback) =>
          renderCreateBudgetApprovalSummary(createBudgetArgs(value) ?? fallback),
      },
      details: (args) =>
        args
          ? [
              { label: "Budget", value: args.name },
              { label: "Period", value: budgetPeriodLabel(args.period) },
            ]
          : [],
      parseResult: createBudgetResult,
      renderOutcome: renderCreateBudgetOutcome,
    }),
  },
})

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
