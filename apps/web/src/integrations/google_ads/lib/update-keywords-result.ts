// apps/web/src/integrations/google_ads/lib/update-keywords-result.ts

import { isEditOutcome, type EditOutcome } from "@/integrations/google_ads/lib/edit-outcomes"
import {
  KEYWORD_SETTINGS,
  keywordValue,
  type KeywordSetting,
  type KeywordValue,
} from "@/integrations/google_ads/lib/update-keywords"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type KeywordOutcomeRow = {
  adGroupName: string
  after: KeywordValue
  before: KeywordValue
  errorCode: string | null
  message: string | null
  outcome: EditOutcome
  readBack: boolean
  // The keyword added with the new match type, when Google confirmed it.
  replacement: string | null
  setting: KeywordSetting
  text: string
}

export type UpdateKeywordsResult = {
  accountId: string
  currency: string | null
  rows: KeywordOutcomeRow[]
}

function parseKeyword(raw: unknown): KeywordOutcomeRow[] | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["text"]) || !Array.isArray(raw["settings"]))
    return null
  const text = (key: string) => (typeof raw[key] === "string" ? raw[key] : null)
  const rows: KeywordOutcomeRow[] = []
  for (const item of raw["settings"]) {
    if (!isRecord(item)) return null
    const setting = KEYWORD_SETTINGS.find((name) => name === item["setting"])
    const outcome = item["outcome"]
    if (!setting || !isEditOutcome(outcome)) return null
    const before = keywordValue(setting, item["before"])
    const after = keywordValue(setting, item["after"])
    if (before === undefined) return null
    rows.push({
      adGroupName: text("ad_group_name") ?? "",
      // A failed match type change has no after value to read.
      after: after ?? null,
      before,
      errorCode: text("error_code"),
      message: text("message"),
      outcome,
      readBack: raw["read_back"] === true,
      replacement: text("replacement"),
      setting,
      text: raw["text"],
    })
  }
  return rows
}

export function parseUpdateKeywordsResult(raw: unknown): UpdateKeywordsResult | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["account_id"]) || !Array.isArray(raw["keywords"]))
    return null
  const keywords = raw["keywords"].map(parseKeyword)
  if (keywords.some((rows) => rows === null)) return null
  return {
    accountId: raw["account_id"],
    currency: isNonEmptyString(raw["currency"]) ? raw["currency"] : null,
    rows: keywords.flatMap((rows) => rows ?? []),
  }
}
