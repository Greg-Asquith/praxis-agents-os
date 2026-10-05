// apps/web/src/integrations/meta_ads/lib/budget-change.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { formatCurrency, formatCurrencyAmount, formatPercentageChange } from "@/lib/format"
import { isNonEmptyString, isRecord, parsePositiveDecimal } from "@/lib/guards"

type BudgetObjectType = "campaign" | "adset"
export type BudgetKind = "daily" | "lifetime"

type BudgetCheck = {
  problem: string | null
  spent: string | null
  recentChanges: number | null
  // False when the counts are lower bounds because history couldn't be read in full.
  recentChangesComplete: boolean
  unavailable: boolean
}

export type BudgetChange = {
  type: BudgetObjectType
  id: string
  accountId: string
  name: string
  scope: string | null
  currency: string | null
  // Null when the object doesn't hold its own budget or it couldn't be read.
  kind: BudgetKind | null
  previousAmount: string | null
  amount: string
  check: BudgetCheck | null
}

export type BudgetChangeArgs = { changes: BudgetChange[] }

const REFERENCES = [
  { key: "campaign", type: "campaign", idKey: "campaign_id" },
  { key: "ad_set", type: "adset", idKey: "adset_id" },
] as const

export const BUDGET_OBJECT_TITLES = { campaign: "Campaign", adset: "Ad Set" } as const
const KIND_LABELS = { daily: "Daily", lifetime: "Lifetime" } as const
// Average days in a month, matching the Google Ads budget estimate.
const DAYS_PER_MONTH = 30.4

export function parseBudgetChangeArgs(value: unknown): BudgetChangeArgs | null {
  if (!isRecord(value) || !Array.isArray(value["updates"]) || value["updates"].length === 0)
    return null
  const checks = isRecord(value["_budget_checks"]) ? value["_budget_checks"] : {}
  const changes: BudgetChange[] = []
  for (const item of value["updates"]) {
    const change = parseChange(item, checks)
    if (change === null) return null
    changes.push(change)
  }
  return { changes }
}

function parseChange(value: unknown, checks: Record<string, unknown>): BudgetChange | null {
  if (!isRecord(value)) return null
  const amount = parsePositiveDecimal(value["amount"])
  const present = REFERENCES.filter((reference) => isRecord(value[reference.key]))
  const [reference] = present
  if (amount === null || reference === undefined || present.length !== 1) return null
  const target = value[reference.key] as Record<string, unknown>
  const id = target[reference.idKey]
  if (!isNonEmptyString(id)) return null
  const budget = isRecord(target["budget"]) ? target["budget"] : null
  const kind = budget?.["kind"]
  const ownKind = kind === "daily" || kind === "lifetime" ? kind : null
  return {
    type: reference.type,
    id,
    accountId: typeof target["account_id"] === "string" ? target["account_id"] : "",
    name: isNonEmptyString(target["label"]) ? target["label"] : id,
    scope: isNonEmptyString(target["scope_label"]) ? target["scope_label"] : null,
    currency: isNonEmptyString(target["currency"]) ? target["currency"] : null,
    kind: ownKind,
    previousAmount: ownKind && isNonEmptyString(budget?.["amount"]) ? budget["amount"] : null,
    amount,
    check: parseCheck(checks[id]),
  }
}

function parseCheck(value: unknown): BudgetCheck | null {
  if (!isRecord(value)) return null
  const recent = value["recent_changes"]
  return {
    problem: isNonEmptyString(value["problem"]) ? value["problem"] : null,
    spent: isNonEmptyString(value["spent"]) ? value["spent"] : null,
    recentChanges: typeof recent === "number" && Number.isSafeInteger(recent) ? recent : null,
    recentChangesComplete: value["recent_changes_complete"] !== false,
    unavailable: value["unavailable"] === true,
  }
}

export function budgetMoney(amount: string, currency: string | null): string {
  return currency ? formatCurrencyAmount(amount, currency) : amount
}

export function budgetKindLabel(kind: BudgetKind | null): string {
  return kind ? `${KIND_LABELS[kind]} Budget` : "Budget"
}

