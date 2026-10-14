// apps/web/src/integrations/meta_ads/lib/targeting.ts

import { isNonEmptyString, isNonNegativeInteger, isRecord, isStringArray } from "@/lib/guards"

type MetaAdsTargetingOption = {
  kind: string
  key: string
  name: string
  description: string | null
  size: string | null
}

export type MetaAdsTargetingSearch = {
  options: MetaAdsTargetingOption[]
  truncated: boolean
}

export type MetaAdsAudienceEstimate = {
  range: string | null
  notes: string[]
}

export const TARGETING_KIND_LABELS: Record<string, string> = {
  country: "Country",
  region: "Region",
  city: "City",
  postcode: "Postcode",
  interest: "Interest",
  behavior: "Behaviour",
  demographic: "Demographic",
  language: "Language",
}
const AUDIENCE_SIZE = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 })

// Meta's ranges are approximate, and null when Meta has no estimate.
export function formatAudienceRange(lower: unknown, upper: unknown): string | null {
  if (!isNonNegativeInteger(lower) || !isNonNegativeInteger(upper)) return null
  if (lower === upper) return `about ${AUDIENCE_SIZE.format(lower)} people`
  return `${AUDIENCE_SIZE.format(lower)} to ${AUDIENCE_SIZE.format(upper)} people`
}

export function parseMetaAdsTargetingSearch(value: unknown): MetaAdsTargetingSearch | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["options"]) ||
    typeof value["truncated"] !== "boolean"
  )
    return null
  const options: MetaAdsTargetingOption[] = []
  for (const item of value["options"]) {
    if (!isRecord(item) || !isNonEmptyString(item["key"]) || !isNonEmptyString(item["name"]))
      return null
    const range = isRecord(item["audience_size_range"]) ? item["audience_size_range"] : {}
    options.push({
      kind: TARGETING_KIND_LABELS[String(item["kind"])] ?? "Other",
      key: item["key"],
      name: item["name"],
      description: isNonEmptyString(item["description"]) ? item["description"] : null,
      size: formatAudienceRange(range["lower"], range["upper"]),
    })
  }
  return { options, truncated: value["truncated"] }
}

export function parseMetaAdsAudienceEstimate(value: unknown): MetaAdsAudienceEstimate | null {
  if (!isRecord(value) || !isStringArray(value["notes"])) return null
  return {
    range: formatAudienceRange(value["users_lower_bound"], value["users_upper_bound"]),
    notes: value["notes"],
  }
}
