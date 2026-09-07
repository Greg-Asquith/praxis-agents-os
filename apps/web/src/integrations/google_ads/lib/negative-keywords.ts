// apps/web/src/integrations/google_ads/lib/negative-keywords.ts

import { isRecord } from "@/lib/guards"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"

export function parseKeywordRow(
  value: unknown,
  allowAny = false
): { matchType: "EXACT" | "PHRASE" | "BROAD" | "ANY"; text: string } | null {
  if (
    !isRecord(value) ||
    typeof value["text"] !== "string" ||
    (value["match_type"] !== "EXACT" &&
      value["match_type"] !== "PHRASE" &&
      value["match_type"] !== "BROAD" &&
      (!allowAny || value["match_type"] !== "ANY"))
  ) {
    return null
  }
  return { matchType: value["match_type"], text: value["text"] }
}

export function parseNegativeListReference(value: unknown): {
  customerId: string
  listId: string
  label: string
} | null {
  if (
    !isRecord(value) ||
    (value["entity_kind"] != null && value["entity_kind"] !== "google_ads_shared_set")
  )
    return null
  const customerId = googleAdsId(value["customer_id"])
  const listId = googleAdsId(value["shared_set_id"])
  if (!customerId || !listId) return null
  return {
    customerId,
    listId,
    label:
      typeof value["label"] === "string" && value["label"].trim()
        ? value["label"].trim()
        : "Selected negative keyword list",
  }
}
