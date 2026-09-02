// apps/web/src/integrations/google_ads/lib/campaign-budgets.ts

import { formatCurrency, formatCurrencyAmount, titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const DIGITS_PATTERN = /^\d+$/
const CURRENCY_CODE_PATTERN = /^[A-Z]{3}$/

export type CampaignBudgetReference = {
  amountMicros: string | null
  budgetId: string
  campaignLabels: string[]
  currencyCode: string | null
  customerId: string
  deliveryMethod: string | null
  explicitlyShared: boolean | null
  label: string
  period: string | null
  referenceCount: number | null
  status: string | null
  totalAmountMicros: string | null
}

export type CampaignBudgetWithCurrency = CampaignBudgetReference & { currencyCode: string }

export type CampaignReference = {
  campaignId: string
  label: string
}

export function parseCampaignBudgetReference(value: unknown): CampaignBudgetReference | null {
  if (
    !isRecord(value) ||
    (value["entity_kind"] != null && value["entity_kind"] !== "google_ads_campaign_budget") ||
    typeof value["customer_id"] !== "string" ||
    !DIGITS_PATTERN.test(value["customer_id"]) ||
    typeof value["budget_id"] !== "string" ||
    !DIGITS_PATTERN.test(value["budget_id"]) ||
    typeof value["label"] !== "string"
  ) {
    return null
  }
  if (
    (value["amount_micros"] != null && exactMicros(value["amount_micros"]) === null) ||
    (value["total_amount_micros"] != null && exactMicros(value["total_amount_micros"]) === null) ||
    (value["reference_count"] != null &&
      (typeof value["reference_count"] !== "number" ||
        !Number.isSafeInteger(value["reference_count"]) ||
        value["reference_count"] < 0)) ||
    (value["campaign_labels"] != null &&
      (!Array.isArray(value["campaign_labels"]) ||
        !value["campaign_labels"].every((item) => typeof item === "string"))) ||
    (value["explicitly_shared"] != null && typeof value["explicitly_shared"] !== "boolean") ||
    (value["currency_code"] != null &&
      (typeof value["currency_code"] !== "string" ||
        !CURRENCY_CODE_PATTERN.test(value["currency_code"]))) ||
    (value["delivery_method"] != null && typeof value["delivery_method"] !== "string") ||
    (value["period"] != null && typeof value["period"] !== "string") ||
    (value["status"] != null && typeof value["status"] !== "string")
  ) {
    return null
  }
  return {
    amountMicros: exactMicros(value["amount_micros"]),
    budgetId: value["budget_id"],
    campaignLabels: value["campaign_labels"] ?? [],
    currencyCode: value["currency_code"] ?? null,
    customerId: value["customer_id"],
    deliveryMethod: value["delivery_method"] ?? null,
    explicitlyShared: value["explicitly_shared"] ?? null,
    label: value["label"].trim() || value["budget_id"],
    period: value["period"] ?? null,
    referenceCount: value["reference_count"] ?? null,
    status: value["status"] ?? null,
    totalAmountMicros: exactMicros(value["total_amount_micros"]),
  }
}

export function parseCampaignReference(value: unknown): CampaignReference | null {
  if (
    !isRecord(value) ||
    (value["entity_kind"] != null && value["entity_kind"] !== "google_ads_campaign") ||
    typeof value["campaign_id"] !== "string" ||
    !DIGITS_PATTERN.test(value["campaign_id"]) ||
    typeof value["label"] !== "string"
  ) {
    return null
  }
  return {
    campaignId: value["campaign_id"],
    label: value["label"].trim() || value["campaign_id"],
  }
}

export function formatDailyEstimate(amount: string, currencyCode: string): string {
  const numeric = Number(amount)
  return Number.isFinite(numeric)
    ? `${formatCurrency(numeric * 30.4, currencyCode, { maximumFractionDigits: 2 })} estimated per month`
    : "Monthly estimate unavailable"
}

export function formatCampaignBudgetAmount(budget: CampaignBudgetWithCurrency): string {
  const micros = budget.period === "DAILY" ? budget.amountMicros : budget.totalAmountMicros
  if (micros === null) {
    return "Amount unavailable"
  }
  const padded = micros.padStart(7, "0")
  const whole = padded.slice(0, -6)
  const fraction = padded.slice(-6).padStart(6, "0").replace(/0+$/, "")
  return formatCurrencyAmount(fraction ? `${whole}.${fraction}` : whole, budget.currencyCode)
}

export function campaignBudgetIdentity(budget: CampaignBudgetReference): string {
  return `${budget.customerId}:${budget.budgetId}`
}

function exactMicros(value: unknown): string | null {
  if (typeof value === "string" && DIGITS_PATTERN.test(value)) {
    return value.replace(/^0+(?=\d)/, "")
  }
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0) {
    return String(value)
  }
  return null
}

export function budgetPeriodLabel(period: string | null): string {
  return period === "DAILY"
    ? "Daily"
    : period === "CUSTOM_PERIOD"
      ? "Campaign total"
      : titleCaseToken(period ?? "", "Period unavailable")
}

export function deliveryMethodLabel(method: string | null): string {
  return titleCaseToken(method ?? "", "Delivery unavailable")
}

export function sharingLabel(shared: boolean | null): string {
  return shared === null ? "Sharing unavailable" : shared ? "Shared" : "Not shared"
}

export function linkedCampaignLabel(count: number | null): string {
  if (count === null) {
    return "Unavailable"
  }
  return `${String(count)} ${count === 1 ? "campaign" : "campaigns"}`
}
