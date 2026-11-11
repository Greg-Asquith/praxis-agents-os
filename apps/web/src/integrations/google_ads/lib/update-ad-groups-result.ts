// apps/web/src/integrations/google_ads/lib/update-ad-groups-result.ts

import { isEditOutcome, type EditOutcome } from "@/integrations/google_ads/lib/edit-outcomes"
import {
  AD_GROUP_SETTINGS,
  adGroupValue,
  type AdGroupSetting,
  type AdGroupValue,
} from "@/integrations/google_ads/lib/update-ad-groups"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type AdGroupOutcomeRow = {
  adGroupName: string
  after: AdGroupValue
  before: AdGroupValue
  campaignName: string
  errorCode: string | null
  message: string | null
  outcome: EditOutcome
  readBack: boolean
  setting: AdGroupSetting
}

export type UpdateAdGroupsResult = {
  accountId: string
  currency: string | null
  rows: AdGroupOutcomeRow[]
}

function parseAdGroup(raw: unknown): AdGroupOutcomeRow[] | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["name"]) || !Array.isArray(raw["settings"]))
    return null
  const text = (key: string) => (typeof raw[key] === "string" ? raw[key] : null)
  const rows: AdGroupOutcomeRow[] = []
  for (const item of raw["settings"]) {
    if (!isRecord(item)) return null
    const setting = AD_GROUP_SETTINGS.find((name) => name === item["setting"])
    const outcome = item["outcome"]
    if (!setting || !isEditOutcome(outcome)) return null
    const before = adGroupValue(setting, item["before"])
    const after = adGroupValue(setting, item["after"])
    if (before === undefined || after === undefined) return null
    rows.push({
      adGroupName: raw["name"],
      after,
      before,
      campaignName: text("campaign_name") ?? "",
      errorCode: text("error_code"),
      message: text("message"),
      outcome,
      readBack: raw["read_back"] === true,
      setting,
    })
  }
  return rows
}

export function parseUpdateAdGroupsResult(raw: unknown): UpdateAdGroupsResult | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["account_id"]) || !Array.isArray(raw["ad_groups"]))
    return null
  const adGroups = raw["ad_groups"].map(parseAdGroup)
  if (adGroups.some((rows) => rows === null)) return null
  return {
    accountId: raw["account_id"],
    currency: isNonEmptyString(raw["currency"]) ? raw["currency"] : null,
    rows: adGroups.flatMap((rows) => rows ?? []),
  }
}
