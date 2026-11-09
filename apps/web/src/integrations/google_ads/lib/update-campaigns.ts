// apps/web/src/integrations/google_ads/lib/update-campaigns.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export const CAMPAIGN_SETTINGS = [
  "name",
  "start_date",
  "end_date",
  "final_url_suffix",
  "tracking_template",
  "custom_parameters",
  "search_partners",
  "display_expansion",
] as const

export type CampaignSetting = (typeof CAMPAIGN_SETTINGS)[number]
export type UrlParameter = { key: string; value: string }
// Card terms, as the server sends them: dates as YYYY-MM-DD, and null for none.
export type SettingValue = string | boolean | UrlParameter[] | null

export const SETTING_TITLES: Record<CampaignSetting, string> = {
  custom_parameters: "Custom Parameters",
  display_expansion: "Display Expansion",
  end_date: "End Date",
  final_url_suffix: "Final URL Suffix",
  name: "Name",
  search_partners: "Search Partners",
  start_date: "Start Date",
  tracking_template: "Tracking Template",
}

const URL_SETTINGS = new Set<CampaignSetting>([
  "final_url_suffix",
  "tracking_template",
  "custom_parameters",
])
const NETWORK_SETTINGS = new Set<CampaignSetting>(["search_partners", "display_expansion"])

type CampaignChange = {
  campaignId: string
  customerId: string
  // The change as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  key: string
  label: string
  requested: Partial<Record<CampaignSetting, SettingValue>>
}

type CampaignCheck =
  | { unavailable: true }
  | {
      unavailable: false
      current: Partial<Record<CampaignSetting, SettingValue>>
      name: string | null
      problem: string | null
      problems: Partial<Record<CampaignSetting, string>>
      requested: Partial<Record<CampaignSetting, SettingValue>>
    }

export type UpdateCampaignsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  changes: CampaignChange[]
  checks: Map<string, CampaignCheck>
}

// A setting the operator cancelled, kept beside the request so Undo can bring it back.
export type CancelledSetting = {
  campaign: Record<string, unknown>
  key: string
  setting: CampaignSetting
  value: SettingValue
}

export type CampaignRow = {
  campaignName: string
  cancelled: boolean
  change: CampaignChange | null
  customerId: string
  id: string
  key: string
  // Blocks approval while set.
  problem: string | null
  setting: CampaignSetting
  // Same as the live value, so nothing is sent for it.
  unchanged: boolean
  value: SettingValue
  // Undefined when the live value couldn't be read.
  was: SettingValue | undefined
}

export type CampaignCounts = {
  apply: number
  campaigns: number
  problems: number
  total: number
}

const UNAVAILABLE_PROBLEM =
  "Google Ads couldn't check this campaign. Ask the agent to prepare the change again."

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function parseParameters(value: unknown): UrlParameter[] | null {
  if (!Array.isArray(value)) return null
  const items: UrlParameter[] = []
  for (const item of value) {
    if (!isRecord(item) || typeof item["key"] !== "string" || typeof item["value"] !== "string")
      return null
    items.push({ key: item["key"], value: item["value"] })
  }
  return items
}

function settingValue(setting: CampaignSetting, value: unknown): SettingValue | undefined {
  if (value === null) return setting === "custom_parameters" ? [] : null
  if (NETWORK_SETTINGS.has(setting)) return typeof value === "boolean" ? value : undefined
  if (setting === "custom_parameters") return parseParameters(value) ?? undefined
  return typeof value === "string" ? value : undefined
}

function settingMap(value: unknown): Partial<Record<CampaignSetting, SettingValue>> {
  const values: Partial<Record<CampaignSetting, SettingValue>> = {}
  if (!isRecord(value)) return values
  for (const setting of CAMPAIGN_SETTINGS) {
    if (!Object.hasOwn(value, setting)) continue
    const parsed = settingValue(setting, value[setting])
    if (parsed !== undefined) values[setting] = parsed
  }
  return values
}

