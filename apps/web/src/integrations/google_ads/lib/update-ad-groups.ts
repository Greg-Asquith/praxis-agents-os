// apps/web/src/integrations/google_ads/lib/update-ad-groups.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { canonicalMoney, roasPercent } from "@/integrations/google_ads/lib/campaign-bidding"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { parametersText, type UrlParameter } from "@/integrations/google_ads/lib/update-campaigns"
import { formatCurrencyAmount } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const AD_GROUP_SETTINGS = [
  "name",
  "cpc_bid",
  "target_cpa",
  "target_roas",
  "final_url_suffix",
  "tracking_template",
  "custom_parameters",
  "ad_rotation",
] as const

export type AdGroupSetting = (typeof AD_GROUP_SETTINGS)[number]
// Card terms, as the server sends them: money as a decimal string, target ROAS a ratio, and null
// for none, which for a target means the ad group follows its campaign.
export type AdGroupValue = string | number | UrlParameter[] | null

const BID_SETTINGS = ["cpc_bid", "target_cpa", "target_roas"] as const
type BidSetting = (typeof BID_SETTINGS)[number]
export const ROTATIONS = ["OPTIMIZE", "ROTATE_FOREVER"] as const

export const AD_GROUP_SETTING_TITLES: Record<AdGroupSetting, string> = {
  ad_rotation: "Ad Rotation",
  cpc_bid: "Default Max CPC",
  custom_parameters: "Custom Parameters",
  final_url_suffix: "Final URL Suffix",
  name: "Name",
  target_cpa: "Target CPA",
  target_roas: "Target ROAS",
  tracking_template: "Tracking Template",
}

// Each setting as a sentence names it.
const SETTING_NAMES: Record<AdGroupSetting, string> = {
  ad_rotation: "ad rotation",
  cpc_bid: "default max CPC",
  custom_parameters: "custom parameters",
  final_url_suffix: "final URL suffix",
  name: "name",
  target_cpa: "target CPA",
  target_roas: "target ROAS",
  tracking_template: "tracking template",
}

export const ROTATION_LABELS: Record<(typeof ROTATIONS)[number], string> = {
  OPTIMIZE: "Optimise",
  ROTATE_FOREVER: "Rotate Evenly",
}

const URL_SETTINGS = new Set<AdGroupSetting>([
  "final_url_suffix",
  "tracking_template",
  "custom_parameters",
])
const MONEY_SETTINGS = new Set<AdGroupSetting>(["cpc_bid", "target_cpa"])

type AdGroupChange = {
  adGroupId: string
  customerId: string
  // The change as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  key: string
  label: string
  requested: Partial<Record<AdGroupSetting, AdGroupValue>>
}

type AdGroupCheck =
  | { unavailable: true }
  | {
      unavailable: false
      bidsUsed: BidSetting[]
      campaignName: string | null
      current: Partial<Record<AdGroupSetting, AdGroupValue>>
      name: string | null
      problem: string | null
      problems: Partial<Record<AdGroupSetting, string>>
      requested: Partial<Record<AdGroupSetting, AdGroupValue>>
      strategyName: string | null
    }

export type UpdateAdGroupsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  changes: AdGroupChange[]
  checks: Map<string, AdGroupCheck>
}

// A setting the operator cancelled, kept beside the request so Undo can bring it back.
export type CancelledAdGroupSetting = {
  adGroup: Record<string, unknown>
  key: string
  setting: AdGroupSetting
  value: AdGroupValue
}

export type AdGroupRow = {
  adGroupName: string
  // The bid fields the campaign's strategy uses; null when it couldn't be read.
  bidsUsed: readonly BidSetting[] | null
  campaignName: string | null
  cancelled: boolean
  change: AdGroupChange | null
  customerId: string
  id: string
  key: string
  // Blocks approval while set.
  problem: string | null
  setting: AdGroupSetting
  strategyName: string | null
  // Same as the live value, so nothing is sent for it.
  unchanged: boolean
  value: AdGroupValue
  // Undefined when the live value couldn't be read.
  was: AdGroupValue | undefined
}

export type AdGroupCounts = {
  adGroups: number
  apply: number
  campaigns: number
  problems: number
  total: number
}

const UNAVAILABLE_PROBLEM =
  "Google Ads couldn't check this ad group. Ask the agent to prepare the change again."

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function money(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? canonicalMoney(value) : null
}

