// apps/web/src/integrations/google_ads/lib/targeting-search.ts

import { isRecord } from "@/lib/guards"

type TargetingOption = {
  key: string
  kind: "location" | "language"
  name: string
  reach: number | null
  region: string | null
  targetType: string | null
}

export type TargetingSearchResult = { options: TargetingOption[]; truncated: boolean }

function parseOption(value: unknown): TargetingOption | null {
  if (!isRecord(value)) return null
  const { key, kind, name, reach, region, target_type: targetType } = value
  if (
    typeof key !== "string" ||
    typeof name !== "string" ||
    (kind !== "location" && kind !== "language")
  )
    return null
  return {
    key,
    kind,
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

const REACH_FORMAT = new Intl.NumberFormat("en-GB", {
  maximumFractionDigits: 1,
  notation: "compact",
})

export function reachText(reach: number | null): string {
  return reach === null ? "—" : REACH_FORMAT.format(reach)
}
