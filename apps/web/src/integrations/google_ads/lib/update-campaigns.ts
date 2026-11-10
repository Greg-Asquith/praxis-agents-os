// apps/web/src/integrations/google_ads/lib/update-campaigns.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import {
  biddingArgument,
  biddingProblem,
  biddingText,
  changesStrategy,
  comparableBidding,
  parseBidding,
  resolvedBidding,
  STANDARD_STRATEGIES,
  strategyLabel,
  TARGET_KEYS,
  TARGET_LABELS,
  TARGETS,
  type Bidding,
  type BiddingContext,
} from "@/integrations/google_ads/lib/campaign-bidding"
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
  "bidding",
] as const

export type CampaignSetting = (typeof CAMPAIGN_SETTINGS)[number]
export type UrlParameter = { key: string; value: string }
// Card terms, as the server sends them: dates as YYYY-MM-DD, and null for none.
export type SettingValue = string | boolean | UrlParameter[] | Bidding | null

export const SETTING_TITLES: Record<CampaignSetting, string> = {
  bidding: "Bidding",
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
      channel: string | null
      current: Partial<Record<CampaignSetting, SettingValue>>
      name: string | null
      // Notes about a bidding change, such as recent conversions and ad groups' own bids.
      notes: string[]
      portfolios: Map<string, string>
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
  // A bidding change that moves to another strategy, so Google's learning restarts.
  learning: boolean
  // Shown under the change while it matches what Google last checked.
  notes: string[]
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
  learning: number
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
  if (setting === "bidding") return parseBidding(value) ?? undefined
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
  const bidding = parseBidding(entry["bidding"])
  if (bidding) values.bidding = bidding
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
  const notes = isRecord(value["notes"]) ? value["notes"]["bidding"] : null
  const portfolios = new Map<string, string>()
  if (isRecord(value["portfolios"]))
    for (const [name, item] of Object.entries(value["portfolios"]))
      if (isRecord(item) && typeof item["name"] === "string") portfolios.set(name, item["name"])
  return {
    unavailable: false,
    channel: text(value["channel"]),
    current: settingMap(value["current"]),
    name: text(value["name"]),
    notes: Array.isArray(notes) ? notes.filter((note) => typeof note === "string") : [],
    portfolios,
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

function comparable(value: SettingValue | undefined): unknown {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? comparableBidding(value)
    : value
}

export function sameValue(a: SettingValue | undefined, b: SettingValue | undefined): boolean {
  return JSON.stringify(comparable(a)) === JSON.stringify(comparable(b))
}

export function isBidding(value: SettingValue | undefined): value is Bidding {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

/** The value a row leaves the campaign on: a targets-only bidding change merged into the live one. */
function rowResult(row: Pick<CampaignRow, "value" | "was">): SettingValue {
  if (!isBidding(row.value)) return row.value
  const resolved = resolvedBidding(row.value, isBidding(row.was) ? row.was : undefined)
  // A target the live strategy can't take changes nothing yet, so it never reads as Already Set.
  return resolved.problem === null ? resolved.bidding : row.value
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
  const result = rowResult({ value, was })
  const local = isBidding(value) ? biddingProblem(value) : null
  return {
    campaignName: live?.name ?? label,
    cancelled: change === null,
    change,
    customerId,
    id: `${key}|${setting}`,
    key,
    learning:
      isBidding(result) &&
      result.strategy !== TARGETS &&
      isBidding(was) &&
      changesStrategy(result, was),
    notes: live !== null && checked && setting === "bidding" ? live.notes : [],
    problem:
      local ??
      (live === null
        ? UNAVAILABLE_PROBLEM
        : checked
          ? (live.problem ?? live.problems[setting] ?? null)
          : null),
    setting,
    unchanged: was !== undefined && sameValue(was, result),
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
    learning: new Set(live.filter((row) => row.learning).map((row) => row.key)).size,
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
  if (isBidding(value)) {
    const argument = biddingArgument(value)
    return argument ? { ...entry, bidding: argument } : entry
  }
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

// The channels on which each network can change, as on the server.
const NETWORK_CHANNELS: Partial<Record<CampaignSetting, readonly string[]>> = {
  display_expansion: ["SEARCH"],
  search_partners: ["SEARCH", "SHOPPING"],
}

/** Today's date in a time zone, as `YYYY-MM-DD`. */
function today(timeZone: string | undefined): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date())
  } catch {
    return new Date().toISOString().slice(0, 10)
  }
}

/** Settings the request doesn't change on a campaign yet, each starting at its live value.

Networks are offered only on channels that take them, a start date only before the campaign
starts, and bidding only from a standard strategy the card can write back.
 */
export function addableCampaignSettings(
  args: UpdateCampaignsArgs,
  checked: UpdateCampaignsArgs,
  rows: readonly CampaignRow[],
  key: string
): { setting: CampaignSetting; value: SettingValue }[] {
  const check = checked.checks.get(key)
  const change = args.changes.find((item) => item.key === key)
  if (!check || check.unavailable || !change) return []
  const present = new Set(rows.filter((row) => row.key === key).map((row) => row.setting))
  const started =
    typeof check.current.start_date !== "string" ||
    check.current.start_date <= today(args.accounts.get(change.customerId)?.timeZone)
  return CAMPAIGN_SETTINGS.flatMap((setting) => {
    const live = check.current[setting] ?? (setting === "custom_parameters" ? [] : null)
    const channels = NETWORK_CHANNELS[setting]
    if (
      present.has(setting) ||
      (channels && !channels.includes(check.channel ?? "")) ||
      (setting === "start_date" && started) ||
      (setting === "name" && live === null) ||
      (setting === "bidding" &&
        !(isBidding(live) && (STANDARD_STRATEGIES as readonly string[]).includes(live.strategy)))
    )
      return []
    return [{ setting, value: live }]
  })
}

/** The `changes` value with a setting added to one campaign already in the request. */
export function addedCampaignChanges(
  args: UpdateCampaignsArgs,
  key: string,
  setting: CampaignSetting,
  value: SettingValue
): Record<string, unknown>[] {
  return args.changes.map((change) =>
    change.key === key ? withSetting(change.entry, setting, value) : change.entry
  )
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

/** Whether Google can check the request: every bidding change is complete. */
export function canCheckCampaigns(args: UpdateCampaignsArgs): boolean {
  return args.changes.every((change) => {
    const bidding = change.requested.bidding
    return !isBidding(bidding) || biddingProblem(bidding) === null
  })
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

const NO_CONTEXT: BiddingContext = { currency: null, portfolios: new Map() }

/** The account currency and portfolio names a row's bidding is written with. */
export function rowContext(args: UpdateCampaignsArgs, row: CampaignRow): BiddingContext {
  const check = args.checks.get(row.key)
  return {
    currency: args.accounts.get(row.customerId)?.currencyCode ?? null,
    portfolios: check && !check.unavailable ? check.portfolios : NO_CONTEXT.portfolios,
  }
}

/** A setting's value in the words the card uses. */
export function valueText(
  setting: CampaignSetting,
  value: SettingValue | undefined,
  context: BiddingContext = NO_CONTEXT
): string {
  if (value === undefined) return "—"
  if (isBidding(value)) return biddingText(value, context)
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
  // The banner names the account, so a sole change's prompt names only the campaign.
  if (sole) {
    if (sole.setting === "name")
      return `Rename ${sole.campaignName} to ${valueText("name", sole.value)}.`
    if (isBidding(sole.value)) return biddingPrompt(sole, sole.value)
    return `Change the ${SETTING_TITLES[sole.setting].toLowerCase()} of ${sole.campaignName}.`
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
    if (isBidding(sole.value)) return biddingApproveLabel(sole)
    return `Change ${SETTING_TITLES[sole.setting]}`
  }
  const { apply } = campaignCounts(campaignRows(args, args))
  return apply === 0
    ? "Apply Changes"
    : `Apply ${String(apply)} ${apply === 1 ? "Change" : "Changes"}`
}

// Each target as a sentence names it.
const TARGET_NAMES = {
  max_cpc: "maximum click bid",
  target_cpa: "target CPA",
  target_roas: "target ROAS",
} as const

// The target a target-only change names, for its prompt and button.
function changedTarget(value: SettingValue): (typeof TARGET_KEYS)[number] | null {
  if (!isBidding(value) || value.strategy !== TARGETS) return null
  return TARGET_KEYS.find((key) => value[key] != null) ?? null
}

function biddingPrompt(row: CampaignRow, value: Bidding): string {
  const target = changedTarget(value)
  if (target) return `Change the ${TARGET_NAMES[target]} of ${row.campaignName}.`
  return row.learning
    ? `Switch ${row.campaignName} to ${strategyLabel(value.strategy)}.`
    : `Change the bidding of ${row.campaignName}.`
}

function biddingApproveLabel(row: CampaignRow): string {
  const value = rowResult(row)
  if (row.learning && isBidding(value)) return `Switch to ${strategyLabel(value.strategy)}`
  const target = changedTarget(row.value)
  return target ? `Change ${TARGET_LABELS[target]}` : "Change Bidding"
}

/** The banner leads with Google's learning restarting when a strategy changes. */
export function campaignsBannerTitle(counts: CampaignCounts): string {
  if (counts.learning === 0) return "Changes take effect straight away"
  return counts.campaigns === 1
    ? "Google's learning restarts"
    : `Google's learning restarts on ${approvalCountLine(counts.learning, "campaign")}`
}

export function campaignsBannerDetail(
  counts: CampaignCounts,
  accountIds: readonly string[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>
): string[] {
  const account = accountIds.length === 1 ? accounts.get(accountIds[0] ?? "") : undefined
  const where = [
    account?.label ?? null,
    counts.campaigns > 1 ? approvalCountLine(counts.campaigns, "campaign") : null,
    account?.timeZone ? `Account time ${account.timeZone}` : null,
  ]
    .filter((part) => part !== null)
    .join(" · ")
  return [
    counts.learning > 0
      ? "Changes take effect straight away. Results can swing for 1–2 weeks while Google relearns."
      : null,
    where,
  ].filter((line): line is string => Boolean(line))
}

export function campaignsDetails(args: UpdateCampaignsArgs | null): FanOutDetail[] {
  return args ? [{ label: "Campaigns", value: String(args.changes.length) }] : []
}
