// apps/web/src/integrations/google_analytics/lib/google-ads-links-model.ts

import { isDateTimeString, isNonNegativeInteger, isRecord } from "@/lib/guards"

const CUSTOMER_ID_PATTERN = /^\d{1,32}$/

export type GoogleAdsLink = {
  adsPersonalizationEnabled: boolean
  canManageClients: boolean
  createdAt: string | null
  customerId: string
}

export function parseGoogleAdsLinks(value: unknown): GoogleAdsLink[] | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["links"]) ||
    !isNonNegativeInteger(value["link_count"])
  ) {
    return null
  }
  const links: GoogleAdsLink[] = []
  for (const item of value["links"]) {
    const createdAt = item !== null && isRecord(item) ? item["created_at"] : undefined
    if (
      !isRecord(item) ||
      typeof item["customer_id"] !== "string" ||
      !CUSTOMER_ID_PATTERN.test(item["customer_id"]) ||
      typeof item["can_manage_clients"] !== "boolean" ||
      typeof item["ads_personalization_enabled"] !== "boolean" ||
      (createdAt !== null && !isDateTimeString(createdAt))
    ) {
      return null
    }
    links.push({
      adsPersonalizationEnabled: item["ads_personalization_enabled"],
      canManageClients: item["can_manage_clients"],
      createdAt: typeof createdAt === "string" ? createdAt : null,
      customerId: item["customer_id"],
    })
  }
  return value["link_count"] === links.length ? links : null
}