function ratio(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null
}

function parameters(value: unknown): UrlParameter[] | null {
  if (!Array.isArray(value)) return null
  const items: UrlParameter[] = []
  for (const item of value) {
    if (!isRecord(item) || typeof item["key"] !== "string" || typeof item["value"] !== "string")
      return null
    items.push({ key: item["key"], value: item["value"] })
  }
  return items
}

/** Reads one setting's value in card terms; undefined when it isn't one. */
export function adGroupValue(setting: AdGroupSetting, value: unknown): AdGroupValue | undefined {
  if (setting === "custom_parameters") return value === null ? [] : (parameters(value) ?? undefined)
  if (value === null) return null
  if (MONEY_SETTINGS.has(setting)) return money(value) ?? undefined
  if (setting === "target_roas") return ratio(value) ?? undefined
  if (setting === "ad_rotation")
    return (ROTATIONS as readonly unknown[]).includes(value) ? (value as string) : undefined
  return typeof value === "string" ? value : undefined
}

function settingMap(value: unknown): Partial<Record<AdGroupSetting, AdGroupValue>> {
  const values: Partial<Record<AdGroupSetting, AdGroupValue>> = {}
  if (!isRecord(value)) return values
  for (const setting of AD_GROUP_SETTINGS) {
    if (!Object.hasOwn(value, setting)) continue
    const parsed = adGroupValue(setting, value[setting])
    if (parsed !== undefined) values[setting] = parsed
  }
  return values
}

/** The settings an entry changes, read the way the server reads them. */
function requestedOf(
  entry: Record<string, unknown>
): Partial<Record<AdGroupSetting, AdGroupValue>> {
  const values: Partial<Record<AdGroupSetting, AdGroupValue>> = {}
  if (typeof entry["name"] === "string")
    values.name = entry["name"].split(/\s+/).filter(Boolean).join(" ")
  const bid = money(entry["cpc_bid"])
  if (bid) values.cpc_bid = bid
  // "none" removes a target override.
  if (entry["target_cpa"] === "none") values.target_cpa = null
  else if (money(entry["target_cpa"])) values.target_cpa = money(entry["target_cpa"])
  if (entry["target_roas"] === "none") values.target_roas = null
  else if (ratio(entry["target_roas"]) !== null) values.target_roas = ratio(entry["target_roas"])
  const url = isRecord(entry["url_options"]) ? entry["url_options"] : {}
  for (const setting of ["final_url_suffix", "tracking_template"] as const) {
    const value = url[setting]
    if (typeof value === "string") values[setting] = value.trim() || null
  }
  const custom = parameters(url["custom_parameters"])
  if (custom) values.custom_parameters = custom
  const rotation = adGroupValue("ad_rotation", entry["ad_rotation"])
  if (typeof rotation === "string") values.ad_rotation = rotation
  return values
}

function parseChange(value: unknown): AdGroupChange | null {
  if (!isRecord(value) || !isRecord(value["ad_group"])) return null
  const reference = value["ad_group"]
  const customerId = googleAdsId(reference["customer_id"])
  const adGroupId = googleAdsId(reference["ad_group_id"])
  if (customerId === null || adGroupId === null) return null
  return {
    adGroupId,
    customerId,
    entry: value,
    key: `customers/${customerId}/adGroups/${adGroupId}`,
    label: text(reference["label"]) ?? `Ad group ${adGroupId}`,
    requested: requestedOf(value),
  }
}

function parseCheck(value: unknown): AdGroupCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const problems: Partial<Record<AdGroupSetting, string>> = {}
  const rawProblems = isRecord(value["problems"]) ? value["problems"] : {}
  for (const setting of AD_GROUP_SETTINGS) {
    const problem = text(rawProblems[setting])
    if (problem) problems[setting] = problem
  }
  const bids = Array.isArray(value["bids_used"]) ? value["bids_used"] : []
  return {
    unavailable: false,
    bidsUsed: BID_SETTINGS.filter((setting) => bids.includes(setting)),
    campaignName: text(value["campaign_name"]),
    current: settingMap(value["current"]),
    name: text(value["name"]),
    problem: text(value["problem"]),
    problems,
    requested: settingMap(value["requested"]),
    strategyName: text(value["strategy_name"]),
  }
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseUpdateAdGroupsArgs(value: unknown): UpdateAdGroupsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const changes: AdGroupChange[] = []
  const keys = new Set<string>()
  for (const entry of value["changes"]) {
    const change = parseChange(entry)
    if (change === null || keys.has(change.key)) return null
    keys.add(change.key)
    changes.push(change)
  }
  const rawChecks = isRecord(value["_checks"]) ? value["_checks"] : {}
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    changes,
    checks: new Map(Object.entries(rawChecks).map(([key, check]) => [key, parseCheck(check)])),
  }
}

