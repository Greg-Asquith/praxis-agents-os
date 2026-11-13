// apps/web/src/integrations/google_ads/lib/targeting-search.ts

import { isRecord } from "@/lib/guards"

const AUDIENCE_KINDS = ["user_list", "user_interest", "custom_audience", "combined_audience"]

type TargetingOption = {
  // Google's grouping for an audience, such as In-Market or Your Data.
  category: string | null
  key: string
  kind: "location" | "language" | "audience"
  name: string
  reach: number | null
  region: string | null
  targetType: string | null
}

export type TargetingSearchResult = { options: TargetingOption[]; truncated: boolean }

function parseOption(value: unknown): TargetingOption | null {
  if (!isRecord(value)) return null
  const { category, key, kind, name, reach, region, target_type: targetType } = value
  const audience = typeof kind === "string" && AUDIENCE_KINDS.includes(kind)
  if (
    typeof key !== "string" ||
    typeof name !== "string" ||
    (kind !== "location" && kind !== "language" && !audience)
  )
    return null
  return {
    category: typeof category === "string" ? category : null,
    key,
    kind: audience ? "audience" : (kind as "location" | "language"),
    name,
    reach: typeof reach === "number" ? reach : null,
    region: typeof region === "string" ? region : null,
    targetType: typeof targetType === "string" ? targetType : null,
  }
}

export function parseTargetingSearch(value: unknown): TargetingSearchResult | null {
  if (!isRecord(value) || !Array.isArray(value["options"])) return null
  const options = value["options"].map(parseOption)
  if (options.some((option) => option === null)) return null
  return {
    options: options.filter((option) => option !== null),
    truncated: value["truncated"] === true,
  }
}

const REACH_FORMAT = new Intl.NumberFormat("en", {
  maximumFractionDigits: 1,
  notation: "compact",
})

export function reachText(reach: number | null): string {
  return reach === null ? "—" : REACH_FORMAT.format(reach)
}
