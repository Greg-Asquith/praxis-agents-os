// apps/web/src/integrations/google_ads/lib/update-campaigns-result.ts

import { parseBidding, type BiddingContext } from "@/integrations/google_ads/lib/campaign-bidding"
import { parseGoals } from "@/integrations/google_ads/lib/campaign-goals"
import { isEditOutcome, type EditOutcome } from "@/integrations/google_ads/lib/edit-outcomes"
import type { UrlParameter } from "@/integrations/google_ads/lib/setting-changes"
import {
  CAMPAIGN_SETTINGS,
  type CampaignSetting,
  type SettingValue,
} from "@/integrations/google_ads/lib/update-campaigns"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type CampaignOutcomeRow = {
  after: SettingValue
  before: SettingValue
  campaignName: string
  errorCode: string | null
  message: string | null
  outcome: EditOutcome
  readBack: boolean
  setting: CampaignSetting
}

export type UpdateCampaignsResult = {
  accountId: string
  // The account currency and portfolio names that bidding values are written with.
  context: BiddingContext
  rows: CampaignOutcomeRow[]
}

function value(raw: unknown): SettingValue | undefined {
  if (raw === null || typeof raw === "string" || typeof raw === "boolean") return raw
  if (isRecord(raw)) return parseBidding(raw) ?? undefined
  if (!Array.isArray(raw)) return undefined
  // Video pages are addresses, goals are category and origin pairs, and custom parameters
  // are key and value pairs.
  if (raw.length > 0 && raw.every((item) => typeof item === "string")) return raw
  const goals = raw.length > 0 ? parseGoals(raw) : null
  if (goals) return goals
  const items: UrlParameter[] = []
  for (const item of raw) {
    if (!isRecord(item) || typeof item["key"] !== "string" || typeof item["value"] !== "string")
      return undefined
    items.push({ key: item["key"], value: item["value"] })
  }
  return items
}

function parseCampaign(raw: unknown): CampaignOutcomeRow[] | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["name"]) || !Array.isArray(raw["settings"]))
    return null
  const text = (key: string) => (typeof raw[key] === "string" ? raw[key] : null)
  const rows: CampaignOutcomeRow[] = []
  for (const item of raw["settings"]) {
    if (!isRecord(item)) return null
    const { outcome, setting } = item
    const before = value(item["before"])
    const after = value(item["after"])
    if (
      typeof setting !== "string" ||
      !(CAMPAIGN_SETTINGS as readonly string[]).includes(setting) ||
      !isEditOutcome(outcome) ||
      before === undefined ||
      after === undefined
    )
      return null
    rows.push({
      after,
      before,
      campaignName: raw["name"],
      errorCode: text("error_code"),
      message: text("message"),
      outcome,
      readBack: raw["read_back"] === true,
      setting: setting as CampaignSetting,
    })
  }
  return rows
}

export function parseUpdateCampaignsResult(raw: unknown): UpdateCampaignsResult | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["account_id"]) || !Array.isArray(raw["campaigns"]))
    return null
  const campaigns = raw["campaigns"].map(parseCampaign)
  if (campaigns.some((rows) => rows === null)) return null
  const portfolios = new Map<string, string>()
  if (Array.isArray(raw["portfolios"]))
    for (const item of raw["portfolios"])
      if (
        isRecord(item) &&
        typeof item["resource_name"] === "string" &&
        typeof item["name"] === "string"
      )
        portfolios.set(item["resource_name"], item["name"])
  return {
    accountId: raw["account_id"],
    context: { currency: isNonEmptyString(raw["currency"]) ? raw["currency"] : null, portfolios },
    rows: campaigns.flatMap((rows) => rows ?? []),
  }
}
