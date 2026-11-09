// apps/web/src/integrations/google_ads/lib/update-targeting.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type TargetField =
  "add_locations" | "exclude_locations" | "remove_locations" | "add_languages" | "remove_languages"
export type LocationSetting = "PRESENCE_OR_INTEREST" | "PRESENCE"
export type RadiusUnits = "MILES" | "KILOMETERS"

const MIN_BID_ADJUSTMENT = -90
const MAX_BID_ADJUSTMENT = 900
// Search campaigns can only remove languages; Google matches each ad's language.
const NO_LANGUAGE_ADDS = new Set(["SEARCH"])
const TARGET_FIELDS: readonly TargetField[] = [
  "add_locations",
  "exclude_locations",
  "remove_locations",
  "add_languages",
  "remove_languages",
]

export type Target = {
  bidAdjustment: number | null
  key: string
  name: string | null
  targetType: string | null
}

export type RadiusTarget = {
  bidAdjustment: number | null
  label: string | null
  latitude: number
  longitude: number
  radius: number
  units: RadiusUnits
}

export type TargetingChange = {
  campaignId: string
  // The change as received, so an edit keeps every field.
  entry: Record<string, unknown>
  key: string
  label: string
  radius: RadiusTarget[]
  removeRadius: string[]
  setting: LocationSetting | null
  targets: Record<TargetField, Target[]>
}

type LiveRadius = { criterionId: string; radius: number; units: RadiusUnits }
type ShownLocation = { bidAdjustment: number; excluded: boolean; key: string; name: string }
type ItemProblem = { field: string; key: string; message: string }

export type TargetingCheck =
  | { unavailable: true }
  | {
      unavailable: false
      alreadySet: number
      channel: string | null
      itemProblems: ItemProblem[]
      languages: { key: string; name: string }[]
      locationSetting: LocationSetting | null
      locationTotal: number
      locations: ShownLocation[]
      name: string
      problem: string | null
      radius: LiveRadius[]
      status: string | null
    }

export type UpdateTargetingArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  changes: TargetingChange[]
  checks: Map<string, TargetingCheck>
  names: { languages: Map<string, string>; locations: Map<string, string> }
}

export type CampaignRow = {
  alreadySet: boolean
  cancelled: boolean
  change: TargetingChange
  check: TargetingCheck | undefined
  // Needs a new check because this campaign's changes differ from what Google answered for.
  edited: boolean
  key: string
  name: string
  problems: string[]
}

export type TargetLine = {
  bidAdjustment: number | null
  count: number
  field: TargetField
  key: string
  name: string
  targetType: string | null
}

const UNAVAILABLE =
  "Google Ads couldn't check this campaign. Check again, or ask the agent to prepare the change again."

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function wholeNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null
}

function parseSetting(value: unknown): LocationSetting | null {
  return value === "PRESENCE" || value === "PRESENCE_OR_INTEREST" ? value : null
}

function parseTargets(value: unknown): Target[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item)) return []
    const key = googleAdsId(item["key"])
    return key === null
      ? []
      : [
          {
            bidAdjustment: wholeNumber(item["bid_adjustment"]),
            key,
            name: text(item["name"]),
            targetType: text(item["target_type"]),
          },
        ]
  })
}

function parseRadius(value: unknown): RadiusTarget[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item)) return []
    const { latitude, longitude, radius, units } = item
    if (
      typeof latitude !== "number" ||
      typeof longitude !== "number" ||
      typeof radius !== "number" ||
      (units !== "MILES" && units !== "KILOMETERS")
    )
      return []
    return [
      {
        bidAdjustment: wholeNumber(item["bid_adjustment"]),
        label: text(item["label"]),
        latitude,
        longitude,
        radius,
        units,
      },
    ]
  })
}

