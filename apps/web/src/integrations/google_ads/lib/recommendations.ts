// apps/web/src/integrations/google_ads/lib/recommendations.ts

import { isRecord, isNullableString, isOneOf } from "@/lib/guards"

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