function sameAdGroupValue(a: AdGroupValue | undefined, b: AdGroupValue | undefined) {
  return JSON.stringify(a) === JSON.stringify(b)
}

function rowOf(
  change: AdGroupChange | null,
  key: string,
  customerId: string,
  label: string,
  setting: AdGroupSetting,
  value: AdGroupValue,
  check: AdGroupCheck | undefined
): AdGroupRow {
  const live = check && !check.unavailable ? check : null
  const was = live
    ? (live.current[setting] ?? (setting === "custom_parameters" ? [] : null))
    : undefined
  // Google answered for the value it was checked with, so an edited value waits for a new check.
  const checked = live !== null && sameAdGroupValue(live.requested[setting], value)
  return {
    adGroupName: live?.name ?? label,
    bidsUsed: live?.bidsUsed ?? null,
    campaignName: live?.campaignName ?? null,
    cancelled: change === null,
    change,
    customerId,
    id: `${key}|${setting}`,
    key,
    problem:
      live === null
        ? UNAVAILABLE_PROBLEM
        : checked
          ? (live.problem ?? live.problems[setting] ?? null)
          : null,
    setting,
    strategyName: live?.strategyName ?? null,
    unchanged: was !== undefined && sameAdGroupValue(was, value),
    value,
    was,
  }
}

/** One row per ad group and setting, with cancelled settings after the ones still requested. */
export function adGroupRows(
  args: UpdateAdGroupsArgs,
  checked: UpdateAdGroupsArgs,
  cancelled: readonly CancelledAdGroupSetting[] = []
): AdGroupRow[] {
  const rows: AdGroupRow[] = []
  for (const change of args.changes)
    for (const setting of AD_GROUP_SETTINGS) {
      const value = change.requested[setting]
      if (value === undefined) continue
      rows.push(
        rowOf(
          change,
          change.key,
          change.customerId,
          change.label,
          setting,
          value,
          checked.checks.get(change.key)
        )
      )
    }
  const live = new Set(rows.map((row) => row.id))
  for (const item of cancelled) {
    if (live.has(`${item.key}|${item.setting}`)) continue
    rows.push(
      rowOf(
        null,
        item.key,
        googleAdsId(item.adGroup["customer_id"]) ?? "",
        text(item.adGroup["label"]) ?? item.key,
        item.setting,
        item.value,
        checked.checks.get(item.key)
      )
    )
  }
  return rows
}

export function adGroupCounts(rows: readonly AdGroupRow[]): AdGroupCounts {
  const live = rows.filter((row) => !row.cancelled)
  return {
    adGroups: new Set(live.map((row) => row.key)).size,
    apply: live.filter((row) => !row.unchanged).length,
    campaigns: new Set(live.map((row) => row.campaignName ?? row.key)).size,
    problems: live.filter((row) => row.problem !== null).length,
    total: live.length,
  }
}

function without(record: Record<string, unknown>, key: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key))
}

/** Writes a setting into a raw entry in the tool's argument shape; undefined leaves it out. */
function withSetting(
  entry: Record<string, unknown>,
  setting: AdGroupSetting,
  value: AdGroupValue | undefined
): Record<string, unknown> {
  if (URL_SETTINGS.has(setting)) {
    const current = isRecord(entry["url_options"]) ? entry["url_options"] : {}
    const item = value === null && setting !== "custom_parameters" ? "" : value
    const group = item === undefined ? without(current, setting) : { ...current, [setting]: item }
    return Object.keys(group).length > 0
      ? { ...entry, url_options: group }
      : without(entry, "url_options")
  }
  if (value === undefined) return without(entry, setting)
  // Removing a target override is "none"; a CPC bid can only be set.
  return { ...entry, [setting]: value ?? "none" }
}