function parseChange(value: unknown): TargetingChange | null {
  if (!isRecord(value) || !isRecord(value["campaign"])) return null
  const customerId = googleAdsId(value["campaign"]["customer_id"])
  const campaignId = googleAdsId(value["campaign"]["campaign_id"])
  if (customerId === null || campaignId === null) return null
  const key = `customers/${customerId}/campaigns/${campaignId}`
  return {
    campaignId,
    entry: value,
    key,
    label: text(value["campaign"]["label"]) ?? `Campaign ${campaignId}`,
    radius: parseRadius(value["add_radius"]),
    removeRadius: Array.isArray(value["remove_radius"])
      ? value["remove_radius"].flatMap((id) => googleAdsId(id) ?? [])
      : [],
    setting: parseSetting(value["location_setting"]),
    targets: {
      add_languages: parseTargets(value["add_languages"]),
      add_locations: parseTargets(value["add_locations"]),
      exclude_locations: parseTargets(value["exclude_locations"]),
      remove_languages: parseTargets(value["remove_languages"]),
      remove_locations: parseTargets(value["remove_locations"]),
    },
  }
}

function parseCheck(value: unknown): TargetingCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const locations = Array.isArray(value["locations"]) ? value["locations"] : []
  const languages = Array.isArray(value["languages"]) ? value["languages"] : []
  const radius = Array.isArray(value["radius"]) ? value["radius"] : []
  const problems = Array.isArray(value["item_problems"]) ? value["item_problems"] : []
  return {
    unavailable: false,
    alreadySet: Array.isArray(value["already_set"]) ? value["already_set"].length : 0,
    channel: text(value["channel"]),
    itemProblems: problems.flatMap((item) => {
      if (!isRecord(item)) return []
      const [field, key, message] = [text(item["field"]), text(item["key"]), text(item["message"])]
      return field && key && message ? [{ field, key, message }] : []
    }),
    languages: languages.flatMap((item) => {
      if (!isRecord(item)) return []
      const [key, name] = [text(item["key"]), text(item["name"])]
      return key && name ? [{ key, name }] : []
    }),
    locationSetting: parseSetting(value["location_setting"]),
    locationTotal: wholeNumber(value["location_total"]) ?? locations.length,
    locations: locations.flatMap((item) => {
      if (!isRecord(item)) return []
      const [key, name] = [text(item["key"]), text(item["name"])]
      return key && name
        ? [
            {
              bidAdjustment: wholeNumber(item["bid_adjustment"]) ?? 0,
              excluded: item["excluded"] === true,
              key,
              name,
            },
          ]
        : []
    }),
    name: text(value["name"]) ?? "Campaign",
    status: text(value["status"]),
    problem: text(value["problem"]),
    radius: radius.flatMap((item) => {
      if (!isRecord(item)) return []
      const criterionId = googleAdsId(item["criterion_id"])
      const { radius: distance, units } = item
      return criterionId &&
        typeof distance === "number" &&
        (units === "MILES" || units === "KILOMETERS")
        ? [{ criterionId, radius: distance, units }]
        : []
    }),
  }
}

function nameMap(value: unknown): Map<string, string> {
  if (!isRecord(value)) return new Map()
  return new Map(
    Object.entries(value).flatMap(([key, name]) => (typeof name === "string" ? [[key, name]] : []))
  )
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseUpdateTargetingArgs(value: unknown): UpdateTargetingArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const changes: TargetingChange[] = []
  for (const entry of value["changes"]) {
    const change = parseChange(entry)
    if (change === null) return null
    changes.push(change)
  }
  const raw = isRecord(value["_checks"]) ? value["_checks"] : {}
  const campaigns = isRecord(raw["campaigns"]) ? raw["campaigns"] : {}
  const names = isRecord(raw["names"]) ? raw["names"] : {}
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    changes,
    checks: new Map(Object.entries(campaigns).map(([key, check]) => [key, parseCheck(check)])),
    names: { languages: nameMap(names["languages"]), locations: nameMap(names["locations"]) },
  }
}

export function serializeChanges(changes: readonly TargetingChange[]): Record<string, unknown>[] {
  return changes.map((change) => change.entry)
}

