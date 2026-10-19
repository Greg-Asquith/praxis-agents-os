// apps/web/src/integrations/meta_ads/lib/targeting-edits.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { formatAudienceRange } from "@/integrations/meta_ads/lib/targeting"
import { itemName, targetingItems } from "@/integrations/meta_ads/lib/targeting-edit"
import { placeName } from "@/integrations/meta_ads/lib/targeting-sentence"
import { formatPercentageChange } from "@/lib/format"
import { isNonEmptyString, isOneOf, isRecord, isStringArray } from "@/lib/guards"

type Targeting = Record<string, unknown>
type Item = Record<string, unknown>
type Entry = Record<string, unknown>

/** Places and audiences the operator edits directly, as additions and removals. */
export type ListField = "locations" | "excluded_locations" | "audiences" | "excluded_audiences"

const LISTS: Record<ListField, { add: string; remove: string; place: boolean }> = {
  locations: { add: "add_locations", remove: "remove_locations", place: true },
  excluded_locations: {
    add: "add_excluded_locations",
    remove: "remove_excluded_locations",
    place: true,
  },
  audiences: { add: "add_audiences", remove: "remove_audiences", place: false },
  excluded_audiences: {
    add: "add_excluded_audiences",
    remove: "remove_excluded_audiences",
    place: false,
  },
}
const LIST_FIELDS = Object.keys(LISTS) as ListField[]

// Interest and language changes the card can drop and restore, but not add to.
type ChipKind = "add_detailed_items" | "remove_detailed_items" | "languages" | "detailed"

/** Settings the card edits in place, when the agent proposed them. */
export type ValueKey =
  | "location_types"
  | "age_min"
  | "age_max"
  | "genders"
  | "advantage_audience"
  | "eu_payer"
  | "eu_beneficiary"
export type EditValue = string | number | boolean

type Estimate = { lower: number; upper: number } | null

type TargetingCheck = {
  before: Targeting | null
  // The entry these checks were made for.
  requested: unknown
  problems: string[]
  // Effects that can cost results for a while.
  warnings: string[]
  notes: string[]
  // Sections Praxis keeps as they are, with what each holds.
  unmodelled: Record<string, string>
  specialCategory: boolean
  estimates: { before?: Estimate; after?: Estimate }
  unavailable: boolean
}

export type TargetingEdit = {
  id: string
  accountId: string
  name: string
  check: TargetingCheck | null
  // The entry as sent, so edits keep what the card doesn't change.
  raw: Entry
}

export type TargetingEditArgs = { edits: TargetingEdit[] }

/** One proposed interest or language change, kept when dropped so it can come back. */
export type TargetingChip = { kind: ChipKind; id: string; label: string; included: boolean }

/** One proposed ad set, kept when the operator drops it so it can come back. */
export type TargetingEditRow = {
  edit: TargetingEdit
  proposed: TargetingEdit
  included: boolean
  chips: TargetingChip[]
}

/** A place or audience as the card lists it now. */
export type ListItem = {
  id: string
  label: string
  detail: string | null
  // Added by this change, by the agent or the operator.
  added: boolean
  item: Item
}

/** Where one place or audience list stands with the change applied. */
export type ListState = {
  items: ListItem[]
  // Items the ad set has now that the change removes.
  removing: ListItem[]
  // Additions the agent proposed that the operator took out.
  leftOut: ListItem[]
}

export type TargetingEditChange =
  | { included: boolean }
  | { chip: TargetingChip }
  | { key: ValueKey; value: EditValue }
  | { entry: Entry }

export function parseTargetingEditArgs(value: unknown): TargetingEditArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const checks = isRecord(value["_checks"]) ? value["_checks"] : {}
  const edits: TargetingEdit[] = []
  for (const item of value["changes"]) {
    if (!isRecord(item) || !isRecord(item["ad_set"])) return null
    const reference = item["ad_set"]
    const id = reference["adset_id"]
    if (!isNonEmptyString(id)) return null
    edits.push({
      id,
      accountId: typeof reference["account_id"] === "string" ? reference["account_id"] : "",
      name: isNonEmptyString(reference["label"]) ? reference["label"] : id,
      check: parseCheck(checks[id]),
      raw: item,
    })
  }
  return { edits }
}

