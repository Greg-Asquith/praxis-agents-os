// apps/web/src/integrations/google_ads/lib/update-keywords.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { canonicalMoney } from "@/integrations/google_ads/lib/campaign-bidding"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { MATCH_TYPE_LABELS, MATCH_TYPES } from "@/integrations/google_ads/lib/negative-keywords"
import { parametersText, type UrlParameter } from "@/integrations/google_ads/lib/update-campaigns"
import { formatCurrencyAmount } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const KEYWORD_SETTINGS = [
  "match_type",
  "cpc_bid",
  "final_urls",
  "final_mobile_urls",
  "final_url_suffix",
  "tracking_template",
  "custom_parameters",
] as const

export type KeywordSetting = (typeof KEYWORD_SETTINGS)[number]
// Card terms, as the server sends them: money as a decimal string, URLs as lists, and null for
// none, which for a max CPC means the keyword uses its ad group's bid.
export type KeywordValue = string | string[] | UrlParameter[] | null

export const KEYWORD_SETTING_TITLES: Record<KeywordSetting, string> = {
  cpc_bid: "Max CPC",
  custom_parameters: "Custom Parameters",
  final_mobile_urls: "Mobile URLs",
  final_url_suffix: "Final URL Suffix",
  final_urls: "Final URLs",
  match_type: "Match Type",
  tracking_template: "Tracking Template",
}

const URL_OPTIONS = new Set<KeywordSetting>([
  "final_url_suffix",
  "tracking_template",
  "custom_parameters",
])
const URL_LISTS = new Set<KeywordSetting>(["final_urls", "final_mobile_urls"])
const URL_PATTERN = /^https?:\/\/\S+$/i

type KeywordChange = {
  customerId: string
  // The change as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  key: string
  label: string
  matchType: KeywordMatchType | null
  requested: Partial<Record<KeywordSetting, KeywordValue>>
}

type KeywordCheck =
  | { unavailable: true }
  | {
      unavailable: false
      adGroupName: string | null
      // Whether the campaign's strategy uses keyword bids.
      bidsUsed: boolean
      campaignName: string | null
      current: Partial<Record<KeywordSetting, KeywordValue>>
      matchType: KeywordMatchType | null
      problem: string | null
      problems: Partial<Record<KeywordSetting, string>>
      requested: Partial<Record<KeywordSetting, KeywordValue>>
      strategyName: string | null
      text: string | null
    }

export type UpdateKeywordsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  changes: KeywordChange[]
  checks: Map<string, KeywordCheck>
}

// A setting the operator cancelled, kept beside the request so Undo can bring it back.
export type CancelledKeywordSetting = {
  key: string
  keyword: Record<string, unknown>
  setting: KeywordSetting
  value: KeywordValue
}

export type KeywordRow = {
  adGroupName: string | null
  // Whether the campaign's strategy uses keyword bids; null when it couldn't be read.
  bidsUsed: boolean | null
  campaignName: string | null
  cancelled: boolean
  change: KeywordChange | null
  customerId: string
  id: string
  key: string
  // The keyword's live match type, or the reference's when it couldn't be read.
  matchType: KeywordMatchType | null
  // Blocks approval while set.
  problem: string | null
  setting: KeywordSetting
  strategyName: string | null
  text: string
  // Same as the live value, so nothing is sent for it.
  unchanged: boolean
  value: KeywordValue
  // Undefined when the live value couldn't be read.
  was: KeywordValue | undefined
}

/** The resource name of the ad group a keyword row is in, from the keyword's own name. */
export function keywordAdGroup(row: Pick<KeywordRow, "key">): string {
  return row.key.replace("/adGroupCriteria/", "/adGroups/").replace(/~\d+$/, "")
}

export type KeywordCounts = {
  adGroups: number
  apply: number
  keywords: number
  problems: number
  total: number
}

const UNAVAILABLE_PROBLEM =
  "Google Ads couldn't check this keyword. Ask the agent to prepare the change again."

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function matchType(value: unknown): KeywordMatchType | null {
  return MATCH_TYPES.find((item) => item === value) ?? null
}

