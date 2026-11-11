// apps/web/src/integrations/google_ads/lib/update-targeting-result.ts

import { type EditOutcome, isEditOutcome } from "@/integrations/google_ads/lib/edit-outcomes"
import { bidText, deviceText } from "@/integrations/google_ads/lib/update-targeting"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type TargetingSetting =
  | "locations"
  | "excluded_locations"
  | "radius"
  | "languages"
  | "location_setting"
  | "devices"
  | "ad_schedule"
  | "audiences"
  | "audience_mode"
  | "demographics"
type TargetingAction = "add" | "remove" | "change_bid" | "set"

type OutcomeItem = {
  bidAdjustment: number | null
  name: string
  previousBidAdjustment: number | null
}

export type TargetingOutcomeRow = {
  action: TargetingAction
  // Set when the change was on one of the campaign's ad groups.
  adGroupName: string | null
  campaignName: string
  count: number
  errorCode: string | null
  items: OutcomeItem[]
  message: string | null
  outcome: EditOutcome
  setting: TargetingSetting
}

export type UpdateTargetingResult = { accountId: string; rows: TargetingOutcomeRow[] }

const SETTINGS = [
  "locations",
  "excluded_locations",
  "radius",
  "languages",
  "location_setting",
  "devices",
  "ad_schedule",
  "audiences",
  "audience_mode",
  "demographics",
]
const ACTIONS = ["add", "remove", "change_bid", "set"]

export const SETTING_TITLES: Record<TargetingSetting, string> = {
  ad_schedule: "Ad Schedule",
  audience_mode: "Audience Use",
  audiences: "Audiences",
  demographics: "Demographics",
  devices: "Devices",
  excluded_locations: "Excluded",
  languages: "Languages",
  location_setting: "Who Counts",
  locations: "Locations",
  radius: "Radius",
}

export const LOCATION_SETTING_LABELS: Record<string, string> = {
  PRESENCE: "People in or regularly in",
  PRESENCE_OR_INTEREST: "People in, or interested in",
}

const SET_LABELS: Record<string, string> = {
  ...LOCATION_SETTING_LABELS,
  OBSERVATION: "Observation",
  TARGETING: "Targeting",
}

function parseItem(value: unknown): OutcomeItem | null {
  if (!isRecord(value) || !isNonEmptyString(value["name"])) return null
  const number = (key: string) => (typeof value[key] === "number" ? value[key] : null)
  return {
    bidAdjustment: number("bid_adjustment"),
    name: value["name"],
    previousBidAdjustment: number("previous_bid_adjustment"),
  }
}

function parseRow(value: unknown): TargetingOutcomeRow | null {
  if (!isRecord(value)) return null
  const { action, count, items, outcome, setting } = value
  if (
    typeof action !== "string" ||
    !ACTIONS.includes(action) ||
    typeof setting !== "string" ||
    !SETTINGS.includes(setting) ||
    !isEditOutcome(outcome) ||
    typeof count !== "number" ||
    !Array.isArray(items)
  )
    return null
  const parsed = items.map(parseItem)
  if (parsed.some((item) => item === null)) return null
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    action: action as TargetingAction,
    adGroupName: text("ad_group_name"),
    campaignName: text("campaign_name") ?? "",
    count,
    errorCode: text("error_code"),
    items: parsed.filter((item) => item !== null),
    message: text("message"),
    outcome,
    setting: setting as TargetingSetting,
  }
}

export function parseUpdateTargetingResult(value: unknown): UpdateTargetingResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !Array.isArray(value["outcomes"])
  )
    return null
  const rows = value["outcomes"].map(parseRow)
  if (rows.some((row) => row === null)) return null
  return { accountId: value["account_id"], rows: rows.filter((row) => row !== null) }
}

function itemsText(row: TargetingOutcomeRow): string {
  const names = row.items.map((item) => {
    const bid = bidText(item.bidAdjustment)
    return bid ? `${item.name} (${bid})` : item.name
  })
  const more = row.count - row.items.length
  return more > 0 ? `${names.join(", ")} and ${String(more)} more` : names.join(", ")
}

function devicesText(row: TargetingOutcomeRow, previous: boolean): string {
  return row.items
    .map((item) => {
      const bidAdjustment = (previous ? item.previousBidAdjustment : item.bidAdjustment) ?? 0
      return `${item.name} ${deviceText({ bidAdjustment, excluded: false })}`
    })
    .join(", ")
}

/** The row's Before and After, in the words the card uses. */
export function rowChange(row: TargetingOutcomeRow): { after: string; before: string } {
  if (row.setting === "devices" || row.setting === "demographics")
    return { after: devicesText(row, false), before: devicesText(row, true) }
  if (row.action === "set") {
    const name = row.items[0]?.name ?? ""
    return { after: SET_LABELS[name] ?? name, before: "—" }
  }
  if (row.action === "remove") return { after: "Removed", before: itemsText(row) }
  if (row.action === "change_bid") {
    const [first] = row.items
    return {
      after: itemsText(row),
      before: first ? (bidText(first.previousBidAdjustment) ?? "No adjustment") : "—",
    }
  }
  return { after: `+ ${itemsText(row)}`, before: "—" }
}
