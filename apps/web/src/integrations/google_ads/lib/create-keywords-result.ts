// apps/web/src/integrations/google_ads/lib/create-keywords-result.ts

import type { DataTableTab } from "@/components/ui/data-table"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import { countsText } from "@/integrations/google_ads/lib/edit-outcomes"
import { isNonEmptyString, isRecord } from "@/lib/guards"

const OUTCOMES = ["added", "already_set", "failed", "unverified"] as const

export type KeywordAdditionOutcome = (typeof OUTCOMES)[number]

export const ADDITION_LABELS: Record<KeywordAdditionOutcome, string> = {
  added: "Added",
  already_set: "Already There",
  failed: "Failed",
  unverified: "Unconfirmed",
}

export const ADDITION_BADGES = {
  added: "success",
  already_set: "secondary",
  failed: "destructive",
  unverified: "warning",
} as const

// Result rows put each outcome in `token`.
export const ADDITION_TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  ...OUTCOMES.map((outcome) => ({
    hideWhenEmpty: true,
    id: outcome,
    label: ADDITION_LABELS[outcome],
    match: (row: Record<string, unknown>) => row["token"] === outcome,
  })),
]

export type AddedKeywordRow = {
  adGroupName: string
  campaignName: string
  cpcBid: string | null
  errorCode: string | null
  finalUrl: string | null
  matchType: KeywordMatchType
  message: string | null
  outcome: KeywordAdditionOutcome
  text: string
}

export type CreateKeywordsResult = {
  accountId: string
  currency: string | null
  rows: AddedKeywordRow[]
  status: "ENABLED" | "PAUSED"
}

function parseRow(raw: unknown): AddedKeywordRow | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["text"])) return null
  const outcome = OUTCOMES.find((item) => item === raw["outcome"])
  const matchType = raw["match_type"]
  if (!outcome || (matchType !== "EXACT" && matchType !== "PHRASE" && matchType !== "BROAD"))
    return null
  const text = (key: string) => (typeof raw[key] === "string" ? raw[key] : null)
  return {
    adGroupName: text("ad_group_name") ?? "",
    campaignName: text("campaign_name") ?? "",
    cpcBid: text("cpc_bid"),
    errorCode: text("error_code"),
    finalUrl: text("final_url"),
    matchType,
    message: text("message"),
    outcome,
    text: raw["text"],
  }
}

export function parseCreateKeywordsResult(raw: unknown): CreateKeywordsResult | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["account_id"]) || !Array.isArray(raw["keywords"]))
    return null
  const rows = raw["keywords"].map(parseRow)
  if (rows.some((row) => row === null)) return null
  return {
    accountId: raw["account_id"],
    currency: isNonEmptyString(raw["currency"]) ? raw["currency"] : null,
    rows: rows as AddedKeywordRow[],
    status: raw["status"] === "ENABLED" ? "ENABLED" : "PAUSED",
  }
}

/** Counts each outcome, such as "600 added · 2 failed", leaving out outcomes with none. */
export function additionSummary(rows: readonly AddedKeywordRow[]): string {
  return countsText(
    OUTCOMES.map((outcome) => [
      rows.filter((row) => row.outcome === outcome).length,
      ADDITION_LABELS[outcome].toLowerCase(),
    ])
  )
}
