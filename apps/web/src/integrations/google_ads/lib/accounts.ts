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