function strings(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  return value.every((item) => typeof item === "string") ? value : null
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
export function keywordValue(setting: KeywordSetting, value: unknown): KeywordValue | undefined {
  if (setting === "custom_parameters") return value === null ? [] : (parameters(value) ?? undefined)
  if (URL_LISTS.has(setting)) return value === null ? [] : (strings(value) ?? undefined)
  if (setting === "match_type") return matchType(value) ?? undefined
  if (value === null) return null
  if (setting === "cpc_bid")
    return typeof value === "string" && value.trim() ? canonicalMoney(value) : undefined
  return typeof value === "string" ? value : undefined
}

function settingMap(value: unknown): Partial<Record<KeywordSetting, KeywordValue>> {
  const values: Partial<Record<KeywordSetting, KeywordValue>> = {}
  if (!isRecord(value)) return values
  for (const setting of KEYWORD_SETTINGS) {
    if (!Object.hasOwn(value, setting)) continue
    const parsed = keywordValue(setting, value[setting])
    if (parsed !== undefined) values[setting] = parsed
  }
  return values
}

/** The settings an entry changes, read the way the server reads them. */
function requestedOf(
  entry: Record<string, unknown>
): Partial<Record<KeywordSetting, KeywordValue>> {
  const values: Partial<Record<KeywordSetting, KeywordValue>> = {}
  const match = matchType(entry["match_type"])
  if (match) values.match_type = match
  // "none" removes the keyword's own bid, so it uses its ad group's.
  if (entry["cpc_bid"] === "none") values.cpc_bid = null
  else if (text(entry["cpc_bid"])) values.cpc_bid = canonicalMoney(String(entry["cpc_bid"]))
  for (const setting of ["final_urls", "final_mobile_urls"] as const) {
    const urls = strings(entry[setting])
    if (urls) values[setting] = urls
  }
  const url = isRecord(entry["url_options"]) ? entry["url_options"] : {}
  for (const setting of ["final_url_suffix", "tracking_template"] as const) {
    const value = url[setting]
    if (typeof value === "string") values[setting] = value.trim() || null
  }
  const custom = parameters(url["custom_parameters"])
  if (custom) values.custom_parameters = custom
  return values
}

function parseChange(value: unknown): KeywordChange | null {
  if (!isRecord(value) || !isRecord(value["keyword"])) return null
  const reference = value["keyword"]
  const customerId = googleAdsId(reference["customer_id"])
  const adGroupId = googleAdsId(reference["ad_group_id"])
  const criterionId = googleAdsId(reference["criterion_id"])
  if (customerId === null || adGroupId === null || criterionId === null) return null
  return {
    customerId,
    entry: value,
    key: `customers/${customerId}/adGroupCriteria/${adGroupId}~${criterionId}`,
    label: text(reference["label"]) ?? text(reference["text"]) ?? `Keyword ${criterionId}`,
    matchType: matchType(reference["match_type"]),
    requested: requestedOf(value),
  }
}

function parseCheck(value: unknown): KeywordCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const problems: Partial<Record<KeywordSetting, string>> = {}
  const rawProblems = isRecord(value["problems"]) ? value["problems"] : {}
  for (const setting of KEYWORD_SETTINGS) {
    const problem = text(rawProblems[setting])
    if (problem) problems[setting] = problem
  }
  const bids = Array.isArray(value["bids_used"]) ? value["bids_used"] : []
  return {
    unavailable: false,
    adGroupName: text(value["ad_group_name"]),
    bidsUsed: bids.includes("cpc_bid"),
    campaignName: text(value["campaign_name"]),
    current: settingMap(value["current"]),
    matchType: matchType(value["match_type"]),
    problem: text(value["problem"]),
    problems,
    requested: settingMap(value["requested"]),
    strategyName: text(value["strategy_name"]),
    text: text(value["text"]),
  }
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseUpdateKeywordsArgs(value: unknown): UpdateKeywordsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const changes: KeywordChange[] = []
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

function sameKeywordValue(a: KeywordValue | undefined, b: KeywordValue | undefined) {
  return JSON.stringify(a) === JSON.stringify(b)
}

function emptyValue(setting: KeywordSetting): KeywordValue {
  return URL_LISTS.has(setting) || setting === "custom_parameters" ? [] : null
}

function rowOf(
  change: KeywordChange | null,
  item: { customerId: string; key: string; label: string; matchType: KeywordMatchType | null },
  setting: KeywordSetting,
  value: KeywordValue,
  check: KeywordCheck | undefined
): KeywordRow {
  const live = check && !check.unavailable ? check : null
  const was = live ? (live.current[setting] ?? emptyValue(setting)) : undefined
  // Google answered for the value it was checked with, so an edited value waits for a new check.
  const checked = live !== null && sameKeywordValue(live.requested[setting], value)
  return {
    adGroupName: live?.adGroupName ?? null,
    bidsUsed: live?.bidsUsed ?? null,
    campaignName: live?.campaignName ?? null,
    cancelled: change === null,
    change,
    customerId: item.customerId,
    id: `${item.key}|${setting}`,
    key: item.key,
    matchType: live?.matchType ?? item.matchType,
    problem:
      live === null
        ? UNAVAILABLE_PROBLEM
        : checked
          ? (live.problem ?? live.problems[setting] ?? null)
          : null,
    setting,
    strategyName: live?.strategyName ?? null,
    text: live?.text ?? item.label,
    unchanged: was !== undefined && sameKeywordValue(was, value),
    value,
    was,
  }
}

/** One row per keyword and setting, with cancelled settings after the ones still requested. */
export function keywordRows(
  args: UpdateKeywordsArgs,
  checked: UpdateKeywordsArgs,
  cancelled: readonly CancelledKeywordSetting[] = []
): KeywordRow[] {
  const rows: KeywordRow[] = []
  for (const change of args.changes)
    for (const setting of KEYWORD_SETTINGS) {
      const value = change.requested[setting]
      if (value === undefined) continue
      rows.push(rowOf(change, change, setting, value, checked.checks.get(change.key)))
    }
  const live = new Set(rows.map((row) => row.id))
  for (const item of cancelled) {
    if (live.has(`${item.key}|${item.setting}`)) continue
    const reference = item.keyword
    rows.push(
      rowOf(
        null,
        {
          customerId: googleAdsId(reference["customer_id"]) ?? "",
          key: item.key,
          label: text(reference["label"]) ?? item.key,
          matchType: matchType(reference["match_type"]),
        },
        item.setting,
        item.value,
        checked.checks.get(item.key)
      )
    )
  }
  return rows
}

export function keywordCounts(rows: readonly KeywordRow[]): KeywordCounts {
  const live = rows.filter((row) => !row.cancelled)
  return {
    adGroups: new Set(live.map((row) => row.adGroupName ?? row.key)).size,
    apply: live.filter((row) => !row.unchanged).length,
    keywords: new Set(live.map((row) => row.key)).size,
    problems: live.filter((row) => row.problem !== null).length,
    total: live.length,
  }
}

/** Whether a row's change pauses its keyword and adds the same text with another match type. */
export function replacesKeyword(row: Pick<KeywordRow, "setting" | "unchanged">): boolean {
  return row.setting === "match_type" && !row.unchanged
}

function without(record: Record<string, unknown>, key: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key))
}