function parseCheck(value: unknown): TargetingCheck | null {
  if (!isRecord(value)) return null
  const strings = (key: string) => (isStringArray(value[key]) ? value[key] : [])
  const estimates = isRecord(value["estimates"]) ? value["estimates"] : {}
  const unmodelled = isRecord(value["unmodelled"]) ? value["unmodelled"] : {}
  return {
    before: isRecord(value["before"]) ? value["before"] : null,
    requested: value["requested"],
    problems: strings("problems"),
    warnings: strings("warnings"),
    notes: strings("notes"),
    unmodelled: Object.fromEntries(
      Object.entries(unmodelled).filter((entry): entry is [string, string] =>
        isNonEmptyString(entry[1])
      )
    ),
    specialCategory: value["special_category"] === true,
    estimates: {
      before: parseEstimate(estimates["before"]),
      after: parseEstimate(estimates["after"]),
    },
    unavailable: value["unavailable"] === true,
  }
}

function parseEstimate(value: unknown): Estimate {
  if (!isRecord(value)) return null
  const { lower, upper } = value
  return typeof lower === "number" && typeof upper === "number" ? { lower, upper } : null
}

/** Meta's estimate as words, such as "500K to 550K people", or null. */
export function estimateText(estimate: Estimate | undefined): string | null {
  return estimate ? formatAudienceRange(estimate.lower, estimate.upper) : null
}

/** How far the estimate moves, compared at the middle of each range, or null. */
export function estimateChange(edit: TargetingEdit): string | null {
  const { before, after } = edit.check?.estimates ?? {}
  if (!before || !after || !checkIsCurrent(edit)) return null
  const change = formatPercentageChange(
    (before.lower + before.upper) / 2,
    (after.lower + after.upper) / 2
  )
  return change === "—" ? null : change
}

function itemId(field: ListField, item: Item): string {
  return LISTS[field].place
    ? `${String(item["kind"])}:${String(item["key"])}`
    : String(item["audience_id"])
}

function itemLabel(field: ListField, item: Item): string {
  if (LISTS[field].place) return placeName(item)
  return isNonEmptyString(item["label"]) ? item["label"] : itemName(item)
}

const PLACE_KINDS: Record<string, string> = {
  country: "Country",
  region: "Region",
  city: "City",
  postcode: "Postcode",
}

function itemDetail(field: ListField, item: Item): string | null {
  if (LISTS[field].place) return PLACE_KINDS[String(item["kind"])] ?? null
  return typeof item["subtype"] === "string" && item["subtype"]
    ? item["subtype"].charAt(0).toUpperCase() + item["subtype"].slice(1).replaceAll("_", " ")
    : null
}

function listItem(field: ListField, item: Item, added: boolean): ListItem {
  return {
    id: itemId(field, item),
    label: itemLabel(field, item),
    detail: itemDetail(field, item),
    added,
    item,
  }
}

/** One list with the change applied: what stays, what goes, and what the operator left out. */
export function listState(row: TargetingEditRow, field: ListField): ListState {
  const { add, remove } = LISTS[field]
  const raw = row.edit.raw
  const before = targetingItems(row.edit.check?.before?.[field])
  const removed = new Set(targetingItems(raw[remove]).map((item) => itemId(field, item)))
  const adds = targetingItems(raw[add])
  const added = new Set(adds.map((item) => itemId(field, item)))
  const proposedAdds = row.included ? targetingItems(row.proposed.raw[add]) : []
  return {
    items: [
      ...before
        .filter((item) => !removed.has(itemId(field, item)))
        .map((item) => listItem(field, item, false)),
      ...adds.map((item) => listItem(field, item, true)),
    ],
    removing: targetingItems(raw[remove]).map((item) => {
      const now = before.find((candidate) => itemId(field, candidate) === itemId(field, item))
      return listItem(field, now ?? item, false)
    }),
    leftOut: proposedAdds
      .filter((item) => !added.has(itemId(field, item)))
      .map((item) => listItem(field, item, true)),
  }
}

/** True for an item the operator added, as opposed to the agent. */
export function addedByOperator(row: TargetingEditRow, field: ListField, item: ListItem): boolean {
  const proposed = targetingItems(row.proposed.raw[LISTS[field].add])
  return item.added && !proposed.some((candidate) => itemId(field, candidate) === item.id)
}

