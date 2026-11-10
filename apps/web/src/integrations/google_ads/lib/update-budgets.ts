// apps/web/src/integrations/google_ads/lib/update-budgets.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { canonicalMoney } from "@/integrations/google_ads/lib/campaign-bidding"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { formatCurrency, formatCurrencyAmount } from "@/lib/format"
import { isRecord } from "@/lib/guards"

// Google charges at most this many days of a daily budget in a month.
export const DAYS_PER_MONTH = 30.4
export const DELIVERIES = ["STANDARD", "ACCELERATED"] as const
export type Delivery = (typeof DELIVERIES)[number]
export const DELIVERY_LABELS: Record<Delivery, string> = {
  ACCELERATED: "Accelerated",
  STANDARD: "Standard",
}

export type BudgetSetting = "amount" | "delivery" | "shared_budget"

export const BUDGET_SETTING_TITLES: Record<BudgetSetting, string> = {
  amount: "Daily Budget",
  delivery: "Delivery",
  shared_budget: "Budget",
}

type BudgetChange = {
  // A canonical decimal, as the server compares it.
  amount: string | null
  customerId: string
  delivery: Delivery | null
  // The change as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  key: string
  kind: "campaign" | "budget"
  label: string
  // The shared budget a campaign moves onto, by resource name.
  sharedBudget: string | null
  sharedBudgetLabel: string | null
}

type BudgetCampaign = { name: string; spend: string }

type BudgetView = {
  amount: string | null
  campaignCount: number
  campaigns: BudgetCampaign[]
  delivery: string | null
  name: string
  resourceName: string
  shared: boolean
  spendThisMonth: string
}

type BudgetCheck =
  | { unavailable: true }
  | {
      unavailable: false
      budget: BudgetView | null
      current: { amount: string | null; delivery: string | null; sharedBudget: string | null }
      daysLeft: number | null
      destination: BudgetView | null
      name: string | null
      problem: string | null
      removesBudget: boolean
      requested: Partial<Record<BudgetSetting, string>>
      spendThisMonth: string | null
    }

export type UpdateBudgetsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  changes: BudgetChange[]
  checks: Map<string, BudgetCheck>
}

// A change the operator cancelled, kept beside the request so Undo can bring it back.
export type CancelledBudgetChange = { entry: Record<string, unknown>; key: string }

export type BudgetRow = {
  amount: string | null
  budget: BudgetView | null
  cancelled: boolean
  change: BudgetChange | null
  customerId: string
  daysLeft: number | null
  delivery: Delivery | null
  destination: BudgetView | null
  id: string
  key: string
  kind: "campaign" | "budget"
  name: string
  // Blocks approval while set.
  problem: string | null
  removesBudget: boolean
  sharedBudget: string | null
  sharedBudgetLabel: string | null
  // This month's cost for the budget, or for the campaign when it moves.
  spend: string | null
  // Every requested setting is already live, so nothing is sent.
  unchanged: boolean
  // The live amount and delivery; undefined when the budget couldn't be read.
  was: { amount: string | null; delivery: string | null } | undefined
}

export type BudgetCounts = {
  apply: number
  campaigns: number
  decreases: number
  increases: number
  moves: number
  problems: number
  shared: number
  total: number
}

const UNAVAILABLE_PROBLEM =
  "Google Ads couldn't check this budget. Ask the agent to prepare the change again."

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function money(value: unknown): string | null {
  return typeof value === "string" && /^\d+(\.\d+)?$/.test(value.trim())
    ? canonicalMoney(value)
    : null
}

function delivery(value: unknown): Delivery | null {
  return DELIVERIES.find((item) => item === value) ?? null
}

function budgetResource(reference: unknown): string | null {
  if (!isRecord(reference)) return null
  const customerId = googleAdsId(reference["customer_id"])
  const budgetId = googleAdsId(reference["budget_id"])
  return customerId && budgetId ? `customers/${customerId}/campaignBudgets/${budgetId}` : null
}

function parseChange(value: unknown): BudgetChange | null {
  if (!isRecord(value)) return null
  const campaign = isRecord(value["campaign"]) ? value["campaign"] : null
  const budget = isRecord(value["budget"]) ? value["budget"] : null
  const reference = campaign ?? budget
  if (!reference || (campaign && budget)) return null
  const customerId = googleAdsId(reference["customer_id"])
  const id = googleAdsId(reference[campaign ? "campaign_id" : "budget_id"])
  if (customerId === null || id === null) return null
  const shared = value["use_shared_budget"]
  return {
    amount: money(value["amount"]),
    customerId,
    delivery: delivery(value["delivery"]),
    entry: value,
    key: `customers/${customerId}/${campaign ? "campaigns" : "campaignBudgets"}/${id}`,
    kind: campaign ? "campaign" : "budget",
    label: text(reference["label"]) ?? id,
    sharedBudget: budgetResource(shared),
    sharedBudgetLabel: isRecord(shared) ? text(shared["label"]) : null,
  }
}