/** Writes a setting into a raw entry in the tool's argument shape; undefined leaves it out. */
function withSetting(
  entry: Record<string, unknown>,
  setting: KeywordSetting,
  value: KeywordValue | undefined
): Record<string, unknown> {
  if (URL_OPTIONS.has(setting)) {
    const current = isRecord(entry["url_options"]) ? entry["url_options"] : {}
    const item = value === null && setting !== "custom_parameters" ? "" : value
    const group = item === undefined ? without(current, setting) : { ...current, [setting]: item }
    return Object.keys(group).length > 0
      ? { ...entry, url_options: group }
      : without(entry, "url_options")
  }
  if (value === undefined) return without(entry, setting)
  // Removing a keyword's own bid is "none", so it uses its ad group's.
  return { ...entry, [setting]: setting === "cpc_bid" ? (value ?? "none") : value }
}

/** The `changes` value with one setting set on the given rows, or cancelled when undefined. */
export function editedKeywordChanges(
  args: UpdateKeywordsArgs,
  ids: ReadonlySet<string>,
  value: (row: { key: string; setting: KeywordSetting }) => KeywordValue | undefined
): Record<string, unknown>[] {
  return args.changes.flatMap((change) => {
    let entry = change.entry
    for (const setting of KEYWORD_SETTINGS) {
      if (change.requested[setting] === undefined || !ids.has(`${change.key}|${setting}`)) continue
      entry = withSetting(entry, setting, value({ key: change.key, setting }))
    }
    // An entry must change something, so a keyword with every setting cancelled leaves.
    return Object.keys(requestedOf(entry)).length > 0 ? [entry] : []
  })
}