/** The `changes` value with one setting set on the given rows, or cancelled when undefined. */
export function editedAdGroupChanges(
  args: UpdateAdGroupsArgs,
  ids: ReadonlySet<string>,
  value: (row: { key: string; setting: AdGroupSetting }) => AdGroupValue | undefined
): Record<string, unknown>[] {
  return args.changes.flatMap((change) => {
    let entry = change.entry
    for (const setting of AD_GROUP_SETTINGS) {
      if (change.requested[setting] === undefined || !ids.has(`${change.key}|${setting}`)) continue
      entry = withSetting(entry, setting, value({ key: change.key, setting }))
    }
    // An entry must change something, so an ad group with every setting cancelled leaves.
    return Object.keys(requestedOf(entry)).length > 0 ? [entry] : []
  })
}

/** Settings the request doesn't change on an ad group yet, each starting at its live value.

Bids and targets are offered only where the campaign's strategy uses them.
 */
export function addableSettings(
  checked: UpdateAdGroupsArgs,
  rows: readonly AdGroupRow[],
  key: string
): { setting: AdGroupSetting; value: AdGroupValue }[] {
  const check = checked.checks.get(key)
  if (!check || check.unavailable) return []
  const present = new Set(rows.filter((row) => row.key === key).map((row) => row.setting))
  return AD_GROUP_SETTINGS.flatMap((setting) => {
    const bid = BID_SETTINGS.find((item) => item === setting)
    if (present.has(setting) || (bid && !check.bidsUsed.includes(bid))) return []
    const live = check.current[setting] ?? (setting === "custom_parameters" ? [] : null)
    // An ad group with no rotation set starts at Optimise, Google's recommended mode.
    const value = setting === "ad_rotation" ? (live ?? "OPTIMIZE") : live
    // A name and a CPC bid can't be cleared, so they need a live value to start from.
    if (value === null && (setting === "name" || setting === "cpc_bid")) return []
    return [{ setting, value }]
  })
}

/** The `changes` value with a setting added to one ad group already in the request. */
export function addedAdGroupChanges(
  args: UpdateAdGroupsArgs,
  key: string,
  setting: AdGroupSetting,
  value: AdGroupValue
): Record<string, unknown>[] {
  return args.changes.map((change) =>
    change.key === key ? withSetting(change.entry, setting, value) : change.entry
  )
}

/** Puts cancelled settings back, adding their ad group again when it had left the request. */
export function restoredAdGroupChanges(
  args: UpdateAdGroupsArgs,
  items: readonly CancelledAdGroupSetting[]
): Record<string, unknown>[] {
  const entries = new Map(args.changes.map((change) => [change.key, change.entry]))
  for (const item of items) {
    const entry = entries.get(item.key) ?? { ad_group: item.adGroup }
    entries.set(item.key, withSetting(entry, item.setting, item.value))
  }
  return [...entries.values()]
}

export function parseCancelledAdGroupSettings(value: unknown): CancelledAdGroupSetting[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item) || !isRecord(item["adGroup"]) || typeof item["key"] !== "string") return []
    const setting = AD_GROUP_SETTINGS.find((name) => name === item["setting"])
    const parsed = setting ? adGroupValue(setting, item["value"]) : undefined
    return setting && parsed !== undefined
      ? [{ adGroup: item["adGroup"], key: item["key"], setting, value: parsed }]
      : []
  })
}

/** Raises or lowers a money value by a percentage, in the currency's smallest unit. */
export function scaledMoney(value: string, percent: number, currency: string | null): string {
  const digits = currency
    ? new Intl.NumberFormat("en", { currency, style: "currency" }).resolvedOptions()
        .maximumFractionDigits
    : 2
  const scaled = Number(value) * (1 + percent / 100)
  return canonicalMoney(Math.max(scaled, 10 ** -(digits ?? 2)).toFixed(digits ?? 2))
}

function signature(args: UpdateAdGroupsArgs): string {
  return JSON.stringify(
    args.changes.map((change) => [
      change.key,
      AD_GROUP_SETTINGS.map((setting) => change.requested[setting] ?? "-"),
    ])
  )
}

export function adGroupsNeedCheck(args: UpdateAdGroupsArgs, checked: UpdateAdGroupsArgs) {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    signature(args) !== signature(checked)
  )
}