function parseView(value: unknown): BudgetView | null {
  if (!isRecord(value) || !text(value["resource_name"])) return null
  const campaigns = Array.isArray(value["campaigns"]) ? value["campaigns"] : []
  return {
    amount: money(value["amount"]),
    campaignCount: typeof value["campaign_count"] === "number" ? value["campaign_count"] : 0,
    campaigns: campaigns.flatMap((item) =>
      isRecord(item) && text(item["name"])
        ? [{ name: String(item["name"]), spend: money(item["spend"]) ?? "0" }]
        : []
    ),
    delivery: text(value["delivery"]),
    name: text(value["name"]) ?? "Budget",
    resourceName: String(value["resource_name"]),
    shared: value["shared"] === true,
    spendThisMonth: money(value["spend_this_month"]) ?? "0",
  }
}

function parseCheck(value: unknown): BudgetCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const current = isRecord(value["current"]) ? value["current"] : {}
  const requested = isRecord(value["requested"]) ? value["requested"] : {}
  const days = value["days_left"]
  return {
    unavailable: false,
    budget: parseView(value["budget"]),
    current: {
      amount: money(current["amount"]),
      delivery: text(current["delivery"]),
      sharedBudget: text(current["shared_budget"]),
    },
    daysLeft: typeof days === "number" && Number.isInteger(days) && days > 0 ? days : null,
    destination: parseView(value["destination"]),
    name: text(value["name"]),
    problem: text(value["problem"]),
    removesBudget: value["removes_budget"] === true,
    requested: Object.fromEntries(
      (["amount", "delivery", "shared_budget"] as const).flatMap((setting) => {
        const item = text(requested[setting])
        return item ? [[setting, setting === "amount" ? canonicalMoney(item) : item]] : []
      })
    ),
    spendThisMonth: money(value["spend_this_month"]),
  }
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseUpdateBudgetsArgs(value: unknown): UpdateBudgetsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const changes: BudgetChange[] = []
  const keys = new Set<string>()
  for (const entry of value["changes"]) {
    const change = parseChange(entry)
    if (change === null || keys.has(change.key)) return null
    keys.add(change.key)
    changes.push(change)
  }
  const rawChecks = isRecord(value["_checks"]) ? value["_checks"] : {}
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    changes,
    checks: new Map(Object.entries(rawChecks).map(([key, check]) => [key, parseCheck(check)])),
  }
}

/** The settings a change sets, in the server's card terms. */
function requestedOf(change: BudgetChange): Partial<Record<BudgetSetting, string>> {
  return {
    ...(change.amount ? { amount: change.amount } : {}),
    ...(change.delivery ? { delivery: change.delivery } : {}),
    ...(change.sharedBudget ? { shared_budget: change.sharedBudget } : {}),
  }
}

function rowOf(change: BudgetChange, check: BudgetCheck | undefined, cancelled: boolean) {
  const live = check && !check.unavailable ? check : null
  const requested = requestedOf(change)
  // Google answered for the change it was checked with, so an edit waits for a new check.
  const checked = live !== null && JSON.stringify(live.requested) === JSON.stringify(requested)
  const was = live ? { amount: live.current.amount, delivery: live.current.delivery } : undefined
  const unchanged =
    live !== null &&
    (change.amount === null || change.amount === live.current.amount) &&
    (change.delivery === null || change.delivery === live.current.delivery) &&
    (change.sharedBudget === null || change.sharedBudget === live.current.sharedBudget)
  const row: BudgetRow = {
    amount: change.amount,
    budget: live?.budget ?? null,
    cancelled,
    change: cancelled ? null : change,
    customerId: change.customerId,
    daysLeft: live?.daysLeft ?? null,
    delivery: change.delivery,
    destination: live?.destination?.resourceName === change.sharedBudget ? live.destination : null,
    id: change.key,
    key: change.key,
    kind: change.kind,
    name: live?.name ?? change.label,
    problem: live === null ? UNAVAILABLE_PROBLEM : checked ? live.problem : null,
    removesBudget: live?.removesBudget ?? false,
    sharedBudget: change.sharedBudget,
    sharedBudgetLabel:
      live?.destination?.resourceName === change.sharedBudget
        ? live.destination.name
        : change.sharedBudgetLabel,
    spend: live?.spendThisMonth ?? null,
    unchanged,
    was,
  }
  return row
}

