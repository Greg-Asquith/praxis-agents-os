// apps/web/src/integrations/google_ads/lib/update-keywords.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import { groupedByParent } from "@/integrations/ads/lib/parent-rows"
import {
  accountsText,
  parseCheckedEntries,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { canonicalMoney } from "@/integrations/google_ads/lib/campaign-bidding"
import {
  applyChangesLabel,
  approvalCountLine,
  changesBlock,
  unavailableProblem,
} from "@/integrations/google_ads/lib/copy"
import {
  googleAdsId,
  parseGoogleAdsUrlList,
  textOrNull,
} from "@/integrations/google_ads/lib/field-values"
import { MATCH_TYPE_LABELS, MATCH_TYPES } from "@/integrations/google_ads/lib/negative-keywords"
import {
  editedSettingChanges,
  isUrlOption,
  parametersText,
  parseSettingMap,
  parseUrlParameters,
  requestedUrlOptions,
  restoredSettingChanges,
  settingsNeedCheck,
  soleRow,
  withoutKey,
  withUrlOption,
  type UrlParameter,
} from "@/integrations/google_ads/lib/setting-changes"
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

const URL_LISTS = new Set<KeywordSetting>(["final_urls", "final_mobile_urls"])

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

const UNAVAILABLE_PROBLEM = unavailableProblem("keyword")

function matchType(value: unknown): KeywordMatchType | null {
  return MATCH_TYPES.find((item) => item === value) ?? null
}

function strings(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  return value.every((item) => typeof item === "string") ? value : null
}

/** Reads one setting's value in card terms; undefined when it isn't one. */
export function keywordValue(setting: KeywordSetting, value: unknown): KeywordValue | undefined {
  if (setting === "custom_parameters")
    return value === null ? [] : (parseUrlParameters(value) ?? undefined)
  if (URL_LISTS.has(setting)) return value === null ? [] : (strings(value) ?? undefined)
  if (setting === "match_type") return matchType(value) ?? undefined
  if (value === null) return null
  if (setting === "cpc_bid")
    return typeof value === "string" && value.trim() ? canonicalMoney(value) : undefined
  return typeof value === "string" ? value : undefined
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
  else if (textOrNull(entry["cpc_bid"])) values.cpc_bid = canonicalMoney(String(entry["cpc_bid"]))
  for (const setting of ["final_urls", "final_mobile_urls"] as const) {
    const urls = strings(entry[setting])
    if (urls) values[setting] = urls
  }
  Object.assign(values, requestedUrlOptions(entry))
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
    label:
      textOrNull(reference["label"]) ?? textOrNull(reference["text"]) ?? `Keyword ${criterionId}`,
    matchType: matchType(reference["match_type"]),
    requested: requestedOf(value),
  }
}