export function budgetChangeLine(change: BudgetChange): string {
  const after = budgetMoney(change.amount, change.currency)
  if (change.previousAmount === null) return `New amount: ${after}`
  const percent = formatPercentageChange(Number(change.previousAmount), Number(change.amount))
  return `${budgetMoney(change.previousAmount, change.currency)} → ${after} (${percent})`
}

// Notes under each proposed change; a problem comes first because it blocks approval.
export function budgetNotes(change: BudgetChange): string[] {
  const check = change.check
  if (check?.problem) return [check.problem]
  const notes: string[] = []
  if (check?.unavailable) notes.push("This budget couldn't be checked before approval.")
  const amount = Number(change.amount)
  if (change.kind === "daily" && change.currency && Number.isFinite(amount))
    notes.push(
      `About ${formatCurrency(amount * DAYS_PER_MONTH, change.currency, { maximumFractionDigits: 2 })} a month.`
    )
  if (change.kind === "lifetime" && check?.spent)
    notes.push(`Already spent ${budgetMoney(check.spent, change.currency)} of this budget.`)
  const recentNote = recentChangesNote(check)
  if (recentNote) notes.push(recentNote)
  return notes
}

function recentChangesNote(check: BudgetCheck | null): string | null {
  if (check === null || check.unavailable) return null
  const limit = "Meta limits how often a budget can change, so it might reject this one."
  const count = check.recentChanges ?? 0
  if (count > 0) {
    const times = `${String(count)} ${count === 1 ? "time" : "times"}`
    const atLeast = check.recentChangesComplete ? "" : "at least "
    return `Changed ${atLeast}${times} in the last hour. ${limit}`
  }
  if (!check.recentChangesComplete)
    return `Recent changes to this budget couldn't all be read. ${limit}`
  return null
}

export function hasBudgetProblem(args: BudgetChangeArgs | null): boolean {
  return args?.changes.some((change) => change.check?.problem) ?? false
}

export function budgetChangeDetails(args: BudgetChangeArgs | null): FanOutDetail[] {
  if (args === null) return []
  return [{ label: "Budgets", value: String(args.changes.length) }]
}

// Result models

type BudgetOutcomeToken = "updated" | "already_set" | "failed" | "unverified"

type BudgetResultRow = {
  type: BudgetObjectType
  id: string
  name: string
  kind: BudgetKind
  previousAmount: string
  requestedAmount: string
  amount: string | null
  outcome: BudgetOutcomeToken
  errorCode: string | null
  message: string | null
}

export type BudgetChangeResult = {
  accountId: string
  currency: string
  budgets: BudgetResultRow[]
}

const OUTCOMES = new Set<string>(["updated", "already_set", "failed", "unverified"])

export function parseBudgetChangeResult(value: unknown): BudgetChangeResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !isNonEmptyString(value["currency"]) ||
    !Array.isArray(value["budgets"])
  )
    return null
  const budgets: BudgetResultRow[] = []
  for (const item of value["budgets"]) {
    const row = parseResultRow(item)
    if (row === null) return null
    budgets.push(row)
  }
  return { accountId: value["account_id"], currency: value["currency"], budgets }
}

function parseResultRow(value: unknown): BudgetResultRow | null {
  if (
    !isRecord(value) ||
    (value["object_type"] !== "campaign" && value["object_type"] !== "adset") ||
    !isNonEmptyString(value["object_id"]) ||
    (value["budget_kind"] !== "daily" && value["budget_kind"] !== "lifetime") ||
    !isNonEmptyString(value["previous_amount"]) ||
    !isNonEmptyString(value["requested_amount"]) ||
    typeof value["outcome"] !== "string" ||
    !OUTCOMES.has(value["outcome"])
  )
    return null
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    type: value["object_type"],
    id: value["object_id"],
    name: isNonEmptyString(value["object_name"]) ? value["object_name"] : value["object_id"],
    kind: value["budget_kind"],
    previousAmount: value["previous_amount"],
    requestedAmount: value["requested_amount"],
    amount: text("amount"),
    outcome: value["outcome"] as BudgetOutcomeToken,
    errorCode: text("error_code"),
    message: text("message"),
  }
}