function sameEntry(left: TargetingChange | undefined, right: TargetingChange | undefined): boolean {
  return JSON.stringify(left?.entry) === JSON.stringify(right?.entry)
}

/** Each campaign still in the request, then each cancelled one, with what blocks approval. */
export function campaignRows(
  args: UpdateTargetingArgs,
  checked: UpdateTargetingArgs,
  cancelled: readonly TargetingChange[] = []
): CampaignRow[] {
  const answered = new Map(checked.changes.map((change) => [change.key, change]))
  const live = args.changes.map((change): CampaignRow => {
    const check = checked.checks.get(change.key)
    const edited = !sameEntry(change, answered.get(change.key))
    const alreadySet =
      !edited && check !== undefined && !check.unavailable && check.alreadySet >= itemCount(change)
    return {
      alreadySet,
      cancelled: false,
      change,
      check,
      edited,
      key: change.key,
      name: check && !check.unavailable ? check.name : change.label,
      problems: edited ? [] : checkProblems(change, check),
    }
  })
  const held = new Set(args.changes.map((change) => change.key))
  return [
    ...live,
    ...cancelled
      .filter((change) => !held.has(change.key))
      .map((change): CampaignRow => ({
        alreadySet: false,
        cancelled: true,
        change,
        check: checked.checks.get(change.key),
        edited: false,
        key: change.key,
        name: change.label,
        problems: [],
      })),
  ]
}

function itemCount(change: TargetingChange): number {
  return (
    TARGET_FIELDS.reduce((total, field) => total + change.targets[field].length, 0) +
    change.radius.length +
    change.removeRadius.length +
    (change.setting === null ? 0 : 1)
  )
}

function checkProblems(change: TargetingChange, check: TargetingCheck | undefined): string[] {
  if (check === undefined || check.unavailable) return [UNAVAILABLE]
  if (check.problem) return [check.problem]
  return [...new Set(check.itemProblems.map((item) => itemProblemText(change, item)))]
}

function itemProblemText(change: TargetingChange, item: ItemProblem): string {
  const target = (TARGET_FIELDS as readonly string[]).includes(item.field)
    ? change.targets[item.field as TargetField].find((entry) => entry.key === item.key)
    : undefined
  return target?.name ? `${target.name}: ${item.message}` : item.message
}

export function targetingCounts(rows: readonly CampaignRow[]) {
  const live = rows.filter((row) => !row.cancelled)
  return {
    alreadySet: live.filter((row) => row.alreadySet).length,
    // A blocked campaign has to be fixed or cancelled, so it doesn't count towards what applies.
    apply: live.filter((row) => !row.alreadySet && row.problems.length === 0).length,
    cancelled: rows.length - live.length,
    problems: live.filter((row) => row.problems.length > 0).length,
    total: live.length,
  }
}

function targetName(args: UpdateTargetingArgs, field: TargetField, target: Target): string {
  const names = field.endsWith("languages") ? args.names.languages : args.names.locations
  return names.get(target.key) ?? target.name ?? target.key
}

/** Each location or language once, with how many campaigns it reaches, as the card shows it. */
export function targetLines(args: UpdateTargetingArgs): TargetLine[] {
  const lines = new Map<string, TargetLine>()
  for (const change of args.changes) {
    for (const field of TARGET_FIELDS) {
      for (const target of change.targets[field]) {
        const id = `${field}:${target.key}`
        const line = lines.get(id)
        if (line) line.count += 1
        else
          lines.set(id, {
            bidAdjustment: target.bidAdjustment,
            count: 1,
            field,
            key: target.key,
            name: targetName(args, field, target),
            targetType: target.targetType,
          })
      }
    }
  }
  return [...lines.values()]
}

export type UnchangedPlace = { count: number; excluded: boolean; key: string; name: string }

