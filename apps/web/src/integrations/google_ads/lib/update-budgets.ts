// apps/web/src/integrations/google_ads/lib/update-budgets.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import {
  accountsText,
  parseCheckedEntries,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { canonicalMoney } from "@/integrations/google_ads/lib/campaign-bidding"
import {
  applyChangesLabel,
  approvalCountLine,
  changesBlock,
  unavailableProblem,
} from "@/integrations/google_ads/lib/copy"
import { googleAdsId, textOrNull } from "@/integrations/google_ads/lib/field-values"
import { soleRow } from "@/integrations/google_ads/lib/setting-changes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
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

// The networks a budget can spend on, in the order the server lists them within a tier.
const NETWORKS = ["GOOGLE_DISPLAY", "OWNED_AND_OPERATED", "SEARCH_PARTNER"] as const
export type Network = (typeof NETWORKS)[number]
export const NETWORK_LABELS: Record<Network, string> = {
  GOOGLE_DISPLAY: "Display Network",
  OWNED_AND_OPERATED: "Google",
  SEARCH_PARTNER: "Search Partners",
}
// A budget with no network order of its own follows the account's.
const ACCOUNT_DEFAULT = "ACCOUNT_DEFAULT"

/** The networks that spend first, then the rest with the most of the budget each may take. */
export type NetworkPriority = {
  first: Network[]
  then: { cap: number | null; network: Network }[]
}
export type NetworkTier = "first" | "then" | "off"

export type BudgetSetting = "amount" | "delivery" | "shared_budget" | "network_priority"
const BUDGET_SETTINGS = ["amount", "delivery", "shared_budget", "network_priority"] as const

export const BUDGET_SETTING_TITLES: Record<BudgetSetting, string> = {
  amount: "Daily Budget",
  delivery: "Delivery",
  network_priority: "Network Order",
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
  // The networks the budget spends on first, or the account's order again.
  networkPriority: NetworkPriority | "account_default" | null
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
      current: {
        amount: string | null
        delivery: string | null
        // The live network order as the server codes it; null when it wasn't read.
        networkPriority: string | null
        sharedBudget: string | null
      }
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
  networkPriority: NetworkPriority | "account_default" | null
  // Blocks approval while set.
  problem: string | null
  removesBudget: boolean
  sharedBudget: string | null
  sharedBudgetLabel: string | null
  // This month's cost for the budget, or for the campaign when it moves.
  spend: string | null
  // Every requested setting is already live, so nothing is sent.
  unchanged: boolean
  // The live settings; undefined when the budget couldn't be read.
  was:
    { amount: string | null; delivery: string | null; networkPriority: string | null } | undefined
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

const UNAVAILABLE_PROBLEM = unavailableProblem("budget")

function money(value: unknown): string | null {
  return typeof value === "string" && /^\d+(\.\d+)?$/.test(value.trim())
    ? canonicalMoney(value)
    : null
}

function delivery(value: unknown): Delivery | null {
  return DELIVERIES.find((item) => item === value) ?? null
}

function network(value: unknown): Network | null {
  return NETWORKS.find((item) => item === value) ?? null
}

function parseNetworkPriority(value: unknown): BudgetChange["networkPriority"] {
  if (value === "account_default") return value
  if (!isRecord(value) || !Array.isArray(value["first"])) return null
  const then = Array.isArray(value["then"]) ? value["then"] : []
  const first = value["first"].map(network)
  const rest = then.map((item) => {
    const name = isRecord(item) ? network(item["network"]) : null
    const cap = isRecord(item) ? item["cap_percent"] : null
    return name && { cap: typeof cap === "number" ? cap : null, network: name }
  })
  if (first.length === 0 || first.includes(null) || rest.includes(null)) return null
  return {
    first: first.filter((item) => item !== null),
    then: rest.filter((item) => item !== null),
  }
}

/** A network order as the server codes it, such as `OWNED_AND_OPERATED>SEARCH_PARTNER:20`. */
function networkCode(priority: NetworkPriority | "account_default"): string {
  if (priority === "account_default") return ACCOUNT_DEFAULT
  const then = priority.then.map((item) =>
    item.cap === null ? item.network : `${item.network}:${String(item.cap)}`
  )
  return [[...priority.first].sort(), then.sort()]
    .filter((tier) => tier.length > 0)
    .map((tier) => tier.join("+"))
    .join(">")
}

/** A coded network order in words, such as "Google first, then Search Partners (up to 20%)". */
export function networkOrderText(code: string | null): string {
  if (code === null) return "—"
  if (code === ACCOUNT_DEFAULT) return "Account default"
  const tiers = code.split(">").map((tier) =>
    tier
      .split("+")
      .map((item) => {
        const [name = "", cap] = item.split(":")
        const label = network(name) ? NETWORK_LABELS[name as Network] : googleAdsTokenLabel(name)
        return cap === undefined ? label : `${label} (up to ${cap}%)`
      })
      .join(" and ")
  )
  const [first = "", ...rest] = tiers
  if (rest.length > 0) return `${first} first, then ${rest.join(", then ")}`
  return first.includes(" and ") ? `${first} together` : `${first} only`
}

export function networkTier(priority: NetworkPriority | null, name: Network): NetworkTier {
  if (priority?.first.includes(name)) return "first"
  return priority?.then.some((item) => item.network === name) ? "then" : "off"
}

/** The order with one network moved; null when that would leave no network first. */
export function withNetworkTier(
  priority: NetworkPriority | null,
  name: Network,
  tier: NetworkTier
): NetworkPriority | null {
  const first = (priority?.first ?? []).filter((item) => item !== name)
  const then = (priority?.then ?? []).filter((item) => item.network !== name)
  if (tier === "first") first.push(name)
  if (tier === "then") then.push({ cap: null, network: name })
  return first.length === 0 ? null : { first, then }
}

export function withNetworkCap(
  priority: NetworkPriority,
  name: Network,
  cap: number | null
): NetworkPriority {
  return {
    first: priority.first,
    then: priority.then.map((item) => (item.network === name ? { cap, network: name } : item)),
  }
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
    label: textOrNull(reference["label"]) ?? id,
    networkPriority: parseNetworkPriority(value["network_priority"]),
    sharedBudget: budgetResource(shared),
    sharedBudgetLabel: isRecord(shared) ? textOrNull(shared["label"]) : null,
  }
}

