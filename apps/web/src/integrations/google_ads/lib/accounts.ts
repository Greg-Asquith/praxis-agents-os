// apps/web/src/integrations/google_ads/lib/accounts.ts

import {
  CURRENCY_CODE_PATTERN,
  googleAdsId,
  textOrNull,
} from "@/integrations/google_ads/lib/field-values"
import { isOneOf, isRecord } from "@/lib/guards"

export type GoogleAdsApprovalAccount = { currencyCode: string; label: string; timeZone: string }

export type GoogleAdsBillingState =
  | "not_monthly_invoicing"
  | "setup_pending"
  | "no_active_limit"
  | "active"
  | "running_low"
  | "limit_reached"

const BILLING_STATES: ReadonlySet<GoogleAdsBillingState> = new Set([
  "not_monthly_invoicing",
  "setup_pending",
  "no_active_limit",
  "active",
  "running_low",
  "limit_reached",
])

type GoogleAdsSpendingLimit = {
  accountBudgetId: string
  ends: string | null
  // Null when the limit has no ceiling.
  left: string | null
  limit: string | null
  served: string
}

type GoogleAdsPendingLimitChange = { kind: string; limit: string | null }

export type GoogleAdsAccountBilling = {
  activeLimit: GoogleAdsSpendingLimit | null
  billingSetupId: string | null
  paymentsAccountId: string | null
  paymentsAccountName: string | null
  paymentsProfileName: string | null
  pendingChanges: GoogleAdsPendingLimitChange[]
  queuedLimits: number
  state: GoogleAdsBillingState
}

export type GoogleAdsAccountOverview = {
  autoTaggingEnabled: boolean | null
  billing: GoogleAdsAccountBilling | null
  costThisMonth: string | null
  costToday: string | null
  currency: string
  customerId: string
  manager: boolean
  name: string | null
  status: string
  timeZone: string
}

const MONEY_PATTERN = /^-?\d+(?:\.\d+)?$/

// Reads the trusted `_accounts` approval projection, keyed by customer ID.
export function parseApprovalAccounts(value: unknown): Map<string, GoogleAdsApprovalAccount> {
  const accounts = new Map<string, GoogleAdsApprovalAccount>()
  if (!Array.isArray(value)) return accounts
  for (const item of value) {
    if (!isRecord(item)) continue
    const customerId = googleAdsId(item["customer_id"])
    const { currency, name, time_zone: timeZone } = item
    if (
      !customerId ||
      typeof name !== "string" ||
      !name.trim() ||
      typeof currency !== "string" ||
      !CURRENCY_CODE_PATTERN.test(currency) ||
      typeof timeZone !== "string" ||
      !timeZone.trim()
    )
      continue
    accounts.set(customerId, { currencyCode: currency, label: name.trim(), timeZone })
  }
  return accounts
}

/** Reads a request's entries with the trusted `_accounts` and `_checks` beside them.

Null when the request is malformed or names an entry twice.
 */
export function parseCheckedEntries<T extends { key: string }, C>(
  value: unknown,
  field: string,
  parseEntry: (entry: unknown) => T | null,
  parseCheck: (check: unknown) => C
): {
  accounts: Map<string, GoogleAdsApprovalAccount>
  checks: Map<string, C>
  entries: T[]
} | null {
  if (!isRecord(value) || !Array.isArray(value[field])) return null
  const entries: T[] = []
  const keys = new Set<string>()
  for (const item of value[field]) {
    const entry = parseEntry(item)
    if (entry === null || keys.has(entry.key)) return null
    keys.add(entry.key)
    entries.push(entry)
  }
  const rawChecks = isRecord(value["_checks"]) ? value["_checks"] : {}
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    checks: new Map(Object.entries(rawChecks).map(([key, check]) => [key, parseCheck(check)])),
    entries,
  }
}

/** The account a request changes by name, or how many accounts when there are several. */
export function accountsText(
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>,
  customerIds: Iterable<string>
): string {
  const ids = new Set(customerIds)
  const [id] = ids
  return ids.size === 1
    ? (accounts.get(id ?? "")?.label ?? "Google Ads")
    : `${String(ids.size)} accounts`
}

export function parseGoogleAdsAccountOverview(value: unknown): GoogleAdsAccountOverview | null {
  if (!isRecord(value)) return null
  const customerId = googleAdsId(value["customer_id"])
  const { currency, status, time_zone: timeZone, manager } = value
  const name = value["name"] ?? null
  const autoTagging = value["auto_tagging_enabled"] ?? null
  const costToday = value["cost_today"] ?? null
  const costThisMonth = value["cost_this_month"] ?? null
  const billing = value["billing"] == null ? null : parseBilling(value["billing"])
  if (
    billing === undefined ||
    !customerId ||
    (name !== null && typeof name !== "string") ||
    typeof status !== "string" ||
    typeof currency !== "string" ||
    !CURRENCY_CODE_PATTERN.test(currency) ||
    typeof timeZone !== "string" ||
    typeof manager !== "boolean" ||
    (autoTagging !== null && typeof autoTagging !== "boolean") ||
    !isMoneyOrNull(costToday) ||
    !isMoneyOrNull(costThisMonth)
  ) {
    return null
  }
  return {
    autoTaggingEnabled: autoTagging,
    billing,
    costThisMonth,
    costToday,
    currency,
    customerId,
    manager,
    name,
    status,
    timeZone,
  }
}

// Undefined when the billing block is malformed.
function parseBilling(value: unknown): GoogleAdsAccountBilling | undefined {
  if (!isRecord(value) || !isOneOf(BILLING_STATES, value["state"])) return undefined
  const activeLimit = value["active_limit"] == null ? null : parseLimit(value["active_limit"])
  const { pending_changes: pending, queued_limits: queued } = value
  if (activeLimit === undefined || !Array.isArray(pending) || !Array.isArray(queued)) {
    return undefined
  }
  const pendingChanges: GoogleAdsPendingLimitChange[] = []
  for (const item of pending) {
    if (!isRecord(item) || typeof item["kind"] !== "string") return undefined
    const limit = item["limit"] ?? null
    if (!isMoneyOrNull(limit)) return undefined
    pendingChanges.push({ kind: item["kind"], limit })
  }
  const setup = isRecord(value["billing_setup"]) ? value["billing_setup"] : {}
  return {
    activeLimit,
    billingSetupId: googleAdsId(setup["billing_setup_id"]),
    paymentsAccountId: textOrNull(value["payments_account_id"]),
    paymentsAccountName: textOrNull(value["payments_account_name"]),
    paymentsProfileName: textOrNull(value["payments_profile_name"]),
    pendingChanges,
    queuedLimits: queued.length,
    state: value["state"],
  }
}

function parseLimit(value: unknown): GoogleAdsSpendingLimit | undefined {
  if (!isRecord(value) || !isRecord(value["account_budget"])) return undefined
  const accountBudgetId = googleAdsId(value["account_budget"]["account_budget_id"])
  const limit = value["limit"] ?? null
  const left = value["left"] ?? null
  const ends = value["ends"] ?? null
  const { served } = value
  if (
    !accountBudgetId ||
    !isMoneyOrNull(limit) ||
    !isMoneyOrNull(left) ||
    typeof served !== "string" ||
    !MONEY_PATTERN.test(served) ||
    (ends !== null && typeof ends !== "string")
  ) {
    return undefined
  }
  return { accountBudgetId, ends, left, limit, served }
}

function isMoneyOrNull(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && MONEY_PATTERN.test(value))
}
