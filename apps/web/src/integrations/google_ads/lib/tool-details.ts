// apps/web/src/integrations/google_ads/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { titleCaseToken } from "@/lib/format"
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
    ...(status ? [{ label: "New status", value: titleCaseToken(status, status) }] : []),
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
    const externalId = typeof item["external_id"] === "string" ? item["external_id"].trim() : ""
    const value = label || externalId
    return value ? [value] : []
  })
}

function stringArg(args: unknown, key: string): string | null {
  if (!isRecord(args) || typeof args[key] !== "string") {
    return null
  }
  const value = args[key].trim()
  return value || null
}