/** The settings an entry changes, read the way the server reads them. */
function requestedOf(
  entry: Record<string, unknown>
): Partial<Record<CampaignSetting, SettingValue>> {
  const values: Partial<Record<CampaignSetting, SettingValue>> = {}
  if (typeof entry["name"] === "string")
    values.name = entry["name"].split(/\s+/).filter(Boolean).join(" ")
  if (typeof entry["start_date"] === "string") values.start_date = entry["start_date"]
  if (typeof entry["end_date"] === "string")
    values.end_date = entry["end_date"] === "none" ? null : entry["end_date"]
  const url = isRecord(entry["url_options"]) ? entry["url_options"] : {}
  for (const setting of ["final_url_suffix", "tracking_template"] as const) {
    const value = url[setting]
    if (typeof value === "string") values[setting] = value.trim() || null
  }
  const parameters = parseParameters(url["custom_parameters"])
  if (parameters) values.custom_parameters = parameters
  const networks = isRecord(entry["networks"]) ? entry["networks"] : {}
  for (const setting of ["search_partners", "display_expansion"] as const) {
    const value = networks[setting]
    if (typeof value === "boolean") values[setting] = value
  }
  return values
}

function parseChange(value: unknown): CampaignChange | null {
  if (!isRecord(value) || !isRecord(value["campaign"])) return null
  const reference = value["campaign"]
  const customerId = googleAdsId(reference["customer_id"])
  const campaignId = googleAdsId(reference["campaign_id"])
  if (customerId === null || campaignId === null) return null
  return {
    campaignId,
    customerId,
    entry: value,
    key: `customers/${customerId}/campaigns/${campaignId}`,
    label: text(reference["label"]) ?? `Campaign ${campaignId}`,
    requested: requestedOf(value),
  }
}

function parseCheck(value: unknown): CampaignCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const problems: Partial<Record<CampaignSetting, string>> = {}
  const rawProblems = isRecord(value["problems"]) ? value["problems"] : {}
  for (const setting of CAMPAIGN_SETTINGS) {
    const problem = text(rawProblems[setting])
    if (problem) problems[setting] = problem
  }
  return {
    unavailable: false,
    current: settingMap(value["current"]),
    name: text(value["name"]),
    problem: text(value["problem"]),
    problems,
    requested: settingMap(value["requested"]),
  }
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseUpdateCampaignsArgs(value: unknown): UpdateCampaignsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const changes: CampaignChange[] = []
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

export function sameValue(a: SettingValue | undefined, b: SettingValue | undefined): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

function rowOf(
  change: CampaignChange | null,
  key: string,
  customerId: string,
  label: string,
  setting: CampaignSetting,
  value: SettingValue,
  check: CampaignCheck | undefined
): CampaignRow {
  const live = check && !check.unavailable ? check : null
  const was = live ? (live.current[setting] ?? null) : undefined
  // Google answered for the value it was checked with, so an edited value waits for a new check.
  const checked = live !== null && sameValue(live.requested[setting], value)
  return {
    campaignName: live?.name ?? label,
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
    unchanged: was !== undefined && sameValue(was, value),
    value,
    was,
  }
}