/** Settings the request doesn't change on a keyword yet, each starting at its live value.

A max CPC is offered only where the campaign's strategy uses keyword bids.
 */
export function addableSettings(
  checked: UpdateKeywordsArgs,
  rows: readonly KeywordRow[],
  key: string
): { setting: KeywordSetting; value: KeywordValue }[] {
  const check = checked.checks.get(key)
  if (!check || check.unavailable) return []
  const present = new Set(rows.filter((row) => row.key === key).map((row) => row.setting))
  return KEYWORD_SETTINGS.flatMap((setting) => {
    if (present.has(setting) || (setting === "cpc_bid" && !check.bidsUsed)) return []
    const value = check.current[setting] ?? emptyValue(setting)
    return setting === "match_type" && value === null ? [] : [{ setting, value }]
  })
}

/** The `changes` value with a setting added to one keyword already in the request. */
export function addedKeywordChanges(
  args: UpdateKeywordsArgs,
  key: string,
  setting: KeywordSetting,
  value: KeywordValue
): Record<string, unknown>[] {
  return args.changes.map((change) =>
    change.key === key ? withSetting(change.entry, setting, value) : change.entry
  )
}

/** Puts cancelled settings back, adding their keyword again when it had left the request. */
export function restoredKeywordChanges(
  args: UpdateKeywordsArgs,
  items: readonly CancelledKeywordSetting[]
): Record<string, unknown>[] {
  const entries = new Map(args.changes.map((change) => [change.key, change.entry]))
  for (const item of items) {
    const entry = entries.get(item.key) ?? { keyword: item.keyword }
    entries.set(item.key, withSetting(entry, item.setting, item.value))
  }
  return [...entries.values()]
}

export function parseCancelledKeywordSettings(value: unknown): CancelledKeywordSetting[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item) || !isRecord(item["keyword"]) || typeof item["key"] !== "string") return []
    const setting = KEYWORD_SETTINGS.find((name) => name === item["setting"])
    const parsed = setting ? keywordValue(setting, item["value"]) : undefined
    return setting && parsed !== undefined
      ? [{ key: item["key"], keyword: item["keyword"], setting, value: parsed }]
      : []
  })
}

/** Reads URLs separated by spaces or new lines; null when one isn't a full web address. */
export function parseUrls(value: string): string[] | null {
  const urls = value.split(/\s+/).filter(Boolean)
  return urls.every((url) => URL_PATTERN.test(url)) ? urls : null
}

function signature(args: UpdateKeywordsArgs): string {
  return JSON.stringify(
    args.changes.map((change) => [
      change.key,
      KEYWORD_SETTINGS.map((setting) => change.requested[setting] ?? "-"),
    ])
  )
}

export function keywordsNeedCheck(args: UpdateKeywordsArgs, checked: UpdateKeywordsArgs) {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    signature(args) !== signature(checked)
  )
}

