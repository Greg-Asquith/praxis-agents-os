// apps/web/src/integrations/google_ads/lib/recommendations.ts

import { isRecord } from "@/lib/guards"

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
