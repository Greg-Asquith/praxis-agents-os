// apps/web/src/integrations/meta_ads/lib/ads-manager-link.ts

export type MetaAdsObjectType = "campaign" | "adset" | "ad"

const MANAGE_PAGES = { campaign: "campaigns", adset: "adsets", ad: "ads" } as const
const SELECTION_PARAMS = {
  campaign: "selected_campaign_ids",
  adset: "selected_adset_ids",
  ad: "selected_ad_ids",
} as const

// Single place for the Ads Manager deep-link format; unconfirmed against live Meta.
export function adsManagerObjectUrl(
  type: MetaAdsObjectType,
  accountId: string,
  objectId: string
): string | null {
  if (!/^\d+$/.test(accountId) || !/^\d+$/.test(objectId)) return null
  return `https://adsmanager.facebook.com/adsmanager/manage/${MANAGE_PAGES[type]}?act=${accountId}&${SELECTION_PARAMS[type]}=${objectId}`
}