/** One row per change, with cancelled changes after the ones still requested. */
export function budgetRows(
  args: UpdateBudgetsArgs,
  checked: UpdateBudgetsArgs,
  cancelled: readonly CancelledBudgetChange[] = []
): BudgetRow[] {
  const rows = args.changes.map((change) => rowOf(change, checked.checks.get(change.key), false))
  const live = new Set(rows.map((row) => row.key))
  for (const item of cancelled) {
    const change = parseChange(item.entry)
    if (change && !live.has(change.key))
      rows.push(rowOf(change, checked.checks.get(change.key), true))
  }
  return rows
}

/** How much a row raises (positive) or lowers the daily amount; null when it doesn't set one. */
export function dailyDelta(row: BudgetRow): number | null {
  const was = row.was?.amount
  if (row.amount === null || was === null || was === undefined) return null
  return Number(row.amount) - Number(was)
}

export function budgetCounts(rows: readonly BudgetRow[]): BudgetCounts {
  const live = rows.filter((row) => !row.cancelled)
  const delta = (row: BudgetRow) => dailyDelta(row) ?? 0
  return {
    apply: live.filter((row) => !row.unchanged).length,
    campaigns: new Set(
      live.flatMap((row) =>
        row.kind === "campaign" ? [row.key] : (row.budget?.campaigns.map((item) => item.name) ?? [])
      )
    ).size,
    decreases: live.filter((row) => delta(row) < 0).length,
    increases: live.filter((row) => delta(row) > 0).length,
    moves: live.filter((row) => row.sharedBudget !== null).length,
    problems: live.filter((row) => row.problem !== null).length,
    shared: live.filter((row) => row.sharedBudget === null && row.budget?.shared === true).length,
    total: live.length,
  }
}

/** The total change to daily spending across every amount still requested. */
export function totalDailyDelta(rows: readonly BudgetRow[]): number {
  return rows
    .filter((row) => !row.cancelled && row.problem === null)
    .reduce((total, row) => total + (dailyDelta(row) ?? 0), 0)
}

/** What the month comes to: this month's spend so far, then the amount for each day left. */
export function monthAtAmount(row: BudgetRow, amount: string | null): number | null {
  if (row.spend === null || row.daysLeft === null || amount === null) return null
  return Number(row.spend) + Number(amount) * row.daysLeft
}

function withEntry(
  entry: Record<string, unknown>,
  key: string,
  value: unknown
): Record<string, unknown> {
  if (value !== undefined) return { ...entry, [key]: value }
  return Object.fromEntries(Object.entries(entry).filter(([name]) => name !== key))
}

/** The `changes` value with each chosen change's entry replaced. */
export function editedBudgetChanges(
  args: UpdateBudgetsArgs,
  ids: ReadonlySet<string>,
  edit: (change: BudgetChange) => Record<string, unknown>
): Record<string, unknown>[] {
  return args.changes.map((change) => (ids.has(change.key) ? edit(change) : change.entry))
}

export function withAmount(change: BudgetChange, amount: string): Record<string, unknown> {
  return withEntry(change.entry, "amount", amount)
}

export function withDelivery(change: BudgetChange, value: Delivery): Record<string, unknown> {
  return withEntry(change.entry, "delivery", value)
}

export function withSharedBudget(
  change: BudgetChange,
  reference: Record<string, unknown>
): Record<string, unknown> {
  return withEntry(change.entry, "use_shared_budget", reference)
}

/** The `changes` value without the chosen changes, and those changes to keep for Undo. */
export function cancelledBudgetChanges(
  args: UpdateBudgetsArgs,
  ids: ReadonlySet<string>
): { changes: Record<string, unknown>[]; cancelled: CancelledBudgetChange[] } {
  return {
    cancelled: args.changes
      .filter((change) => ids.has(change.key))
      .map((change) => ({ entry: change.entry, key: change.key })),
    changes: args.changes.filter((change) => !ids.has(change.key)).map((change) => change.entry),
  }
}