/** One row per campaign and setting, with cancelled settings after the ones still requested. */
export function campaignRows(
  args: UpdateCampaignsArgs,
  checked: UpdateCampaignsArgs,
  cancelled: readonly CancelledSetting[] = []
): CampaignRow[] {
  const rows: CampaignRow[] = []
  for (const change of args.changes) {
    for (const setting of CAMPAIGN_SETTINGS) {
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
  }
  const live = new Set(rows.map((row) => row.id))
  for (const item of cancelled) {
    if (live.has(`${item.key}|${item.setting}`)) continue
    const customerId = googleAdsId(item.campaign["customer_id"]) ?? ""
    const label = text(item.campaign["label"]) ?? item.key
    rows.push(
      rowOf(
        null,
        item.key,
        customerId,
        label,
        item.setting,
        item.value,
        checked.checks.get(item.key)
      )
    )
  }
  return rows
}

export function campaignCounts(rows: readonly CampaignRow[]): CampaignCounts {
  const live = rows.filter((row) => !row.cancelled)
  return {
    apply: live.filter((row) => !row.unchanged).length,
    campaigns: new Set(live.map((row) => row.key)).size,
    problems: live.filter((row) => row.problem !== null).length,
    total: live.length,
  }
}

/** Writes a setting into a raw entry in the tool's argument shape; undefined leaves it out. */
function withSetting(
  entry: Record<string, unknown>,
  setting: CampaignSetting,
  value: SettingValue | undefined
): Record<string, unknown> {
  const without = (record: Record<string, unknown>, key: string) =>
    Object.fromEntries(Object.entries(record).filter(([name]) => name !== key))
  const nested = (field: string, item: unknown) => {
    const current = isRecord(entry[field]) ? entry[field] : {}
    const group = item === undefined ? without(current, setting) : { ...current, [setting]: item }
    return Object.keys(group).length > 0 ? { ...entry, [field]: group } : without(entry, field)
  }
  if (URL_SETTINGS.has(setting))
    return nested("url_options", value === null && setting !== "custom_parameters" ? "" : value)
  if (NETWORK_SETTINGS.has(setting)) return nested("networks", value)
  if (value === undefined) return without(entry, setting)
  return { ...entry, [setting]: setting === "end_date" && value === null ? "none" : value }
}

/** The `changes` value with one setting set on the given rows, or cancelled when undefined. */
export function editedChanges(
  args: UpdateCampaignsArgs,
  ids: ReadonlySet<string>,
  value: (row: { key: string; setting: CampaignSetting }) => SettingValue | undefined
): Record<string, unknown>[] {
  return args.changes.flatMap((change) => {
    let entry = change.entry
    for (const setting of CAMPAIGN_SETTINGS) {
      if (change.requested[setting] === undefined || !ids.has(`${change.key}|${setting}`)) continue
      entry = withSetting(entry, setting, value({ key: change.key, setting }))
    }
    // An entry must change something, so a campaign with every setting cancelled leaves the request.
    return Object.keys(requestedOf(entry)).length > 0 ? [entry] : []
  })
}

/** Puts cancelled settings back, adding their campaign again when it had left the request. */
export function restoredChanges(
  args: UpdateCampaignsArgs,
  items: readonly CancelledSetting[]
): Record<string, unknown>[] {
  const entries = new Map(args.changes.map((change) => [change.key, change.entry]))
  for (const item of items) {
    const entry = entries.get(item.key) ?? { campaign: item.campaign }
    entries.set(item.key, withSetting(entry, item.setting, item.value))
  }
  return [...entries.values()]
}

export function parseCancelled(value: unknown): CancelledSetting[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item) || !isRecord(item["campaign"]) || typeof item["key"] !== "string") return []
    const setting = item["setting"]
    if (typeof setting !== "string" || !(CAMPAIGN_SETTINGS as readonly string[]).includes(setting))
      return []
    const value = settingValue(setting as CampaignSetting, item["value"])
    return value === undefined
      ? []
      : [
          {
            campaign: item["campaign"],
            key: item["key"],
            setting: setting as CampaignSetting,
            value,
          },
        ]
  })
}

function signature(args: UpdateCampaignsArgs): string {
  return JSON.stringify(
    args.changes.map((change) => [
      change.key,
      CAMPAIGN_SETTINGS.map((setting) => change.requested[setting] ?? "-"),
    ])
  )
}

export function needsCheck(args: UpdateCampaignsArgs, checked: UpdateCampaignsArgs): boolean {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    signature(args) !== signature(checked)
  )
}

/** Why the request can't be approved yet, or null. */
export function campaignsBlock(
  args: UpdateCampaignsArgs | null,
  checked: UpdateCampaignsArgs
): string | null {
  if (args === null) return null
  const counts = campaignCounts(campaignRows(args, checked))
  if (counts.total === 0) return "Every change is cancelled. Decline this request, or undo one."
  if (needsCheck(args, checked))
    return "Click Check Changes so Google can check your edits, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "change")} to continue.`
  if (counts.apply === 0) return "These campaigns already have these settings."
  return null
}

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
  year: "numeric",
})