/** Why the request can't be approved yet, or null. */
export function keywordsBlock(
  args: UpdateKeywordsArgs | null,
  checked: UpdateKeywordsArgs
): string | null {
  if (args === null) return null
  const counts = keywordCounts(keywordRows(args, checked))
  if (counts.total === 0) return "Every change is cancelled. Decline this request, or undo one."
  if (keywordsNeedCheck(args, checked))
    return "Click Check Changes so Google can check your edits, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "change")} to continue.`
  if (counts.apply === 0) return "These keywords already have these settings."
  return null
}

/** A setting's value in the words the card uses. */
export function keywordValueText(
  setting: KeywordSetting,
  value: KeywordValue | undefined,
  currency: string | null
): string {
  if (value === undefined) return "—"
  if (setting === "match_type") {
    const match = matchType(value)
    return match ? MATCH_TYPE_LABELS[match] : "—"
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "None"
    return setting === "custom_parameters"
      ? parametersText(value as UrlParameter[])
      : (value as string[]).join(" ")
  }
  if (value === null) return setting === "cpc_bid" ? "Ad group's bid" : "None"
  if (setting === "cpc_bid") return currency ? formatCurrencyAmount(value, currency) : value
  return value
}

export function keywordCurrency(args: UpdateKeywordsArgs, row: KeywordRow): string | null {
  return args.accounts.get(row.customerId)?.currencyCode ?? null
}

function soleRow(args: UpdateKeywordsArgs): KeywordRow | null {
  const rows = keywordRows(args, args)
  return rows.length === 1 ? (rows[0] ?? null) : null
}

export function keywordsPrompt(args: UpdateKeywordsArgs): string {
  const rows = keywordRows(args, args)
  if (rows.length === 0) return "Nothing is left to change."
  const sole = soleRow(args)
  // The banner names the account, so a sole change's prompt names only the keyword.
  if (sole) {
    if (sole.setting === "match_type" && typeof sole.value === "string")
      return `Change “${sole.text}” to ${keywordValueText("match_type", sole.value, null).toLowerCase()} match.`
    if (sole.setting === "cpc_bid" && sole.value === null)
      return `Remove the max CPC of “${sole.text}”, so it uses its ad group's bid.`
    return `Change the ${KEYWORD_SETTING_TITLES[sole.setting].toLowerCase()} of “${sole.text}”.`
  }
  const counts = keywordCounts(rows)
  const ids = new Set(args.changes.map((change) => change.customerId))
  const [id] = ids
  const where =
    ids.size === 1
      ? (args.accounts.get(id ?? "")?.label ?? "Google Ads")
      : `${String(ids.size)} accounts`
  return `Change ${approvalCountLine(counts.keywords, "keyword")} in ${where}.`
}

/** Names the change when there is only one; otherwise counts what's sent. */
export function keywordsApproveLabel(args: UpdateKeywordsArgs): string {
  const sole = soleRow(args)
  if (sole && !sole.unchanged)
    return sole.setting === "cpc_bid" && sole.value === null
      ? "Remove Max CPC"
      : `Change ${KEYWORD_SETTING_TITLES[sole.setting]}`
  const { apply } = keywordCounts(keywordRows(args, args))
  return apply === 0
    ? "Apply Changes"
    : `Apply ${apply.toLocaleString("en-GB")} ${apply === 1 ? "Change" : "Changes"}`
}

export function keywordsBannerDetail(
  counts: KeywordCounts,
  accountIds: readonly string[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>
): string {
  const account = accountIds.length === 1 ? accounts.get(accountIds[0] ?? "") : undefined
  return [
    account?.label ?? null,
    counts.keywords > 1
      ? `${approvalCountLine(counts.keywords, "keyword")} in ${approvalCountLine(counts.adGroups, "ad group")}`
      : null,
  ]
    .filter((part) => part !== null)
    .join(" · ")
}

export function keywordsDetails(args: UpdateKeywordsArgs | null): FanOutDetail[] {
  return args ? [{ label: "Keywords", value: String(args.changes.length) }] : []
}