/** What each campaign already targets and this request leaves alone, most common first. */
export function unchangedPlaces(args: UpdateTargetingArgs): UnchangedPlace[] {
  const places = new Map<string, UnchangedPlace>()
  for (const change of args.changes) {
    const check = args.checks.get(change.key)
    if (!check || check.unavailable) continue
    const touched = new Set(
      (["add_locations", "exclude_locations", "remove_locations"] as const).flatMap((field) =>
        change.targets[field].map((target) => target.key)
      )
    )
    for (const place of check.locations) {
      if (touched.has(place.key)) continue
      const id = `${String(place.excluded)}:${place.key}`
      const held = places.get(id)
      if (held) held.count += 1
      else places.set(id, { count: 1, excluded: place.excluded, key: place.key, name: place.name })
    }
  }
  return [...places.values()].sort((left, right) => right.count - left.count)
}

/** Live languages the request leaves alone, with how many campaigns hold each. */
export function unchangedLanguages(args: UpdateTargetingArgs): UnchangedPlace[] {
  const languages = new Map<string, UnchangedPlace>()
  for (const change of args.changes) {
    const check = args.checks.get(change.key)
    if (!check || check.unavailable) continue
    const removing = new Set(change.targets.remove_languages.map((target) => target.key))
    for (const language of check.languages) {
      if (removing.has(language.key)) continue
      const held = languages.get(language.key)
      if (held) held.count += 1
      else languages.set(language.key, { ...language, count: 1, excluded: false })
    }
  }
  return [...languages.values()].sort((left, right) => right.count - left.count)
}

/** Live radius targets the request leaves alone, as the card words them. */
export function unchangedRadius(args: UpdateTargetingArgs): { count: number; text: string }[] {
  const radii = new Map<string, { count: number; text: string }>()
  for (const change of args.changes) {
    const check = args.checks.get(change.key)
    if (!check || check.unavailable) continue
    for (const live of check.radius) {
      if (change.removeRadius.includes(live.criterionId)) continue
      const text = radiusText({ ...live, label: null })
      radii.set(text, { count: (radii.get(text)?.count ?? 0) + 1, text })
    }
  }
  return [...radii.values()]
}

/** How many campaigns are running, or null when any couldn't be read. */
export function campaignsOn(args: UpdateTargetingArgs): number | null {
  let on = 0
  for (const change of args.changes) {
    const check = args.checks.get(change.key)
    if (!check || check.unavailable) return null
    if (check.status !== "PAUSED") on += 1
  }
  return on
}

function targetEntry(target: Target, keepsBid: boolean): Record<string, unknown> {
  return {
    key: target.key,
    name: target.name,
    ...(target.targetType ? { target_type: target.targetType } : {}),
    ...(keepsBid ? { bid_adjustment: target.bidAdjustment } : {}),
  }
}

function withEntry(
  change: TargetingChange,
  fields: Partial<Record<string, unknown>>
): TargetingChange {
  const next = parseChange({ ...change.entry, ...fields })
  return next ?? change
}

function isEmpty(change: TargetingChange): boolean {
  return itemCount(change) === 0
}

function fieldEntries(targets: readonly Target[], field: TargetField) {
  return targets.map((target) => targetEntry(target, field === "add_locations"))
}

/** Takes one location or language out of every campaign; a campaign left with nothing leaves too. */
export function removeTarget(
  changes: readonly TargetingChange[],
  field: TargetField,
  key: string
): TargetingChange[] {
  return changes
    .map((change) =>
      withEntry(change, {
        [field]: fieldEntries(
          change.targets[field].filter((target) => target.key !== key),
          field
        ),
      })
    )
    .filter((change) => !isEmpty(change))
}

/** Adds a target to every campaign that can take it, and out of any list it was in before. */
export function addTarget(
  changes: readonly TargetingChange[],
  field: TargetField,
  target: Target,
  accepts: (change: TargetingChange) => boolean = () => true
): TargetingChange[] {
  const family: readonly TargetField[] = field.endsWith("languages")
    ? ["add_languages", "remove_languages"]
    : ["add_locations", "exclude_locations", "remove_locations"]
  return changes.map((change) => {
    if (!accepts(change)) return change
    const cleared = Object.fromEntries(
      family.map((name) => [
        name,
        fieldEntries(
          [
            ...change.targets[name].filter((item) => item.key !== target.key),
            ...(name === field ? [target] : []),
          ],
          name
        ),
      ])
    )
    return withEntry(change, cleared)
  })
}

