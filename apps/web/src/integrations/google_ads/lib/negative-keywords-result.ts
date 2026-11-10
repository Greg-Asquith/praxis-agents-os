// apps/web/src/integrations/google_ads/lib/negative-keywords-result.ts

import type { DataTableTab } from "@/components/ui/data-table"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import {
  MATCH_TYPES,
  type NegativeTargetKind,
} from "@/integrations/google_ads/lib/negative-keywords"
import { isRecord } from "@/lib/guards"

export type NegativeOutcome =
  "added" | "removed" | "created" | "already_set" | "not_found" | "failed" | "unverified"

type NegativeOutcomeRow = {
  action: "add" | "remove" | "create"
  errorCode: string | null
  item: "keyword" | "campaign" | "list"
  matchType: KeywordMatchType | null
  message: string | null
  name: string
  outcome: NegativeOutcome
  targetKind: NegativeTargetKind
  targetName: string
}

export type UpdateNegativeKeywordsResult = { accountId: string; rows: NegativeOutcomeRow[] }

export const NEGATIVE_OUTCOME_LABELS: Record<NegativeOutcome, string> = {
  added: "Added",
  already_set: "Already in Place",
  created: "Created",
  failed: "Failed",
  not_found: "Not There",
  removed: "Removed",
  unverified: "Unconfirmed",
}

export const NEGATIVE_OUTCOME_BADGES = {
  added: "success",
  already_set: "secondary",
  created: "success",
  failed: "destructive",
  not_found: "secondary",
  removed: "success",
  unverified: "warning",
} as const

const OUTCOMES = Object.keys(NEGATIVE_OUTCOME_LABELS)
const KINDS = ["campaign", "ad_group", "list", "new_list"]

function parseRow(value: unknown): NegativeOutcomeRow | null {
  if (!isRecord(value)) return null
  const { action, item, match_type: matchType, name, outcome, target_kind: kind } = value
  if (
    (action !== "add" && action !== "remove" && action !== "create") ||
    (item !== "keyword" && item !== "campaign" && item !== "list") ||
    typeof outcome !== "string" ||
    !OUTCOMES.includes(outcome) ||
    typeof kind !== "string" ||
    !KINDS.includes(kind) ||
    typeof name !== "string" ||
    (matchType != null &&
      (typeof matchType !== "string" || !(MATCH_TYPES as readonly string[]).includes(matchType)))
  )
    return null
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    action,
    errorCode: text("error_code"),
    item,
    matchType: (matchType ?? null) as KeywordMatchType | null,
    message: text("message"),
    name,
    outcome: outcome as NegativeOutcome,
    targetKind: kind as NegativeTargetKind,
    targetName: text("target_name") ?? "",
  }
}

export function parseNegativeKeywordsResult(value: unknown): UpdateNegativeKeywordsResult | null {
  if (!isRecord(value) || typeof value["account_id"] !== "string") return null
  if (!Array.isArray(value["outcomes"])) return null
  const rows = value["outcomes"].map(parseRow)
  if (rows.some((row) => row === null)) return null
  return { accountId: value["account_id"], rows: rows.filter((row) => row !== null) }
}

export function negativeOutcomeSummary(rows: readonly NegativeOutcomeRow[]): string {
  const totals = new Map<NegativeOutcome, number>()
  for (const row of rows) totals.set(row.outcome, (totals.get(row.outcome) ?? 0) + 1)
  return [...totals]
    .map(
      ([outcome, total]) =>
        `${total.toLocaleString("en-GB")} ${NEGATIVE_OUTCOME_LABELS[outcome].toLowerCase()}`
    )
    .join(" · ")
}

function tab(id: NegativeOutcome | "all", hideWhenEmpty = true): DataTableTab {
  return {
    hideWhenEmpty,
    id,
    label: id === "all" ? "All" : NEGATIVE_OUTCOME_LABELS[id],
    match: (row) => id === "all" || row["token"] === id,
  }
}

// Result tables put each row's outcome in `token`.
export const NEGATIVE_OUTCOME_TABS: DataTableTab[] = [
  tab("all", false),
  tab("added"),
  tab("removed"),
  tab("created"),
  tab("already_set"),
  tab("not_found"),
  tab("failed"),
  tab("unverified"),
]
