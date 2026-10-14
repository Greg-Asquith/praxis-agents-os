// apps/web/src/integrations/meta_ads/lib/targeting-sentence.ts

import { isRecord } from "@/lib/guards"

const LIST = new Intl.ListFormat("en", { type: "conjunction" })
const EITHER = new Intl.ListFormat("en", { type: "disjunction" })
const UNITS: Record<string, string> = { mile: "mi", kilometer: "km" }
const SPECIAL_CATEGORY =
  "Housing, employment, or financial ad: Meta allows ages 18 to 65+, all genders, and no postcodes."
const ADVANTAGE =
  "Advantage+ audience is on, so Meta may show ads to people outside this age and gender."

/** Describes a targeting draft in plain words, one sentence for who and one for each caveat. */
export function targetingSentences(
  targeting: unknown,
  { specialCategory = false }: { specialCategory?: boolean } = {}
): string[] {
  if (!isRecord(targeting)) return []
  const sentences = [`${who(targeting)} in ${places(targeting["locations"]) || "no location"}.`]
  const excluded = places(targeting["excluded_locations"])
  if (excluded) sentences.push(`Excludes ${excluded}.`)
  const groups: unknown[] = Array.isArray(targeting["detailed"]) ? targeting["detailed"] : []
  for (const group of groups) {
    const names = items(group).map(itemName)
    if (names.length > 0) sentences.push(`Must match ${EITHER.format(names)}.`)
  }
  const audiences = items(targeting["audiences"]).map(itemName)
  if (audiences.length > 0) sentences.push(`In ${EITHER.format(audiences)}.`)
  const excludedAudiences = items(targeting["excluded_audiences"]).map(itemName)
  if (excludedAudiences.length > 0) sentences.push(`Not in ${LIST.format(excludedAudiences)}.`)
  if (specialCategory) sentences.push(SPECIAL_CATEGORY)
  if (targeting["advantage_audience"] !== false) sentences.push(ADVANTAGE)
  return sentences
}

function who(targeting: Record<string, unknown>): string {
  const people =
    { men: "Men", women: "Women" }[String(targeting["genders"])] ?? "People of all genders"
  const min = typeof targeting["age_min"] === "number" ? targeting["age_min"] : 18
  const max = typeof targeting["age_max"] === "number" ? targeting["age_max"] : null
  return `${people} aged ${String(min)} to ${max === null ? "65+" : String(max)}`
}

function places(value: unknown): string {
  return LIST.format(
    items(value).map((location) => {
      const name = itemName(location)
      const unit = UNITS[String(location["radius_unit"])]
      return typeof location["radius"] === "number" && unit
        ? `${name} (+${String(location["radius"])} ${unit})`
        : name
    })
  )
}

function items(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function itemName(value: Record<string, unknown>): string {
  for (const key of ["name", "label", "key"]) {
    const text = value[key]
    if (typeof text === "string" && text.trim()) return text.trim()
  }
  return "Unnamed"
}