export function setBidAdjustment(
  changes: readonly TargetingChange[],
  keys: ReadonlySet<string>,
  bidAdjustment: number | null
): TargetingChange[] {
  return changes.map((change) =>
    withEntry(change, {
      add_locations: fieldEntries(
        change.targets.add_locations.map((target) =>
          keys.has(target.key) ? { ...target, bidAdjustment } : target
        ),
        "add_locations"
      ),
    })
  )
}

export function setLocationSetting(
  changes: readonly TargetingChange[],
  setting: LocationSetting | null
): TargetingChange[] {
  return changes
    .map((change) => withEntry(change, { location_setting: setting }))
    .filter((change) => !isEmpty(change))
}

function radiusEntry(target: RadiusTarget): Record<string, unknown> {
  return {
    latitude: target.latitude,
    longitude: target.longitude,
    radius: target.radius,
    units: target.units,
    label: target.label,
    bid_adjustment: target.bidAdjustment,
  }
}

export function radiusIdentity(target: RadiusTarget): string {
  return [target.latitude, target.longitude, target.radius, target.units].join(",")
}

export function radiusLines(args: UpdateTargetingArgs): (RadiusTarget & { count: number })[] {
  const lines = new Map<string, RadiusTarget & { count: number }>()
  for (const change of args.changes) {
    for (const target of change.radius) {
      const id = radiusIdentity(target)
      const line = lines.get(id)
      if (line) line.count += 1
      else lines.set(id, { ...target, count: 1 })
    }
  }
  return [...lines.values()]
}

/** Replaces, adds, or (with null) takes out one radius on every campaign. */
export function editRadius(
  changes: readonly TargetingChange[],
  identity: string | null,
  next: RadiusTarget | null
): TargetingChange[] {
  return changes
    .map((change) => {
      const kept = change.radius.filter((target) => radiusIdentity(target) !== identity)
      const held = kept.length !== change.radius.length
      const add_radius = [...kept, ...(next && (held || identity === null) ? [next] : [])]
      return withEntry(change, { add_radius: add_radius.map(radiusEntry) })
    })
    .filter((change) => !isEmpty(change))
}

export type RadiusRemoval = { count: number; id: string; text: string }

/** Each radius the request removes, named from what the campaign holds now. */
export function radiusRemovals(args: UpdateTargetingArgs): RadiusRemoval[] {
  const lines = new Map<string, RadiusRemoval>()
  for (const change of args.changes) {
    const check = args.checks.get(change.key)
    for (const id of change.removeRadius) {
      const line = lines.get(id)
      if (line) {
        line.count += 1
        continue
      }
      const live =
        check && !check.unavailable ? check.radius.find((r) => r.criterionId === id) : null
      lines.set(id, {
        count: 1,
        id,
        text: live ? radiusText({ ...live, label: null }) : "Radius target",
      })
    }
  }
  return [...lines.values()]
}

export function keepRadius(changes: readonly TargetingChange[], id: string): TargetingChange[] {
  return changes
    .map((change) =>
      withEntry(change, { remove_radius: change.removeRadius.filter((item) => item !== id) })
    )
    .filter((change) => !isEmpty(change))
}

/** The setting the request asks for, or what the first campaign has now. */
export function shownLocationSetting(args: UpdateTargetingArgs): LocationSetting {
  const requested = args.changes.find((change) => change.setting !== null)?.setting
  if (requested) return requested
  const [first] = args.changes
  const check = first ? args.checks.get(first.key) : undefined
  return (check && !check.unavailable ? check.locationSetting : null) ?? "PRESENCE_OR_INTEREST"
}

