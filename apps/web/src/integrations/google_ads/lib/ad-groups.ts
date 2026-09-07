// apps/web/src/integrations/google_ads/lib/ad-groups.ts

import { isRecord } from "@/lib/guards"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"

export type AdGroupReference = {
  adGroupId: string
  campaignId: string
  campaignLabel: string | null
  customerId: string
  label: string
}

export function parseAdGroupReference(value: unknown): AdGroupReference | null {
  if (!isRecord(value)) return null
  if (value["entity_kind"] != null && value["entity_kind"] !== "google_ads_ad_group") return null
  const customerId = googleAdsId(value["customer_id"])
  const campaignId = googleAdsId(value["campaign_id"])
  const adGroupId = googleAdsId(value["ad_group_id"])
  if (!customerId || !campaignId) return null
  if (!adGroupId || typeof value["label"] !== "string") return null
  return {
    adGroupId,
    campaignId,
    campaignLabel:
      typeof value["scope_label"] === "string" && value["scope_label"].trim()
        ? value["scope_label"]
        : null,
    customerId,
    label: value["label"].trim() || adGroupId,
  }
}