/** The entry after taking an item out of a list: dropping an addition, or removing it. */
export function withoutItem(entry: Entry, field: ListField, item: ListItem): Entry {
  const { add, remove } = LISTS[field]
  if (item.added)
    return {
      ...entry,
      [add]: targetingItems(entry[add]).filter((candidate) => itemId(field, candidate) !== item.id),
    }
  return { ...entry, [remove]: [...targetingItems(entry[remove]), removalOf(field, item.item)] }
}

/** The entry after putting an item in a list: undoing its removal, or adding it. */
export function withItem(entry: Entry, field: ListField, item: Item): Entry {
  const { add, remove } = LISTS[field]
  const id = itemId(field, item)
  const removals = targetingItems(entry[remove])
  if (removals.some((candidate) => itemId(field, candidate) === id))
    return {
      ...entry,
      [remove]: removals.filter((candidate) => itemId(field, candidate) !== id),
    }
  return { ...entry, [add]: [...targetingItems(entry[add]), additionOf(field, item)] }
}

/** True when the list already has this item, so a search shows it as added. */
export function listHas(state: ListState, field: ListField, item: Item): boolean {
  return state.items.some((candidate) => candidate.id === itemId(field, item))
}

// A place keeps only the fields the tool accepts; an audience is its reference unchanged.
function additionOf(field: ListField, item: Item): Item {
  if (!LISTS[field].place) return item
  const place: Item = { kind: item["kind"], key: item["key"], name: item["name"] ?? null }
  if (typeof item["country_code"] === "string") place["country_code"] = item["country_code"]
  return place
}

function removalOf(field: ListField, item: Item): Item {
  if (!LISTS[field].place) return item
  return { kind: item["kind"], key: item["key"], name: placeName(item) }
}

/** Who the ad set reaches once the entry applies to the targeting it has now. */
export function targetingAfter(before: Targeting, raw: Entry): Targeting {
  const after: Targeting = { ...before }
  for (const field of LIST_FIELDS) {
    const { add, remove } = LISTS[field]
    const removed = new Set(targetingItems(raw[remove]).map((item) => itemId(field, item)))
    after[field] = [
      ...targetingItems(before[field]).filter((item) => !removed.has(itemId(field, item))),
      ...targetingItems(raw[add]),
    ]
  }
  after["detailed"] = detailedAfter(before, raw)
  for (const key of ["location_types", "age_min", "genders", "advantage_audience"])
    if (raw[key] !== undefined && raw[key] !== null) after[key] = raw[key]
  if (raw["age_max"] !== undefined && raw["age_max"] !== null)
    after["age_max"] = raw["age_max"] === "none" ? null : raw["age_max"]
  if (Array.isArray(raw["languages"])) after["languages"] = raw["languages"]
  if (raw["languages"] === "all") after["languages"] = []
  return after
}

function detailedAfter(before: Targeting, raw: Entry): Item[][] {
  if (raw["detailed"] === "none") return []
  if (Array.isArray(raw["detailed"])) return raw["detailed"].map(targetingItems)
  const removed = new Set(
    isStringArray(raw["remove_detailed_items"]) ? raw["remove_detailed_items"] : []
  )
  const groups = (Array.isArray(before["detailed"]) ? before["detailed"] : []).map((group) =>
    targetingItems(group).filter((item) => !removed.has(String(item["key"])))
  )
  const addition = raw["add_detailed_items"]
  if (isRecord(addition) && typeof addition["group"] === "number") {
    const at = addition["group"] - 1
    if (at === groups.length) groups.push([])
    groups[at]?.push(...targetingItems(addition["items"]))
  }
  return groups.filter((group) => group.length > 0)
}

/** The proposed interest and language changes, each marked kept or dropped. */
function chipsFor(proposed: TargetingEdit, current: TargetingEdit | undefined): TargetingChip[] {
  const raw = proposed.raw
  const kept = current?.raw ?? raw
  const chips: TargetingChip[] = []
  const addition = raw["add_detailed_items"]
  const keptAddition = kept["add_detailed_items"]
  const keptKeys = new Set(
    targetingItems(isRecord(keptAddition) ? keptAddition["items"] : null).map((item) =>
      String(item["key"])
    )
  )
  for (const item of targetingItems(isRecord(addition) ? addition["items"] : null))
    chips.push({
      kind: "add_detailed_items",
      id: String(item["key"]),
      label: `+${itemName(item)}`,
      included: keptKeys.has(String(item["key"])),
    })
  const names = new Map(
    (Array.isArray(proposed.check?.before?.["detailed"]) ? proposed.check.before["detailed"] : [])
      .flatMap(targetingItems)
      .map((item) => [String(item["key"]), itemName(item)])
  )
  const keptRemovals = new Set(
    isStringArray(kept["remove_detailed_items"]) ? kept["remove_detailed_items"] : []
  )
  for (const key of isStringArray(raw["remove_detailed_items"]) ? raw["remove_detailed_items"] : [])
    chips.push({
      kind: "remove_detailed_items",
      id: key,
      label: `−${names.get(key) ?? key}`,
      included: keptRemovals.has(key),
    })
  for (const key of ["languages", "detailed"] as const)
    if (raw[key] !== undefined && raw[key] !== null)
      chips.push({
        kind: key,
        id: key,
        label: replacementLabel(key, raw[key]),
        included: kept[key] !== undefined && kept[key] !== null,
      })
  return chips
}

