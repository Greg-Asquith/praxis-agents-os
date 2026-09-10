// apps/web/src/integrations/google_ads/lib/accounts.ts

import { CURRENCY_CODE_PATTERN, googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { formatGoogleAdsAccountId } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export type GoogleAdsAccount = {
  currencyCode: string
  customerId: string
  displayName: string
  enabled: boolean
  manager: boolean
  parentCustomerId: string | null
  status: string
  writable: boolean
}

export function parseAccountCurrencies(
  value: unknown
): Map<string, { currencyCode: string; label: string }> {
  const accounts = new Map<string, { currencyCode: string; label: string }>()
  if (!Array.isArray(value)) return accounts
  for (const item of value) {
    if (!isRecord(item)) continue
    const customerId = googleAdsId(item["customer_id"])
    const currencyCode = item["currency_code"]
    const label = item["label"]
    if (
      !customerId ||
      typeof label !== "string" ||
      !label.trim() ||
      typeof currencyCode !== "string" ||
      !CURRENCY_CODE_PATTERN.test(currencyCode)
    )
      continue
    accounts.set(customerId, { currencyCode, label })
  }
  return accounts
}

export function parseGoogleAdsAccounts(value: unknown): GoogleAdsAccount[] | null {
  if (!isRecord(value) || !Array.isArray(value["accounts"])) {
    return null
  }
  const accounts: GoogleAdsAccount[] = []
  for (const item of value["accounts"]) {
    if (
      !isRecord(item) ||
      typeof item["customer_id"] !== "string" ||
      typeof item["display_name"] !== "string" ||
      (item["parent_customer_id"] !== null && typeof item["parent_customer_id"] !== "string") ||
      typeof item["manager"] !== "boolean" ||
      typeof item["currency_code"] !== "string" ||
      typeof item["status"] !== "string" ||
      typeof item["writable"] !== "boolean" ||
      typeof item["enabled"] !== "boolean"
    ) {
      return null
    }
    accounts.push({
      currencyCode: item["currency_code"],
      customerId: formatGoogleAdsAccountId(item["customer_id"]),
      displayName: item["display_name"],
      enabled: item["enabled"],
      manager: item["manager"],
      parentCustomerId: item["parent_customer_id"],
      status: item["status"],
      writable: item["writable"],
    })
  }
  return accounts
}
