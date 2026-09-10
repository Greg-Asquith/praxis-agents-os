// apps/web/src/integrations/google_ads/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { stringArg } from "@/integrations/tool-details"
import { isRecord } from "@/lib/guards"

export function googleAdsReportDetails(args: unknown): FanOutDetail[] {
  const query = stringArg(args, "query")
  return query ? [{ label: "GAQL query", summary: false, value: query }] : []
}

export function googleAdsCampaignDetails(args: unknown): FanOutDetail[] {
  if (!isRecord(args)) {
    return []
  }
  const campaigns = campaignReferenceLabels(args)
  const status = stringArg(args, "status")
  return [
    ...(campaigns.length > 0 ? [{ label: "Campaigns", value: campaigns.join(", ") }] : []),
    ...(status ? [{ label: "New status", value: googleAdsTokenLabel(status, status) }] : []),
  ]
}

export function campaignReferenceLabels(args: unknown): string[] {
  if (!isRecord(args) || !Array.isArray(args["campaign_ids"])) {
    return []
  }
  return args["campaign_ids"].flatMap((item) => {
    if (!isRecord(item)) {
      return []
    }
    const label = typeof item["label"] === "string" ? item["label"].trim() : ""
    const campaignId = typeof item["campaign_id"] === "string" ? item["campaign_id"].trim() : ""
    const value = label || campaignId
    return value ? [value] : []
  })
}