function replacementLabel(key: "languages" | "detailed", value: unknown): string {
  if (key === "languages")
    return Array.isArray(value) ? `Set ${String(value.length)} Languages` : "All Languages"
  return Array.isArray(value) ? "Replace Interests" : "Remove All Interests"
}

/** The proposed ad sets with the ones the operator dropped, in the proposed order. */
export function targetingEditRows(
  proposed: TargetingEditArgs,
  current: TargetingEditArgs
): TargetingEditRow[] {
  const kept = new Map(current.edits.map((edit) => [edit.id, edit]))
  return proposed.edits.map((edit) => {
    const edited = kept.get(edit.id)
    return {
      edit: edited ?? edit,
      proposed: edit,
      included: edited !== undefined,
      chips: chipsFor(edit, edited),
    }
  })
}

/** The `changes` argument after one edit to one ad set, or including or dropping it. */
export function editTargeting(
  rows: readonly TargetingEditRow[],
  id: string,
  change: TargetingEditChange
): Entry[] {
  return rows.flatMap((row) => {
    const same = row.edit.id === id
    const included = same && "included" in change ? change.included : row.included
    if (!included) return []
    if (!same || "included" in change) return [row.edit.raw]
    if ("entry" in change) return [change.entry]
    if ("key" in change) return [{ ...row.edit.raw, [change.key]: change.value }]
    return [withChip(row, change.chip)]
  })
}

/** Rebuilds the chip's list from the proposal, so a restored item returns to its place. */
function withChip(row: TargetingEditRow, toggled: TargetingChip): Entry {
  const included = (chip: TargetingChip) =>
    chip.kind === toggled.kind && chip.id === toggled.id ? !chip.included : chip.included
  const kept = new Set(
    row.chips.filter((chip) => chip.kind === toggled.kind && included(chip)).map((chip) => chip.id)
  )
  const proposed = row.proposed.raw
  const raw = { ...row.edit.raw }
  if (toggled.kind === "languages" || toggled.kind === "detailed")
    raw[toggled.kind] = kept.size > 0 ? proposed[toggled.kind] : null
  else if (toggled.kind === "remove_detailed_items") {
    const removals = proposed[toggled.kind]
    raw[toggled.kind] = (isStringArray(removals) ? removals : []).filter((key) => kept.has(key))
  } else {
    const value = proposed[toggled.kind]
    const addition = isRecord(value) ? value : {}
    const items = targetingItems(addition["items"]).filter((item) => kept.has(String(item["key"])))
    raw[toggled.kind] = items.length > 0 ? { ...addition, items } : null
  }
  return raw
}

/** The settings the agent proposed that the card edits in place, as the entry holds them. */
export function editValues(edit: TargetingEdit): Partial<Record<ValueKey, EditValue>> {
  const values: Partial<Record<ValueKey, EditValue>> = {}
  for (const key of [
    "location_types",
    "age_min",
    "age_max",
    "genders",
    "advantage_audience",
    "eu_payer",
    "eu_beneficiary",
  ] as const) {
    const value = edit.raw[key]
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean")
      values[key] = value
  }
  return values
}

// Section summaries, shared by the card and the result table.

const GENDER_WORDS: Record<string, string> = { all: "All", men: "Men", women: "Women" }

function names(items: Item[], place: boolean): string {
  return items.map((item) => (place ? placeName(item) : itemName(item))).join(", ")
}

/** Where the ad set's ads show, as names. */
export function placesText(targeting: Targeting): string {
  const places = names(targetingItems(targeting["locations"]), true) || "No places"
  const excluded = names(targetingItems(targeting["excluded_locations"]), true)
  return excluded ? `${places} · Not in ${excluded}` : places
}

