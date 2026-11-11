// apps/web/src/integrations/google_ads/lib/accounts.ts

import { CURRENCY_CODE_PATTERN, googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type GoogleAdsApprovalAccount = { currencyCode: string; label: string; timeZone: string }

export type GoogleAdsAccountOverview = {
  autoTaggingEnabled: boolean | null
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
  if (
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

function isMoneyOrNull(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && MONEY_PATTERN.test(value))
}
