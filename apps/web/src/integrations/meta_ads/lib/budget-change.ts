// apps/web/src/integrations/meta_ads/lib/budget-change.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { formatCurrency, formatCurrencyAmount } from "@/lib/format"
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
  // The amount as typed, which can be invalid while the operator edits.
  amount: string
  check: BudgetCheck | null
  // The update as sent, so edits keep the reference the card doesn't change.
  raw: Record<string, unknown>
}

export type BudgetChangeArgs = { changes: BudgetChange[] }

/** One proposed change, kept in the list when the operator drops it so it can come back. */
export type BudgetRow = { change: BudgetChange; included: boolean }

const REFERENCES = [
  { key: "campaign", type: "campaign", idKey: "campaign_id" },
  { key: "ad_set", type: "adset", idKey: "adset_id" },
] as const

export const BUDGET_OBJECT_TITLES = { campaign: "Campaign", adset: "Ad Set" } as const
const KIND_SUFFIXES = { daily: "a day", lifetime: "in total" } as const
// Average days in a month, matching the Google Ads budget estimate.
const DAYS_PER_MONTH = 30.4

export function parseBudgetChangeArgs(value: unknown): BudgetChangeArgs | null {
  if (!isRecord(value) || !Array.isArray(value["updates"])) return null
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
  const amount = typeof value["amount"] === "string" ? value["amount"] : null
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
    check: parseCheck(checks[id], amount),
    raw: value,
  }
}

// A check run for another amount says nothing about the amount now on the card.
function parseCheck(value: unknown, amount: string): BudgetCheck | null {
  if (!isRecord(value)) return null
  if (typeof value["amount"] === "string" && value["amount"] !== amount) return null
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

export function budgetKindSuffix(kind: BudgetKind | null): string {
  return kind ? KIND_SUFFIXES[kind] : ""
}

/** True for a positive amount with at most two decimals, which Meta takes as a budget. */
export function isBudgetAmount(amount: string): boolean {
  return parsePositiveDecimal(amount) !== null && /^\d+(\.\d{1,2})?$/.test(amount.trim())
}

// Notes under each proposed change; a problem is shown apart because it blocks approval.
export function budgetNotes(change: BudgetChange): string[] {
  const check = change.check
  if (check?.problem) return []
  const notes: string[] = []
  if (check?.unavailable) notes.push("This budget couldn't be checked before approval.")
  const amount = Number(change.amount)
  if (change.kind === "daily" && change.currency && isBudgetAmount(change.amount))
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

/** Why the proposed budgets can't be approved yet, or null. */
export function budgetProblem(args: BudgetChangeArgs | null): string | null {
  if (args === null) return null
  if (args.changes.length === 0) return "Keep at least one budget, or decline this request."
  if (args.changes.some((change) => !isBudgetAmount(change.amount)))
    return "Enter each new amount above zero, with at most two decimal places."
  if (args.changes.some((change) => change.check?.problem))
    return "Change or untick the budgets Meta won't accept, or decline this request."
  return null
}

export function budgetRowKey(change: BudgetChange): string {
  return `${change.type}:${change.id}`
}

/** The proposed budgets with the ones the operator dropped, in the proposed order. */
export function budgetRows(proposed: BudgetChangeArgs, current: BudgetChangeArgs): BudgetRow[] {
  const kept = new Map(current.changes.map((change) => [budgetRowKey(change), change]))
  return proposed.changes.map((change) => {
    const edited = kept.get(budgetRowKey(change))
    return { change: edited ?? change, included: edited !== undefined }
  })
}

/** The `updates` argument after setting one row's amount or including or dropping it. */
export function editBudgets(
  rows: readonly BudgetRow[],
  key: string,
  edit: { amount: string } | { included: boolean }
): Record<string, unknown>[] {
  return rows.flatMap((row) => {
    const same = budgetRowKey(row.change) === key
    const included = same && "included" in edit ? edit.included : row.included
    const amount = same && "amount" in edit ? edit.amount : row.change.amount
    return included ? [{ ...row.change.raw, amount }] : []
  })
}

type DailyTotal = { before: number; after: number; currency: string }

/** What the kept daily budgets add up to before and after, in whole minor units. */
export function dailyTotal(rows: readonly BudgetRow[]): DailyTotal | null {
  const daily = rows.filter(
    ({ change, included }) =>
      included &&
      change.kind === "daily" &&
      change.currency &&
      change.previousAmount !== null &&
      isBudgetAmount(change.amount)
  )
  const currency = daily[0]?.change.currency
  if (!currency) return null
  const sum = (amount: (change: BudgetChange) => string | null) =>
    daily.reduce((total, { change }) => total + Math.round(Number(amount(change)) * 100), 0) / 100
  return {
    before: sum((change) => change.previousAmount),
    after: sum((change) => change.amount),
    currency,
  }
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
