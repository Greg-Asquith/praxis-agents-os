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
  const campaignIds = Array.isArray(args["campaign_ids"])
    ? args["campaign_ids"].filter((value): value is string => typeof value === "string")
    : []
  const status = stringArg(args, "status")
  return [
    ...(campaignIds.length > 0 ? [{ label: "Campaigns", value: campaignIds.join(", ") }] : []),
    ...(status ? [{ label: "New status", value: titleCaseToken(status, status) }] : []),
  ]
}

function stringArg(args: unknown, key: string): string | null {
  if (!isRecord(args) || typeof args[key] !== "string") {
    return null
  }
  const value = args[key].trim()
  return value || null
}