function parseView(value: unknown): BudgetView | null {
  if (!isRecord(value) || !textOrNull(value["resource_name"])) return null
  const campaigns = Array.isArray(value["campaigns"]) ? value["campaigns"] : []
  return {
    amount: money(value["amount"]),
    campaignCount: typeof value["campaign_count"] === "number" ? value["campaign_count"] : 0,
    campaigns: campaigns.flatMap((item) =>
      isRecord(item) && textOrNull(item["name"])
        ? [{ name: String(item["name"]), spend: money(item["spend"]) ?? "0" }]
        : []
    ),
    delivery: textOrNull(value["delivery"]),
    name: textOrNull(value["name"]) ?? "Budget",
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
      delivery: textOrNull(current["delivery"]),
      networkPriority: textOrNull(current["network_priority"]),
      sharedBudget: textOrNull(current["shared_budget"]),
    },
    daysLeft: typeof days === "number" && Number.isInteger(days) && days > 0 ? days : null,
    destination: parseView(value["destination"]),
    name: textOrNull(value["name"]),
    problem: textOrNull(value["problem"]),
    removesBudget: value["removes_budget"] === true,
    requested: Object.fromEntries(
      BUDGET_SETTINGS.flatMap((setting) => {
        const item = textOrNull(requested[setting])
        return item ? [[setting, setting === "amount" ? canonicalMoney(item) : item]] : []
      })
    ),
    spendThisMonth: money(value["spend_this_month"]),
  }
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseUpdateBudgetsArgs(value: unknown): UpdateBudgetsArgs | null {
  const parsed = parseCheckedEntries(value, "changes", parseChange, parseCheck)
  return parsed && { accounts: parsed.accounts, changes: parsed.entries, checks: parsed.checks }
}

/** The settings a change sets, in the server's card terms. */
function requestedOf(change: BudgetChange): Partial<Record<BudgetSetting, string>> {
  return {
    ...(change.amount ? { amount: change.amount } : {}),
    ...(change.delivery ? { delivery: change.delivery } : {}),
    ...(change.sharedBudget ? { shared_budget: change.sharedBudget } : {}),
    ...(change.networkPriority ? { network_priority: networkCode(change.networkPriority) } : {}),
  }
}

