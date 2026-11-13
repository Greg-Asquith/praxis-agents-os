// apps/web/src/integrations/google_ads/lib/targeting-audiences.ts

import { DEMOGRAPHIC_VALUES, DIMENSION_NAMES } from "@/integrations/google_ads/lib/demographics"
import {
  audienceId,
  EXCLUDED,
  isEmpty,
  withEntry,
  type AudienceMode,
  type AudienceTarget,
  type DemographicDimension,
  type DemographicTarget,
  type TargetingChange,
  type UpdateTargetingArgs,
} from "@/integrations/google_ads/lib/update-targeting"

const AUDIENCE_CATEGORIES: Record<AudienceTarget["kind"], string> = {
  combined_audience: "Combined",
  custom_audience: "Custom",
  user_interest: "Interest",
  user_list: "Your Data",
}

export const AUDIENCE_MODE_OPTIONS = [
  {
    description: "Bid more or less for these audiences. Who sees your ads doesn't change.",
    label: "Observation",
    value: "OBSERVATION",
  },
  {
    description: "Show ads only to people in these audiences. Fewer people see your ads.",
    label: "Targeting",
    value: "TARGETING",
  },
] as const

export function audienceCategory(kind: AudienceTarget["kind"]): string {
  return AUDIENCE_CATEGORIES[kind]
}

export type AudienceLine = AudienceTarget & {
  count: number
  field: "add_audiences" | "remove_audiences"
  id: string
  name: string
}

/** Each audience added or removed once, with how many entries it reaches. */
export function audienceLines(args: UpdateTargetingArgs): AudienceLine[] {
  const lines = new Map<string, AudienceLine>()
  for (const change of args.changes) {
    for (const [field, targets] of [
      ["add_audiences", change.addAudiences],
      ["remove_audiences", change.removeAudiences],
    ] as const) {
      for (const target of targets) {
        const id = audienceId(target)
        const line = lines.get(`${field}:${id}`)
        if (line) line.count += 1
        else
          lines.set(`${field}:${id}`, {
            ...target,
            count: 1,
            field,
            id,
            name: args.names.audiences.get(id) ?? target.name ?? id,
          })
      }
    }
  }
  return [...lines.values()]
}

/** Live audiences the request leaves alone, with how many entries hold each. */
export function unchangedAudiences(
  args: UpdateTargetingArgs
): { count: number; id: string; name: string }[] {
  const audiences = new Map<string, { count: number; id: string; name: string }>()
  for (const change of args.changes) {
    const check = args.checks.get(change.key)
    if (!check || check.unavailable) continue
    const touched = new Set(
      [...change.addAudiences, ...change.removeAudiences].map((item) => audienceId(item))
    )
    for (const live of check.audiences) {
      const id = audienceId(live)
      if (touched.has(id)) continue
      const held = audiences.get(id)
      if (held) held.count += 1
      else audiences.set(id, { count: 1, id, name: live.name })
    }
  }
  return [...audiences.values()].sort((left, right) => right.count - left.count)
}

function audienceEntry(target: AudienceTarget, keepsBid: boolean): Record<string, unknown> {
  return {
    kind: target.kind,
    key: target.key,
    name: target.name,
    ...(keepsBid ? { bid_adjustment: target.bidAdjustment } : {}),
  }
}

function audienceFields(
  change: TargetingChange,
  add: readonly AudienceTarget[],
  remove: readonly AudienceTarget[]
): TargetingChange {
  return withEntry(change, {
    add_audiences: add.map((target) => audienceEntry(target, true)),
    remove_audiences: remove.map((target) => audienceEntry(target, false)),
  })
}

/** Adds an audience to every entry, taking it out of the removals first. */
export function addAudience(
  changes: readonly TargetingChange[],
  target: AudienceTarget
): TargetingChange[] {
  const id = audienceId(target)
  return changes.map((change) =>
    audienceFields(
      change,
      [...change.addAudiences.filter((item) => audienceId(item) !== id), target],
      change.removeAudiences.filter((item) => audienceId(item) !== id)
    )
  )
}

/** Takes an audience's add or removal out of every entry. */
export function cancelAudience(
  changes: readonly TargetingChange[],
  field: AudienceLine["field"],
  id: string
): TargetingChange[] {
  return changes
    .map((change) =>
      audienceFields(
        change,
        field === "add_audiences"
          ? change.addAudiences.filter((item) => audienceId(item) !== id)
          : change.addAudiences,
        field === "remove_audiences"
          ? change.removeAudiences.filter((item) => audienceId(item) !== id)
          : change.removeAudiences
      )
    )
    .filter((change) => !isEmpty(change))
}

export function setAudienceBid(
  changes: readonly TargetingChange[],
  id: string,
  bidAdjustment: number | null
): TargetingChange[] {
  return changes.map((change) =>
    audienceFields(
      change,
      change.addAudiences.map((item) =>
        audienceId(item) === id ? { ...item, bidAdjustment } : item
      ),
      change.removeAudiences
    )
  )
}