function dateText(value: string): string {
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(date.getTime()) ? value : DATE_FORMAT.format(date)
}

export function parametersText(parameters: readonly UrlParameter[]): string {
  return parameters.map((item) => `${item.key}=${item.value}`).join(", ")
}

/** Reads `key=value, key=value`; null when a pair has no key. */
export function parseParametersText(value: string): UrlParameter[] | null {
  const pairs = value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
  const items: UrlParameter[] = []
  for (const pair of pairs) {
    const split = pair.indexOf("=")
    const key = (split === -1 ? pair : pair.slice(0, split)).trim()
    if (!key) return null
    items.push({ key, value: split === -1 ? "" : pair.slice(split + 1).trim() })
  }
  return items
}

/** A setting's value in the words the card uses. */
export function valueText(setting: CampaignSetting, value: SettingValue | undefined): string {
  if (value === undefined) return "—"
  if (typeof value === "boolean") return value ? "On" : "Off"
  if (Array.isArray(value)) return value.length > 0 ? parametersText(value) : "None"
  if (value === null) return setting === "end_date" ? "No end date" : "None"
  return setting === "start_date" || setting === "end_date" ? dateText(value) : value
}

function accountName(args: UpdateCampaignsArgs): string {
  const ids = new Set(args.changes.map((change) => change.customerId))
  const [id] = ids
  return ids.size === 1
    ? (args.accounts.get(id ?? "")?.label ?? "Google Ads")
    : `${String(ids.size)} accounts`
}

function soleRow(args: UpdateCampaignsArgs): CampaignRow | null {
  const rows = campaignRows(args, args)
  return rows.length === 1 ? (rows[0] ?? null) : null
}

export function campaignsPrompt(args: UpdateCampaignsArgs): string {
  const rows = campaignRows(args, args)
  if (rows.length === 0) return "Nothing is left to change."
  const where = accountName(args)
  const sole = soleRow(args)
  if (sole) {
    return sole.setting === "name"
      ? `Rename ${sole.campaignName} to ${valueText("name", sole.value)} in ${where}.`
      : `Change the ${SETTING_TITLES[sole.setting].toLowerCase()} of ${sole.campaignName} in ${where}.`
  }
  const campaigns = new Set(rows.map((row) => row.key)).size
  const target =
    campaigns === 1
      ? (rows[0]?.campaignName ?? "1 campaign")
      : approvalCountLine(campaigns, "campaign")
  return `Change ${approvalCountLine(rows.length, "setting")} on ${target} in ${where}.`
}

/** Names the change when there is only one; otherwise counts what's sent. */
export function campaignsApproveLabel(args: UpdateCampaignsArgs): string {
  const sole = soleRow(args)
  if (sole && !sole.unchanged) {
    if (sole.setting === "name") return "Rename Campaign"
    if (sole.setting === "end_date") return sole.value === null ? "Remove End Date" : "Set End Date"
    if (typeof sole.value === "boolean")
      return `Turn ${sole.value ? "On" : "Off"} ${SETTING_TITLES[sole.setting]}`
    return `Change ${SETTING_TITLES[sole.setting]}`
  }
  const { apply } = campaignCounts(campaignRows(args, args))
  return apply === 0
    ? "Apply Changes"
    : `Apply ${String(apply)} ${apply === 1 ? "Change" : "Changes"}`
}

export function campaignsBannerDetail(
  counts: CampaignCounts,
  accountIds: readonly string[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>
): string {
  const timeZone = accountIds.length === 1 ? accounts.get(accountIds[0] ?? "")?.timeZone : undefined
  return [
    approvalCountLine(counts.campaigns, "campaign"),
    timeZone ? `Account time ${timeZone}` : null,
  ]
    .filter((part) => part !== null)
    .join(" · ")
}

export function campaignsDetails(args: UpdateCampaignsArgs | null): FanOutDetail[] {
  return args ? [{ label: "Campaigns", value: String(args.changes.length) }] : []
}