export function peopleText(targeting: Targeting): string {
  const min = typeof targeting["age_min"] === "number" ? targeting["age_min"] : 18
  const max = typeof targeting["age_max"] === "number" ? String(targeting["age_max"]) : "65+"
  return `${String(min)} to ${max} · ${GENDER_WORDS[String(targeting["genders"])] ?? "All"}`
}

export function interestsText(targeting: Targeting): string {
  const groups = (Array.isArray(targeting["detailed"]) ? targeting["detailed"] : []).map((group) =>
    targetingItems(group)
      .map((item) => itemName(item))
      .join(" or ")
  )
  return groups.filter(Boolean).join(", and ") || "No interests"
}

export function audiencesText(targeting: Targeting): string {
  const inside = names(targetingItems(targeting["audiences"]), false) || "Anyone"
  const outside = names(targetingItems(targeting["excluded_audiences"]), false)
  return outside ? `${inside} · Not in ${outside}` : inside
}

export function widenText(targeting: Targeting): string {
  return targeting["advantage_audience"] === false ? "Off" : "On"
}

/** The changed places, audiences, and settings on one line, for the ad set's closed row. */
export function editSummary(row: TargetingEditRow): string {
  const parts: string[] = []
  const lists: [string, ListField[]][] = [
    ["Locations", ["locations", "excluded_locations"]],
    ["Audiences", ["audiences", "excluded_audiences"]],
  ]
  for (const [title, fields] of lists) {
    const changes = fields.flatMap((field) => {
      const state = listState(row, field)
      const prefix = field.startsWith("excluded") ? "Not in " : ""
      return [
        ...state.items.filter((item) => item.added).map((item) => `${prefix}+${item.label}`),
        ...state.removing.map((item) => `${prefix}−${item.label}`),
      ]
    })
    if (changes.length > 0) parts.push(`${title}: ${changes.join(", ")}`)
  }
  const values = editValues(row.edit)
  const after = targetingAfter(row.edit.check?.before ?? {}, row.edit.raw)
  if (["age_min", "age_max", "genders"].some((key) => key in values))
    parts.push(`Age and Gender: ${peopleText(after)}`)
  const chips = row.chips.filter((chip) => chip.included)
  if (chips.length > 0) parts.push(`Interests: ${chips.map((chip) => chip.label).join(", ")}`)
  if ("advantage_audience" in values) parts.push(`Widen Audience: ${widenText(after)}`)
  return parts.join(" · ")
}

/** True when the entry still makes at least one change. */
function hasChange(raw: Entry): boolean {
  return Object.entries(raw).some(
    ([key, value]) =>
      key !== "ad_set" &&
      key !== "eu_payer" &&
      key !== "eu_beneficiary" &&
      value !== null &&
      value !== undefined &&
      !(Array.isArray(value) && value.length === 0)
  )
}

/** The entry with empty values dropped and keys sorted, so equal entries compare equal. */
function comparable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(comparable)
  if (!isRecord(value)) return value
  return Object.fromEntries(
    Object.keys(value)
      .filter((key) => {
        const item = value[key]
        return item !== null && item !== undefined && !(Array.isArray(item) && item.length === 0)
      })
      .sort()
      .map((key) => [key, comparable(value[key])])
  )
}

/** True when the server's checks were made for exactly the entry now on the card. */
function checkIsCurrent(edit: TargetingEdit): boolean {
  const check = edit.check
  if (check === null || check.unavailable) return false
  const { ad_set: _reference, ...entry } = edit.raw
  return JSON.stringify(comparable(entry)) === JSON.stringify(comparable(check.requested))
}

export function currentProblems(edit: TargetingEdit): string[] {
  return checkIsCurrent(edit) ? (edit.check?.problems ?? []) : []
}

export function targetingWarnings(edit: TargetingEdit): string[] {
  return checkIsCurrent(edit) ? (edit.check?.warnings ?? []) : []
}

/** Notes under an ad set; a note on values since edited could be wrong, so it says so. */
export function targetingNotes(edit: TargetingEdit): string[] {
  const check = edit.check
  if (check === null || check.unavailable)
    return ["This ad set couldn't be checked before approval. Meta checks it when you approve."]
  if (!checkIsCurrent(edit))
    return ["You changed this targeting, so Meta checks it again when you approve."]
  return check.notes
}