export function parseCancelledBudgetChanges(value: unknown): CancelledBudgetChange[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) =>
    isRecord(item) && isRecord(item["entry"]) && typeof item["key"] === "string"
      ? [{ entry: item["entry"], key: item["key"] }]
      : []
  )
}

function signature(args: UpdateBudgetsArgs): string {
  return JSON.stringify(args.changes.map((change) => [change.key, requestedOf(change)]))
}

export function budgetsNeedCheck(args: UpdateBudgetsArgs, checked: UpdateBudgetsArgs) {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    signature(args) !== signature(checked)
  )
}

/** Why the request can't be approved yet, or null. */
export function budgetsBlock(
  args: UpdateBudgetsArgs | null,
  checked: UpdateBudgetsArgs
): string | null {
  if (args === null) return null
  const counts = budgetCounts(budgetRows(args, checked))
  if (counts.total === 0) return "Every change is cancelled. Decline this request, or undo one."
  if (budgetsNeedCheck(args, checked))
    return "Click Check Changes so Google can check your edits, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "change")} to continue.`
  if (counts.apply === 0) return "These budgets already have these settings."
  return null
}

export function budgetCurrency(args: UpdateBudgetsArgs, row: BudgetRow): string | null {
  return args.accounts.get(row.customerId)?.currencyCode ?? null
}

export function moneyText(value: string | number | null, currency: string | null): string {
  if (value === null) return "—"
  if (typeof value === "number")
    return formatCurrency(value, currency, { maximumFractionDigits: 2 })
  return currency ? formatCurrencyAmount(value, currency) : value
}

/** A result value in the words the card uses; a shared budget arrives as its name. */
export function budgetValueText(
  setting: BudgetSetting,
  value: string | null,
  currency: string | null
): string {
  if (value === null) return "—"
  if (setting === "amount") return moneyText(value, currency)
  const method = delivery(value)
  return setting === "delivery" && method ? DELIVERY_LABELS[method] : value
}

/** The budget a row's campaign or budget uses, as the card names it. */
export function budgetKindText(row: BudgetRow): string {
  if (!row.budget) return "—"
  return row.budget.shared
    ? `Shared · ${approvalCountLine(row.budget.campaignCount, "campaign")}`
    : "Own"
}

function soleRow(args: UpdateBudgetsArgs): BudgetRow | null {
  const rows = budgetRows(args, args)
  return rows.length === 1 ? (rows[0] ?? null) : null
}

export function budgetsPrompt(args: UpdateBudgetsArgs): string {
  const rows = budgetRows(args, args)
  if (rows.length === 0) return "Nothing is left to change."
  const sole = soleRow(args)
  if (sole) {
    const currency = budgetCurrency(args, sole)
    if (sole.sharedBudget)
      return `Move ${sole.name} onto ${sole.sharedBudgetLabel ?? "a shared budget"}.`
    if (sole.amount)
      return `Set the daily budget of ${sole.name} to ${moneyText(sole.amount, currency)}.`
    return `Change how ${sole.name} spends its budget.`
  }
  const ids = new Set(args.changes.map((change) => change.customerId))
  const [id] = ids
  const where =
    ids.size === 1
      ? (args.accounts.get(id ?? "")?.label ?? "Google Ads")
      : `${String(ids.size)} accounts`
  return `Change ${approvalCountLine(rows.length, "budget")} in ${where}.`
}

/** Names the change when there is only one; otherwise counts what's sent. */
export function budgetsApproveLabel(args: UpdateBudgetsArgs): string {
  const sole = soleRow(args)
  if (sole && !sole.unchanged) return sole.sharedBudget ? "Move Campaign" : "Change Budget"
  const { apply } = budgetCounts(budgetRows(args, args))
  return apply === 0
    ? "Apply Changes"
    : `Apply ${String(apply)} ${apply === 1 ? "Change" : "Changes"}`
}

export function budgetsBannerDetail(
  counts: BudgetCounts,
  accountIds: readonly string[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>
): string {
  const account = accountIds.length === 1 ? accounts.get(accountIds[0] ?? "") : undefined
  return [
    account?.label ?? null,
    approvalCountLine(counts.total, "budget"),
    counts.campaigns > 0 ? approvalCountLine(counts.campaigns, "campaign") : null,
    account?.timeZone ? `Account time ${account.timeZone}` : null,
  ]
    .filter((part) => part !== null)
    .join(" · ")
}

export function budgetsDetails(args: UpdateBudgetsArgs | null): FanOutDetail[] {
  return args ? [{ label: "Budgets", value: String(args.changes.length) }] : []
}
