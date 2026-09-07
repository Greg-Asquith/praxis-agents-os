// apps/web/src/integrations/google_ads/lib/field-values.ts

import { isRecord } from "@/lib/guards"

export const GOOGLE_ADS_ID_PATTERN = /^\d+$/
export const CURRENCY_CODE_PATTERN = /^[A-Z]{3}$/

export function googleAdsId(value: unknown): string | null {
  return typeof value === "string" && GOOGLE_ADS_ID_PATTERN.test(value) ? value : null
}

// Parsers preserve literal values. Callers own defaults, trimming, and scalar clears.
export function parseGoogleAdsMoney(value: unknown, minimumMicros = 1n): string | undefined {
  if (typeof value !== "string" || !/^\d+(?:\.\d{1,6})?$/.test(value)) return undefined
  const [whole = "0", fraction = ""] = value.split(".")
  const micros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"))
  return micros >= minimumMicros && micros <= 9_223_372_036_854_775_807n ? value : undefined
}

export function parseGoogleAdsUrlList(value: unknown): string[] | undefined {
  if (!Array.isArray(value) || value.length > 10) return undefined
  return value.every(
    (url) => typeof url === "string" && url.length <= 2048 && /^https?:\/\/\S+$/i.test(url)
  )
    ? value
    : undefined
}

export function parseGoogleAdsCustomParameters(value: unknown): Record<string, string> | undefined {
  let entries: [unknown, unknown][]
  if (Array.isArray(value)) {
    if (value.length > 8) return undefined
    entries = []
    for (const item of value) {
      if (!isRecord(item)) return undefined
      entries.push([item["key"], item["value"]])
    }
  } else {
    if (!isRecord(value)) return undefined
    entries = Object.entries(value)
    if (entries.length > 8) return undefined
  }
  const normalized = new Set<string>()
  const parameters: [string, string][] = []
  for (const [key, item] of entries) {
    if (
      typeof key !== "string" ||
      typeof item !== "string" ||
      !/^[A-Za-z0-9]{1,16}$/.test(key) ||
      new TextEncoder().encode(item).length > 200 ||
      normalized.has(key.toLowerCase())
    )
      return undefined
    normalized.add(key.toLowerCase())
    parameters.push([key, item])
  }
  return Object.fromEntries(parameters)
}