/** Meta's estimate after the change, only while it was made for the entry on the card. */
export function afterEstimate(edit: TargetingEdit): string | null {
  return checkIsCurrent(edit) ? estimateText(edit.check?.estimates.after) : null
}

/** Why one ad set's entry can't be sent as it is, or null. */
export function entryProblem(edit: TargetingEdit): string | null {
  if (!hasChange(edit.raw)) return "Keep at least one change, or switch this ad set off."
  const after = targetingAfter(edit.check?.before ?? {}, edit.raw)
  if (edit.check?.before && targetingItems(after["locations"]).length === 0)
    return "Keep at least one place."
  const { age_min: min, age_max: max } = after
  if (typeof min === "number" && typeof max === "number" && max < min)
    return "Set the maximum age at or above the minimum."
  for (const key of ["eu_payer", "eu_beneficiary"] as const) {
    const value = edit.raw[key]
    if (typeof value === "string" && !value.trim()) return "Enter who pays and who benefits."
  }
  return null
}

/** Why the proposed changes can't be approved yet, or null. */
export function targetingEditProblem(args: TargetingEditArgs | null): string | null {
  if (args === null) return null
  if (args.edits.length === 0) return "Keep at least one ad set, or decline this request."
  if (args.edits.some((edit) => entryProblem(edit) !== null))
    return "Correct the highlighted ad sets before approving."
  if (args.edits.some((edit) => currentProblems(edit).length > 0))
    return "Change the ad sets Meta won't accept or switch them off, or decline this request."
  return null
}

export function targetingEditDetails(args: TargetingEditArgs | null): FanOutDetail[] {
  if (args === null) return []
  return [{ label: "Ad sets", value: String(args.edits.length) }]
}

// Result models

type OutcomeToken = "updated" | "already_set" | "failed" | "unverified"
const OUTCOMES: ReadonlySet<OutcomeToken> = new Set([
  "updated",
  "already_set",
  "failed",
  "unverified",
])

/** Each changed section's title in the result table, and how to describe it. */
export const RESULT_SECTIONS: Record<string, { title: string; text: (t: Targeting) => string }> = {
  locations: { title: "Locations", text: placesText },
  excluded_locations: { title: "Locations", text: placesText },
  ages: { title: "Age and Gender", text: peopleText },
  genders: { title: "Age and Gender", text: peopleText },
  languages: {
    title: "Languages",
    text: (t) =>
      Array.isArray(t["languages"]) && t["languages"].length > 0
        ? `${String(t["languages"].length)} languages`
        : "All languages",
  },
  detailed: { title: "Interests", text: interestsText },
  audiences: { title: "Audiences", text: audiencesText },
  excluded_audiences: { title: "Audiences", text: audiencesText },
  advantage_audience: { title: "Widen Audience", text: widenText },
}
const SECTION_KEYS: ReadonlySet<string> = new Set(Object.keys(RESULT_SECTIONS))

type TargetingOutcome = {
  id: string
  name: string
  before: Targeting
  requested: Targeting
  sections: string[]
  outcome: OutcomeToken
  errorCode: string | null
  message: string | null
}

export type TargetingEditResult = { accountId: string; adSets: TargetingOutcome[] }

export function parseTargetingEditResult(value: unknown): TargetingEditResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !Array.isArray(value["ad_sets"])
  )
    return null
  const adSets: TargetingOutcome[] = []
  for (const item of value["ad_sets"]) {
    if (
      !isRecord(item) ||
      !isNonEmptyString(item["adset_id"]) ||
      !isOneOf(OUTCOMES, item["outcome"]) ||
      !isRecord(item["before"]) ||
      !isRecord(item["requested"]) ||
      !Array.isArray(item["changes"])
    )
      return null
    const text = (key: string) => (typeof item[key] === "string" ? item[key] : null)
    adSets.push({
      id: item["adset_id"],
      name: isNonEmptyString(item["name"]) ? item["name"] : item["adset_id"],
      before: item["before"],
      requested: item["requested"],
      sections: item["changes"].flatMap((change) =>
        isRecord(change) && isOneOf(SECTION_KEYS, change["section"]) ? [change["section"]] : []
      ),
      outcome: item["outcome"],
      errorCode: text("error_code"),
      message: text("message"),
    })
  }
  return { accountId: value["account_id"], adSets }
}
