// apps/web/src/integrations/meta_ads/lib/targeting-edit.ts

import { isRecord } from "@/lib/guards"

export type TargetingItem = Record<string, unknown>
type Targeting = Record<string, unknown>
type LocationField = "locations" | "excluded_locations"
type AudienceField = "audiences" | "excluded_audiences"
type ListField = LocationField | AudienceField

export function targetingItems(value: unknown): TargetingItem[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

/** The name a person would recognise for a location, interest, or audience. */
export function itemName(item: TargetingItem): string {
  for (const key of ["name", "label", "key"]) {
    const text = item[key]
    if (typeof text === "string" && text.trim()) return text.trim()
  }
  return "Unnamed"
}

// Each add returns `targeting` unchanged for an item already in the list.

/** Adds a place from a lookup, copying only the fields the targeting accepts. */
export function addLocation(
  targeting: Targeting,
  field: LocationField,
  place: TargetingItem
): Targeting {
  const current = targetingItems(targeting[field])
  if (current.some((item) => item["kind"] === place["kind"] && item["key"] === place["key"]))
    return targeting
  const added: TargetingItem = { kind: place["kind"], key: place["key"], name: place["name"] }
  if (typeof place["country_code"] === "string") added["country_code"] = place["country_code"]
  return { ...targeting, [field]: [...current, added] }
}

/** Adds an interest to the first group, whose items match with "or", or starts that group. */
export function addInterest(targeting: Targeting, interest: TargetingItem): Targeting {
  const groups = detailedGroups(targeting)
  if (groups.flat().some((item) => item["key"] === interest["key"])) return targeting
  const added: TargetingItem = { kind: "interest", key: interest["key"], name: interest["name"] }
  const [first = [], ...rest] = groups
  return { ...targeting, detailed: [[...first, added], ...rest] }
}

/** Removes one interest, behaviour, or demographic, and its group once it is empty. */
export function removeDetailed(targeting: Targeting, group: number, index: number): Targeting {
  const groups = detailedGroups(targeting).map((items, at) =>
    at === group ? items.filter((_, itemAt) => itemAt !== index) : items
  )
  return { ...targeting, detailed: groups.filter((items) => items.length > 0) }
}

export function detailedGroups(targeting: Targeting): TargetingItem[][] {
  const groups: unknown[] = Array.isArray(targeting["detailed"]) ? targeting["detailed"] : []
  return groups.map(targetingItems)
}

/** Adds an audience reference unchanged; audiences are kept as the lookup returned them. */
export function addAudience(
  targeting: Targeting,
  field: AudienceField,
  audience: TargetingItem
): Targeting {
  const current = targetingItems(targeting[field])
  if (current.some((item) => item["audience_id"] === audience["audience_id"])) return targeting
  return { ...targeting, [field]: [...current, audience] }
}

export function removeItem(targeting: Targeting, field: ListField, index: number): Targeting {
  return { ...targeting, [field]: targetingItems(targeting[field]).filter((_, at) => at !== index) }
}
