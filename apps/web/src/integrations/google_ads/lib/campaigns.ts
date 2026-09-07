// apps/web/src/integrations/google_ads/lib/campaigns.ts

import { isRecord } from "@/lib/guards"
import { GOOGLE_ADS_ID_PATTERN } from "@/integrations/google_ads/lib/field-values"

export type CampaignReference = {
  campaignId: string
  label: string
}

export function parseCampaignReference(value: unknown): CampaignReference | null {
  if (
    !isRecord(value) ||
    (value["entity_kind"] != null && value["entity_kind"] !== "google_ads_campaign") ||
    typeof value["campaign_id"] !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(value["campaign_id"]) ||
    typeof value["label"] !== "string"
  ) {
    return null
  }
  return {
    campaignId: value["campaign_id"],
    label: value["label"].trim() || value["campaign_id"],
  }
}
