// apps/web/src/integrations/google_ads/lib/search-terms-result.ts

import type { DataTableTab } from "@/components/ui/data-table"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import type { SearchTermAction } from "@/integrations/google_ads/lib/search-terms"
import { isRecord } from "@/lib/guards"

type SearchTermOutcome = "added" | "already_set" | "failed" | "unverified"

type SearchTermOutcomeRow = {
  action: SearchTermAction
  adGroupName: string
  campaignName: string
  clicks: number | null
  conversions: number | null
  cost: number | null
  errorCode: string | null
  matchType: KeywordMatchType
  message: string | null
  outcome: SearchTermOutcome
  targetKind: "ad_group" | "campaign" | "list"
  targetName: string
  term: string
}

export type OptimiseSearchTermsResult = {
  accountId: string
  currency: string
  rows: SearchTermOutcomeRow[]
}

// The result's `token` per row: what happened, with an addition split by action.
export type SearchTermToken = "blocked" | "added" | "already_set" | "failed" | "unverified"

export const SEARCH_TERM_TOKEN_LABELS: Record<SearchTermToken, string> = {
  added: "Added",
  already_set: "Already Set",
  blocked: "Blocked",
  failed: "Failed",
  unverified: "Unconfirmed",
}

export const SEARCH_TERM_TOKEN_BADGES = {
  added: "success",
  already_set: "secondary",
  blocked: "success",
  failed: "destructive",
  unverified: "warning",
} as const

const OUTCOMES = ["added", "already_set", "failed", "unverified"]
const KINDS = ["ad_group", "campaign", "list"]
const MATCH_TYPES = ["EXACT", "PHRASE", "BROAD"]

function parseRow(value: unknown): SearchTermOutcomeRow | null {
  if (!isRecord(value)) return null
  const { action, match_type: matchType, outcome, search_term: term, target_kind: kind } = value
  if (
    (action !== "add_negative" && action !== "add_keyword") ||
    typeof outcome !== "string" ||
    !OUTCOMES.includes(outcome) ||
    typeof kind !== "string" ||
    !KINDS.includes(kind) ||
    typeof term !== "string" ||
    typeof matchType !== "string" ||
    !MATCH_TYPES.includes(matchType)
  )
    return null
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  const number = (key: string) => {
    const item = value[key]
    const parsed = typeof item === "string" ? Number(item) : item
    return typeof parsed === "number" && Number.isFinite(parsed) ? parsed : null
  }
  return {
    action,
    adGroupName: text("ad_group_name") ?? "",
    campaignName: text("campaign_name") ?? "",
    clicks: number("clicks"),
    conversions: number("conversions"),
    cost: number("cost"),
    errorCode: text("error_code"),
    matchType: matchType as KeywordMatchType,
    message: text("message"),
    outcome: outcome as SearchTermOutcome,
    targetKind: kind as SearchTermOutcomeRow["targetKind"],
    targetName: text("target_name") ?? "",
    term,
  }
}

export function parseSearchTermsResult(value: unknown): OptimiseSearchTermsResult | null {
  if (!isRecord(value) || typeof value["account_id"] !== "string") return null
  if (typeof value["currency"] !== "string" || !Array.isArray(value["outcomes"])) return null
  const rows = value["outcomes"].map(parseRow)
  if (rows.some((row) => row === null)) return null
  return {
    accountId: value["account_id"],
    currency: value["currency"],
    rows: rows.filter((row) => row !== null),
  }
}

export function searchTermToken(row: SearchTermOutcomeRow): SearchTermToken {
  if (row.outcome !== "added") return row.outcome
  return row.action === "add_negative" ? "blocked" : "added"
}

export function searchTermOutcomeSummary(rows: readonly SearchTermOutcomeRow[]): string {
  const totals = new Map<SearchTermToken, number>()
  for (const row of rows) {
    const token = searchTermToken(row)
    totals.set(token, (totals.get(token) ?? 0) + 1)
  }
  return [...totals]
    .map(
      ([token, total]) =>
        `${total.toLocaleString("en-GB")} ${SEARCH_TERM_TOKEN_LABELS[token].toLowerCase()}`
    )
    .join(" · ")
}

function tab(id: SearchTermToken | "all", hideWhenEmpty = true): DataTableTab {
  return {
    hideWhenEmpty,
    id,
    label: id === "all" ? "All" : SEARCH_TERM_TOKEN_LABELS[id],
    match: (row) => id === "all" || row["token"] === id,
  }
}

export const SEARCH_TERM_OUTCOME_TABS: DataTableTab[] = [
  tab("all", false),
  tab("blocked"),
  tab("added"),
  tab("already_set"),
  tab("failed"),
  tab("unverified"),
]