function parseCheck(value: unknown): KeywordCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const problems: Partial<Record<KeywordSetting, string>> = {}
  const rawProblems = isRecord(value["problems"]) ? value["problems"] : {}
  for (const setting of KEYWORD_SETTINGS) {
    const problem = textOrNull(rawProblems[setting])
    if (problem) problems[setting] = problem
  }
  const bids = Array.isArray(value["bids_used"]) ? value["bids_used"] : []
  return {
    unavailable: false,
    adGroupName: textOrNull(value["ad_group_name"]),
    bidsUsed: bids.includes("cpc_bid"),
    campaignName: textOrNull(value["campaign_name"]),
    current: parseSettingMap(KEYWORD_SETTINGS, keywordValue, value["current"]),
    matchType: matchType(value["match_type"]),
    problem: textOrNull(value["problem"]),
    problems,
    requested: parseSettingMap(KEYWORD_SETTINGS, keywordValue, value["requested"]),
    strategyName: textOrNull(value["strategy_name"]),
    text: textOrNull(value["text"]),
  }
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseUpdateKeywordsArgs(value: unknown): UpdateKeywordsArgs | null {
  const parsed = parseCheckedEntries(value, "changes", parseChange, parseCheck)
  return parsed && { accounts: parsed.accounts, changes: parsed.entries, checks: parsed.checks }
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
          label: textOrNull(reference["label"]) ?? item.key,
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
    adGroups: new Set(live.map(keywordAdGroup)).size,
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

/** Writes a setting into a raw entry in the tool's argument shape; undefined leaves it out. */
function withSetting(
  entry: Record<string, unknown>,
  setting: KeywordSetting,
  value: KeywordValue | undefined
): Record<string, unknown> {
  if (isUrlOption(setting)) return withUrlOption(entry, setting, value)
  if (value === undefined) return withoutKey(entry, setting)
  // Removing a keyword's own bid is "none", so it uses its ad group's.
  return { ...entry, [setting]: setting === "cpc_bid" ? (value ?? "none") : value }
}

const CARD = { requestedOf, settings: KEYWORD_SETTINGS, withSetting }

/** The `changes` value with one setting set on the given rows, or cancelled when undefined. */
export function editedKeywordChanges(
  args: UpdateKeywordsArgs,
  ids: ReadonlySet<string>,
  value: (row: { key: string; setting: KeywordSetting }) => KeywordValue | undefined
): Record<string, unknown>[] {
  return editedSettingChanges(CARD, args.changes, ids, value)
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
  return restoredSettingChanges(CARD, args.changes, items, (item) => ({ keyword: item.keyword }))
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

/** Reads URLs separated by spaces or new lines; null when Google Ads wouldn't accept them. */
export function parseUrls(value: string): string[] | null {
  return parseGoogleAdsUrlList(value.split(/\s+/).filter(Boolean)) ?? null
}

export function keywordsNeedCheck(args: UpdateKeywordsArgs, checked: UpdateKeywordsArgs) {
  return settingsNeedCheck(KEYWORD_SETTINGS, args, checked)
}

/** Why the request can't be approved yet, or null. */
export function keywordsBlock(
  args: UpdateKeywordsArgs | null,
  checked: UpdateKeywordsArgs
): string | null {
  if (args === null) return null
  return changesBlock(
    keywordCounts(keywordRows(args, checked)),
    keywordsNeedCheck(args, checked),
    "These keywords already have these settings."
  )
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

export function keywordsPrompt(args: UpdateKeywordsArgs): string {
  const rows = keywordRows(args, args)
  if (rows.length === 0) return "Nothing is left to change."
  const sole = soleRow(rows)
  // The banner names the account, so a sole change's prompt names only the keyword.
  if (sole) {
    if (sole.setting === "match_type" && typeof sole.value === "string")
      return `Change “${sole.text}” to ${keywordValueText("match_type", sole.value, null).toLowerCase()} match.`
    if (sole.setting === "cpc_bid" && sole.value === null)
      return `Remove the max CPC of “${sole.text}”, so it uses its ad group's bid.`
    return `Change the ${KEYWORD_SETTING_TITLES[sole.setting].toLowerCase()} of “${sole.text}”.`
  }
  const counts = keywordCounts(rows)
  const where = accountsText(
    args.accounts,
    args.changes.map((change) => change.customerId)
  )
  return `Change ${approvalCountLine(counts.keywords, "keyword")} in ${where}.`
}

/** Names the change when there is only one; otherwise counts what's sent. */
export function keywordsApproveLabel(args: UpdateKeywordsArgs): string {
  const rows = keywordRows(args, args)
  const sole = soleRow(rows)
  if (sole && !sole.unchanged)
    return sole.setting === "cpc_bid" && sole.value === null
      ? "Remove Max CPC"
      : `Change ${KEYWORD_SETTING_TITLES[sole.setting]}`
  return applyChangesLabel(keywordCounts(rows).apply)
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

/** One row per ad group, in the order its keywords first appear. */
export function adGroupParents(rows: readonly KeywordRow[]): ParentRow[] {
  return groupedByParent(rows, keywordAdGroup).map(({ items, key, live }) => {
    const first = items.find((row) => row.adGroupName) ?? items[0]
    return {
      cancelled: live.length === 0,
      context: first?.campaignName ?? null,
      key,
      name: first?.adGroupName ?? `Ad group ${key.split("/").pop() ?? ""}`,
      problems: live.filter((row) => row.problem !== null).length,
      values: { changes: live.length, keywords: new Set(live.map((row) => row.key)).size },
    }
  })
}
