// apps/web/src/integrations/google_ads/lib/update-conversions-result.ts

import { isEditOutcome, type EditOutcome } from "@/integrations/google_ads/lib/edit-outcomes"
import {
  CONVERSION_SETTINGS,
  conversionValue,
  type ConversionSetting,
  type ConversionValue,
} from "@/integrations/google_ads/lib/update-conversions"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type ConversionOutcomeRow = {
  after: ConversionValue
  before: ConversionValue
  errorCode: string | null
  message: string | null
  name: string
  outcome: EditOutcome
  readBack: boolean
  resourceName: string
  setting: ConversionSetting
}

export type UpdateConversionsResult = {
  accountId: string
  currency: string | null
  rows: ConversionOutcomeRow[]
}

function parseItem(raw: unknown): ConversionOutcomeRow[] | null {
  if (
    !isRecord(raw) ||
    !isNonEmptyString(raw["name"]) ||
    !isNonEmptyString(raw["resource_name"]) ||
    !Array.isArray(raw["settings"])
  )
    return null
  const text = (key: string) => (typeof raw[key] === "string" ? raw[key] : null)
  const rows: ConversionOutcomeRow[] = []
  for (const item of raw["settings"]) {
    if (!isRecord(item)) return null
    const setting = CONVERSION_SETTINGS.find((name) => name === item["setting"])
    const outcome = item["outcome"]
    if (!setting || !isEditOutcome(outcome)) return null
    const before = conversionValue(setting, item["before"])
    const after = conversionValue(setting, item["after"])
    if (before === undefined || after === undefined) return null
    rows.push({
      after,
      before,
      errorCode: text("error_code"),
      message: text("message"),
      name: raw["name"],
      outcome,
      readBack: raw["read_back"] === true,
      resourceName: raw["resource_name"],
      setting,
    })
  }
  return rows
}

export function parseUpdateConversionsResult(raw: unknown): UpdateConversionsResult | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["account_id"]) || !Array.isArray(raw["items"]))
    return null
  const items = raw["items"].map(parseItem)
  if (items.some((rows) => rows === null)) return null
  return {
    accountId: raw["account_id"],
    currency: isNonEmptyString(raw["currency"]) ? raw["currency"] : null,
    rows: items.flatMap((rows) => rows ?? []),
  }
}