function rowOf(change: BudgetChange, check: BudgetCheck | undefined, cancelled: boolean) {
  const live = check && !check.unavailable ? check : null
  const requested = requestedOf(change)
  // Google answered for the change it was checked with, so an edit waits for a new check.
  const checked = live !== null && JSON.stringify(live.requested) === JSON.stringify(requested)
  const was = live
    ? {
        amount: live.current.amount,
        delivery: live.current.delivery,
        networkPriority: live.current.networkPriority,
      }
    : undefined
  const unchanged =
    live !== null &&
    (change.amount === null || change.amount === live.current.amount) &&
    (change.delivery === null || change.delivery === live.current.delivery) &&
    (change.sharedBudget === null || change.sharedBudget === live.current.sharedBudget) &&
    (requested.network_priority === undefined ||
      requested.network_priority === live.current.networkPriority)
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
    networkPriority: change.networkPriority,
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
    // A budget names the campaigns it funds, so a campaign row is counted by name too.
    campaigns: new Set(
      live.flatMap((row) =>
        (row.kind === "campaign"
          ? [row.name]
          : (row.budget?.campaigns.map((item) => item.name) ?? [])
        ).map((name) => `${row.customerId}/${name}`)
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

/** The `changes` value with each chosen change's entry replaced. */
export function editedBudgetChanges(
  args: UpdateBudgetsArgs,
  ids: ReadonlySet<string>,
  edit: (change: BudgetChange) => Record<string, unknown>
): Record<string, unknown>[] {
  return args.changes.map((change) => (ids.has(change.key) ? edit(change) : change.entry))
}

export function withAmount(change: BudgetChange, amount: string): Record<string, unknown> {
  // A move onto a shared budget can't also set an amount.
  return change.sharedBudget === null ? { ...change.entry, amount } : change.entry
}

export function withDelivery(change: BudgetChange, value: Delivery): Record<string, unknown> {
  return { ...change.entry, delivery: value }
}

export function withNetworkPriority(
  change: BudgetChange,
  value: NetworkPriority | "account_default"
): Record<string, unknown> {
  // A move onto a shared budget can't also set a network order.
  if (change.sharedBudget !== null) return change.entry
  const priority =
    value === "account_default"
      ? value
      : {
          first: value.first,
          then: value.then.map((item) =>
            item.cap === null
              ? { network: item.network }
              : { cap_percent: item.cap, network: item.network }
          ),
        }
  return { ...change.entry, network_priority: priority }
}

/** The network order a row asks for, as the server codes it; null when it asks for none. */
export function requestedNetworkOrder(row: BudgetRow): string | null {
  return row.networkPriority ? networkCode(row.networkPriority) : null
}

export function withSharedBudget(
  change: BudgetChange,
  reference: Record<string, unknown>
): Record<string, unknown> {
  return { ...change.entry, use_shared_budget: reference }
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
  return changesBlock(
    budgetCounts(budgetRows(args, checked)),
    budgetsNeedCheck(args, checked),
    "These budgets already have these settings."
  )
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
  if (setting === "network_priority") return networkOrderText(value)
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

// The campaigns a shared budget's parent row names; the count covers the rest.
const FUNDS_NAMED = 3

/** Who a shared budget funds, such as "Funds Boots, Socks, and 2 more". */
function fundsText(budget: BudgetView): string | null {
  const names = budget.campaigns.slice(0, FUNDS_NAMED).map((campaign) => campaign.name)
  if (names.length === 0) return null
  const more = budget.campaignCount - names.length
  return more > 0
    ? `Funds ${names.join(", ")}, and ${String(more)} more`
    : `Funds ${names.join(", ")}`
}

/** One row per campaign, or per shared budget with the campaigns it funds under its name. */
export function budgetParents(
  rows: readonly BudgetRow[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>,
  showAccount: boolean
): ParentRow[] {
  return rows.map((row) => {
    const funded = row.kind === "budget" && row.budget?.shared ? fundsText(row.budget) : null
    const account = showAccount ? (accounts.get(row.customerId)?.label ?? null) : null
    const problem = !row.cancelled && row.problem !== null
    return {
      cancelled: row.cancelled,
      context: [funded, account].filter((part) => part !== null).join(" · ") || null,
      key: row.id,
      name: row.name,
      problems: problem ? 1 : 0,
      values: {
        budget: row.sharedBudget
          ? `${budgetKindText(row)} → ${row.sharedBudgetLabel ?? "Shared budget"}`
          : budgetKindText(row),
      },
    }
  })
}

export function budgetsPrompt(args: UpdateBudgetsArgs): string {
  const rows = budgetRows(args, args)
  if (rows.length === 0) return "Nothing is left to change."
  const sole = soleRow(rows)
  if (sole) {
    const currency = budgetCurrency(args, sole)
    if (sole.sharedBudget)
      return `Move ${sole.name} onto ${sole.sharedBudgetLabel ?? "a shared budget"}.`
    if (sole.amount)
      return `Set the daily budget of ${sole.name} to ${moneyText(sole.amount, currency)}.`
    if (sole.networkPriority) return `Change which networks ${sole.name} spends on first.`
    return `Change how ${sole.name} spends its budget.`
  }
  const where = accountsText(
    args.accounts,
    args.changes.map((change) => change.customerId)
  )
  return `Change ${approvalCountLine(rows.length, "budget")} in ${where}.`
}

/** Names the change when there is only one; otherwise counts what's sent. */
export function budgetsApproveLabel(args: UpdateBudgetsArgs): string {
  const rows = budgetRows(args, args)
  const sole = soleRow(rows)
  if (sole && !sole.unchanged) return sole.sharedBudget ? "Move Campaign" : "Change Budget"
  return applyChangesLabel(budgetCounts(rows).apply)
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
