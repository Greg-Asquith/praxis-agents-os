// apps/web/src/integrations/google_ads/lib/accounts.ts

import { isRecord } from "@/lib/guards"
import { googleAdsId, CURRENCY_CODE_PATTERN } from "@/integrations/google_ads/lib/field-values"

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
      typeof currencyCode !== "string" ||
      !CURRENCY_CODE_PATTERN.test(currencyCode)
    )
      continue
    accounts.set(customerId, { currencyCode, label })
  }
  return accounts
}