export function radiusText(target: Pick<RadiusTarget, "radius" | "units" | "label">): string {
  const distance = `${String(target.radius)} ${target.units === "MILES" ? "mi" : "km"}`
  return target.label ? `${distance} around ${target.label}` : `${distance} radius`
}

export function bidText(bidAdjustment: number | null): string | null {
  if (bidAdjustment === null || bidAdjustment === 0) return null
  return `${bidAdjustment > 0 ? "+" : ""}${String(bidAdjustment)}%`
}

export function parseBidAdjustment(value: string): number | null {
  const parsed = Number(value.replace(/[%\s]/g, ""))
  return Number.isInteger(parsed) && parsed >= MIN_BID_ADJUSTMENT && parsed <= MAX_BID_ADJUSTMENT
    ? parsed
    : null
}

export function acceptsLanguageAdds(args: UpdateTargetingArgs, change: TargetingChange): boolean {
  const check = args.checks.get(change.key)
  return !check || check.unavailable || !NO_LANGUAGE_ADDS.has(check.channel ?? "")
}

/** What changes on one campaign, shortened so a table row stays on one or two lines. */
export function whatChanges(change: TargetingChange): string {
  const added = change.targets.add_locations.length + change.radius.length
  const excluded = change.targets.exclude_locations.length
  const removed = change.targets.remove_locations.length + change.removeRadius.length
  const parts = [
    added > 0 ? `adds ${String(added)}` : null,
    excluded > 0 ? `excludes ${String(excluded)}` : null,
    removed > 0 ? `removes ${String(removed)}` : null,
  ].filter((part) => part !== null)
  const text = parts.join(", ")
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}` : "No location change"
}

/** Blocked and cancelled campaigns first, then the ones whose change is least like the others. */
export function campaignsByDifference(rows: readonly CampaignRow[]): CampaignRow[] {
  const signature = (row: CampaignRow) =>
    `${whatChanges(row.change)}|${languagesText(row.change, row.check)}`
  const counts = new Map<string, number>()
  for (const row of rows) counts.set(signature(row), (counts.get(signature(row)) ?? 0) + 1)
  const rank = (row: CampaignRow) =>
    row.problems.length > 0 ? -2 : row.cancelled ? -1 : (counts.get(signature(row)) ?? 0)
  return [...rows].sort((left, right) => rank(left) - rank(right))
}

export function languagesText(change: TargetingChange, check: TargetingCheck | undefined): string {
  const names = check && !check.unavailable ? check.languages.map((item) => item.name) : []
  const removing = new Set(change.targets.remove_languages.map((item) => item.key))
  const after = [
    ...(check && !check.unavailable
      ? check.languages.filter((item) => !removing.has(item.key)).map((item) => item.name)
      : []),
    ...change.targets.add_languages.map((item) => item.name ?? item.key),
  ]
  if (names.length === 0 && after.length === 0) return "—"
  return names.join(", ") === after.join(", ")
    ? names.join(", ")
    : `${names.join(", ") || "None"} → ${after.join(", ") || "None"}`
}

export function needsCheck(args: UpdateTargetingArgs, checked: UpdateTargetingArgs): boolean {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    JSON.stringify(serializeChanges(args.changes)) !==
      JSON.stringify(serializeChanges(checked.changes))
  )
}

/** Why the request can't be approved yet, or null. */
export function targetingBlock(
  args: UpdateTargetingArgs | null,
  checked: UpdateTargetingArgs
): string | null {
  if (args === null) return null
  const counts = targetingCounts(campaignRows(args, checked))
  if (counts.total === 0) return "Every change is cancelled. Decline this request, or undo one."
  if (needsCheck(args, checked))
    return "Click Check Changes so Google can check your edits, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "campaign")} to continue.`
  if (counts.apply === 0) return "These campaigns already have these settings."
  return null
}

const LONGEST_NAME_IN_BUTTON = 24