export function setAudienceMode(
  changes: readonly TargetingChange[],
  mode: AudienceMode | null
): TargetingChange[] {
  return changes
    .map((change) => withEntry(change, { audience_mode: mode }))
    .filter((change) => !isEmpty(change))
}

/** The mode the request asks for, or what the first entry uses now; null for Google's default. */
export function shownAudienceMode(args: UpdateTargetingArgs): AudienceMode | null {
  const requested = args.changes.find((change) => change.audienceMode !== null)?.audienceMode
  if (requested) return requested
  const [first] = args.changes
  const check = first ? args.checks.get(first.key) : undefined
  return check && !check.unavailable ? check.audienceMode : null
}

export function changesAudiences(change: TargetingChange): boolean {
  return (
    change.addAudiences.length + change.removeAudiences.length > 0 || change.audienceMode !== null
  )
}

export type DemographicLine = {
  dimension: DemographicDimension
  name: string
  // The live adjustment every shown entry shares, EXCLUDED when excluded, or null when they differ.
  now: number | null
  // What every shown entry asks for; null leaves it, "varies" when entries differ.
  requested: DemographicTarget | null | "varies"
  value: string
}

/** One line per value of the dimension, with what it is now and what the request asks for. */
export function demographicLines(
  args: UpdateTargetingArgs,
  dimension: DemographicDimension
): DemographicLine[] {
  return DEMOGRAPHIC_VALUES[dimension].map(([value, name]) => {
    const nows = new Set(
      args.changes.map((change) => {
        const check = args.checks.get(change.key)
        if (!check || check.unavailable) return null
        const live = check.demographics.find(
          (item) => item.dimension === dimension && item.value === value
        )
        if (!live) return 0
        return live.excluded ? EXCLUDED : live.bidAdjustment
      })
    )
    const asks = new Set(
      args.changes.map((change) => {
        const target = change.demographics.find(
          (item) => item.dimension === dimension && item.value === value
        )
        return target ? JSON.stringify(target) : null
      })
    )
    const [now] = nows
    const [ask] = asks
    return {
      dimension,
      name,
      now: nows.size === 1 && now !== undefined ? now : null,
      requested: asks.size > 1 ? "varies" : ask ? (JSON.parse(ask) as DemographicTarget) : null,
      value,
    }
  })
}

/** True when every entry is a Performance Max campaign, which takes demographics as exclusions only. */
export function exclusionsOnly(args: UpdateTargetingArgs): boolean {
  return (
    args.changes.length > 0 &&
    args.changes.every((change) => {
      const check = args.checks.get(change.key)
      return check !== undefined && !check.unavailable && check.channel === "PERFORMANCE_MAX"
    })
  )
}

/** The dimensions the request changes, in Google's order. */
export function changedDimensions(args: UpdateTargetingArgs): DemographicDimension[] {
  const changed = new Set(
    args.changes.flatMap((change) => change.demographics.map((item) => item.dimension))
  )
  return (Object.keys(DIMENSION_NAMES) as DemographicDimension[]).filter((dimension) =>
    changed.has(dimension)
  )
}

function demographicEntry(target: DemographicTarget): Record<string, unknown> {
  return target.excluded
    ? { dimension: target.dimension, value: target.value, excluded: true }
    : { dimension: target.dimension, value: target.value, bid_adjustment: target.bidAdjustment }
}

/** Sets one value on every entry, or with null leaves it as it is. */
export function setDemographic(
  changes: readonly TargetingChange[],
  dimension: DemographicDimension,
  value: string,
  next: Pick<DemographicTarget, "bidAdjustment" | "excluded"> | null
): TargetingChange[] {
  const order = DEMOGRAPHIC_VALUES[dimension].map(([key]) => key)
  return changes
    .map((change) => {
      const kept = change.demographics.filter(
        (item) => item.dimension !== dimension || item.value !== value
      )
      const demographics = next ? [...kept, { ...next, dimension, value }] : kept
      demographics.sort(
        (left, right) =>
          left.dimension.localeCompare(right.dimension) ||
          order.indexOf(left.value) - order.indexOf(right.value)
      )
      return withEntry(change, { demographics: demographics.map(demographicEntry) })
    })
    .filter((change) => !isEmpty(change))
}

export function clearDemographics(
  changes: readonly TargetingChange[],
  dimension: DemographicDimension
): TargetingChange[] {
  return changes
    .map((change) =>
      withEntry(change, {
        demographics: change.demographics
          .filter((item) => item.dimension !== dimension)
          .map(demographicEntry),
      })
    )
    .filter((change) => !isEmpty(change))
}

/** Takes every audience change and the mode out of every entry. */
export function clearAudiences(changes: readonly TargetingChange[]): TargetingChange[] {
  return changes
    .map((change) =>
      withEntry(change, { add_audiences: [], remove_audiences: [], audience_mode: null })
    )
    .filter((change) => !isEmpty(change))
}
