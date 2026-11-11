// apps/web/src/integrations/google_ads/lib/field-values.ts

const GOOGLE_ADS_ID_PATTERN = /^\d+$/
export const CURRENCY_CODE_PATTERN = /^[A-Z]{3}$/

export function googleAdsId(value: unknown): string | null {
  return typeof value === "string" && GOOGLE_ADS_ID_PATTERN.test(value) ? value : null
}

/** The value when it's text with something in it, else null. */
export function textOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

// Parsers preserve literal values. Callers own defaults, trimming, and scalar clears.
export function parseGoogleAdsMoney(value: unknown, minimumMicros = 1n): string | undefined {
  if (typeof value !== "string" || !/^\d+(?:\.\d{1,6})?$/.test(value)) return undefined
  const [whole = "0", fraction = ""] = value.split(".")
  const micros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"))
  return micros >= minimumMicros && micros <= 9_223_372_036_854_775_807n ? value : undefined
}

export function isGoogleAdsUrl(value: string): boolean {
  return /^https?:\/\/\S+$/i.test(value)
}

export function parseGoogleAdsUrlList(value: unknown): string[] | undefined {
  if (!Array.isArray(value) || value.length > 10) return undefined
  return value.every((url) => typeof url === "string" && url.length <= 2048 && isGoogleAdsUrl(url))
    ? value
    : undefined
}