/** The only kind of change in the request, when there is one. */
function soleField(args: UpdateTargetingArgs): { field: TargetField; names: string[] } | null {
  if (args.changes.some((c) => c.radius.length + c.removeRadius.length > 0 || c.setting))
    return null
  const lines = targetLines(args)
  const [first] = lines
  if (!first || lines.some((line) => line.field !== first.field)) return null
  return { field: first.field, names: lines.map((line) => line.name) }
}

function nameList(names: readonly string[]): string {
  const shown = names.slice(0, 3)
  const more = names.length - shown.length
  if (more > 0) return `${shown.join(", ")} and ${String(more)} more`
  const last = shown.pop()
  return shown.length > 0 ? `${shown.join(", ")} and ${last ?? ""}` : (last ?? "")
}

export function targetingApproveLabel(args: UpdateTargetingArgs): string {
  const { apply } = targetingCounts(campaignRows(args, args))
  if (apply === 0) return "Apply Changes"
  if (args.changes.length > 1)
    return `Apply to ${String(apply)} ${apply === 1 ? "Campaign" : "Campaigns"}`
  const sole = soleField(args)
  if (sole?.field === "add_locations" || sole?.field === "exclude_locations") {
    const verb = sole.field === "add_locations" ? "Add" : "Exclude"
    const [name] = sole.names
    return sole.names.length === 1 && name && name.length <= LONGEST_NAME_IN_BUTTON
      ? `${verb} ${name}`
      : `${verb} ${String(sole.names.length)} ${sole.names.length === 1 ? "Location" : "Locations"}`
  }
  return "Apply Changes"
}

export function targetingPrompt(args: UpdateTargetingArgs): string {
  const [first] = args.changes
  if (!first) return "Nothing is left to change."
  const customerIds = new Set(args.changes.map((change) => change.key.split("/")[1] ?? ""))
  const [customerId] = customerIds
  const where =
    customerIds.size === 1
      ? (args.accounts.get(customerId ?? "")?.label ?? "Google Ads")
      : `${String(customerIds.size)} accounts`
  const sole = args.changes.length === 1 ? soleField(args) : null
  if (sole?.field === "add_locations" || sole?.field === "exclude_locations") {
    const check = args.checks.get(first.key)
    const campaign = check && !check.unavailable ? check.name : first.label
    return sole.field === "add_locations"
      ? `Add ${nameList(sole.names)} to ${campaign} in ${where}.`
      : `Exclude ${nameList(sole.names)} from ${campaign} in ${where}.`
  }
  return `Change locations and languages for ${approvalCountLine(args.changes.length, "campaign")} in ${where}.`
}

/** A cancelled campaign with nothing on it, ready for a change the operator adds next. */
export function clearedChange(change: TargetingChange): TargetingChange {
  return withEntry(change, {
    add_languages: [],
    add_locations: [],
    add_radius: [],
    exclude_locations: [],
    location_setting: null,
    remove_languages: [],
    remove_locations: [],
    remove_radius: [],
  })
}

export function targetingDetails(args: UpdateTargetingArgs | null): FanOutDetail[] {
  return args ? [{ label: "Campaigns", value: String(args.changes.length) }] : []
}

export function parseCancelled(value: unknown): TargetingChange[] {
  return Array.isArray(value) ? value.flatMap((item) => parseChange(item) ?? []) : []
}

// Google takes 25 names a request, and the lookup route takes 500 characters a search.
const MAX_NAMES = 25
const MAX_SEARCH_CHARS = 500
export const MAX_PASTE_LINES = 500

/** Splits pasted lines into searches the lookup route and Google both accept. */
export function pasteBatches(lines: readonly string[]): string[][] {
  const batches: string[][] = []
  let batch: string[] = []
  let size = 0
  for (const line of lines) {
    // No search can hold this line, and no place name is this long.
    if (line.length + 1 > MAX_SEARCH_CHARS) continue
    if (batch.length === MAX_NAMES || size + line.length + 1 > MAX_SEARCH_CHARS) {
      batches.push(batch)
      batch = []
      size = 0
    }
    batch.push(line)
    size += line.length + 1
  }
  return batch.length > 0 ? [...batches, batch] : batches
}
