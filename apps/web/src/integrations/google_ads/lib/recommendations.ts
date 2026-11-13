// apps/web/src/integrations/google_ads/lib/recommendations.ts

import { roasPercent } from "@/integrations/google_ads/lib/campaign-bidding"
import { formatCurrency, microsToCurrencyUnits } from "@/lib/format"
import { isRecord, isNullableString, isOneOf } from "@/lib/guards"

const CHANGE_LABELS = {
  daily_budget: "Daily Budget",
  target_cpa: "Target CPA",
  target_roas: "Target ROAS",
} as const

// The setting a bid or budget recommendation changes: money in `currency` units, ROAS a ratio.
export type RecommendationChange = {
  after: number
  currency: string | null
  now: number
  setting: keyof typeof CHANGE_LABELS
}

export function parseRecommendationChange(value: unknown): RecommendationChange | null {
  if (!isRecord(value)) return null
  const { after, currency = null, now, setting } = value
  if (
    !isOneOf(new Set(Object.keys(CHANGE_LABELS)), setting) ||
    typeof now !== "number" ||
    !Number.isFinite(now) ||
    typeof after !== "number" ||
    !Number.isFinite(after) ||
    !isNullableString(currency)
  )
    return null
  return { after, currency, now, setting: setting as RecommendationChange["setting"] }
}

/** Google's recommended change with the card's own parameters, if any, as the value after. */
export function changeWithParameters(
  change: RecommendationChange,
  parameters: Record<string, string | number | null> | undefined
): RecommendationChange {
  const requested =
    parameters?.[
      change.setting === "daily_budget"
        ? "new_budget_amount_micros"
        : `${change.setting}_multiplier`
    ]
  if (typeof requested !== "number") return change
  // Google takes a multiplier on the current target, and a budget as a new amount.
  return {
    ...change,
    after:
      change.setting === "daily_budget" ? microsToCurrencyUnits(requested) : change.now * requested,
  }
}

export function recommendationChangeText(change: RecommendationChange): string {
  const text = (value: number) =>
    change.setting === "target_roas"
      ? `${roasPercent(value)}%`
      : formatCurrency(value, change.currency, { maximumFractionDigits: 2 })
  return `${CHANGE_LABELS[change.setting]}: ${text(change.now)} → ${text(change.after)}`
}

export function parseRecommendationReference(value: unknown): {
  customerId: string
  label: string
  recommendationType: string
  resourceName: string
} | null {
  if (
    !isRecord(value) ||
    value["entity_kind"] !== "google_ads_recommendation" ||
    typeof value["customer_id"] !== "string" ||
    !value["customer_id"].trim() ||
    typeof value["resource_name"] !== "string" ||
    !value["resource_name"].trim() ||
    typeof value["recommendation_type"] !== "string" ||
    !value["recommendation_type"].trim() ||
    typeof value["label"] !== "string" ||
    !value["label"].trim()
  )
    return null
  return {
    customerId: value["customer_id"],
    label: value["label"],
    recommendationType: value["recommendation_type"],
    resourceName: value["resource_name"],
  }
}

export function parseRecommendationOutcome<Token extends string>(
  value: unknown,
  outcomes: readonly Token[]
) {
  if (
    !isRecord(value) ||
    typeof value["recommendation_resource_name"] !== "string" ||
    typeof value["recommendation_type"] !== "string" ||
    typeof value["recommendation_label"] !== "string" ||
    !Array.isArray(value["affected_campaigns"]) ||
    !value["affected_campaigns"].every((item) => typeof item === "string") ||
    !isOneOf(new Set(outcomes), value["outcome"])
  )
    return null
  const message = value["message"] ?? null
  const errorCode = value["error_code"] ?? null
  if (!isNullableString(message) || !isNullableString(errorCode)) return null
  return {
    affectedCampaigns: value["affected_campaigns"],
    errorCode,
    label: value["recommendation_label"],
    message,
    outcome: value["outcome"],
    recommendationType: value["recommendation_type"],
    resourceName: value["recommendation_resource_name"],
  }
}