/** Why the request can't be approved yet, or null. */
export function adGroupsBlock(
  args: UpdateAdGroupsArgs | null,
  checked: UpdateAdGroupsArgs
): string | null {
  if (args === null) return null
  const counts = adGroupCounts(adGroupRows(args, checked))
  if (counts.total === 0) return "Every change is cancelled. Decline this request, or undo one."
  if (adGroupsNeedCheck(args, checked))
    return "Click Check Changes so Google can check your edits, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "change")} to continue.`
  if (counts.apply === 0) return "These ad groups already have these settings."
  return null
}

/** A setting's value in the words the card uses. */
export function adGroupValueText(
  setting: AdGroupSetting,
  value: AdGroupValue | undefined,
  currency: string | null
): string {
  if (value === undefined) return "—"
  if (Array.isArray(value)) return value.length > 0 ? parametersText(value) : "None"
  if (value === null)
    return setting === "target_cpa" || setting === "target_roas" ? "Campaign's target" : "None"
  if (typeof value === "number") return `${roasPercent(value)}%`
  if (MONEY_SETTINGS.has(setting)) return currency ? formatCurrencyAmount(value, currency) : value
  const rotation = ROTATIONS.find((item) => item === value)
  return setting === "ad_rotation" && rotation ? ROTATION_LABELS[rotation] : value
}

export function adGroupCurrency(args: UpdateAdGroupsArgs, row: AdGroupRow): string | null {
  return args.accounts.get(row.customerId)?.currencyCode ?? null
}

function soleRow(args: UpdateAdGroupsArgs): AdGroupRow | null {
  const rows = adGroupRows(args, args)
  return rows.length === 1 ? (rows[0] ?? null) : null
}

export function adGroupsPrompt(args: UpdateAdGroupsArgs): string {
  const rows = adGroupRows(args, args)
  if (rows.length === 0) return "Nothing is left to change."
  const sole = soleRow(args)
  // The banner names the account, so a sole change's prompt names only the ad group.
  if (sole) {
    if (sole.setting === "name" && typeof sole.value === "string")
      return `Rename ${sole.adGroupName} to ${sole.value}.`
    const name = SETTING_NAMES[sole.setting]
    if (sole.value === null && (sole.setting === "target_cpa" || sole.setting === "target_roas"))
      return `Remove the ${name} of ${sole.adGroupName}, so it follows its campaign.`
    return `Change the ${name} of ${sole.adGroupName}.`
  }
  const counts = adGroupCounts(rows)
  const ids = new Set(args.changes.map((change) => change.customerId))
  const [id] = ids
  const where =
    ids.size === 1
      ? (args.accounts.get(id ?? "")?.label ?? "Google Ads")
      : `${String(ids.size)} accounts`
  const target =
    counts.adGroups === 1
      ? (rows[0]?.adGroupName ?? "1 ad group")
      : approvalCountLine(counts.adGroups, "ad group")
  return `Change ${approvalCountLine(rows.length, "setting")} on ${target} in ${where}.`
}

/** Names the change when there is only one; otherwise counts what's sent. */
export function adGroupsApproveLabel(args: UpdateAdGroupsArgs): string {
  const sole = soleRow(args)
  if (sole && !sole.unchanged) {
    if (sole.setting === "name") return "Rename Ad Group"
    if (sole.value === null && (sole.setting === "target_cpa" || sole.setting === "target_roas"))
      return `Remove ${AD_GROUP_SETTING_TITLES[sole.setting]}`
    return sole.setting === "cpc_bid"
      ? "Change Max CPC"
      : `Change ${AD_GROUP_SETTING_TITLES[sole.setting]}`
  }
  const { apply } = adGroupCounts(adGroupRows(args, args))
  return apply === 0
    ? "Apply Changes"
    : `Apply ${String(apply)} ${apply === 1 ? "Change" : "Changes"}`
}

export function adGroupsBannerDetail(
  counts: AdGroupCounts,
  accountIds: readonly string[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>
): string {
  const account = accountIds.length === 1 ? accounts.get(accountIds[0] ?? "") : undefined
  return [
    account?.label ?? null,
    counts.adGroups > 1
      ? `${approvalCountLine(counts.adGroups, "ad group")} in ${approvalCountLine(counts.campaigns, "campaign")}`
      : null,
    account?.timeZone ? `Account time ${account.timeZone}` : null,
  ]
    .filter((part) => part !== null)
    .join(" · ")
}

export function adGroupsDetails(args: UpdateAdGroupsArgs | null): FanOutDetail[] {
  return args ? [{ label: "Ad Groups", value: String(args.changes.length) }] : []
}
