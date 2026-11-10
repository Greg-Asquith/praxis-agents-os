// apps/web/src/integrations/google_ads/lib/create-keywords.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import {
  parseAdGroupReference,
  type AdGroupReference,
} from "@/integrations/google_ads/lib/ad-groups"
import { canonicalMoney } from "@/integrations/google_ads/lib/campaign-bidding"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import type { DraftKeyword } from "@/integrations/google_ads/lib/create-ad-groups"
import { formatCurrencyAmount } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const MONEY_PATTERN = /^\d+(?:\.\d{1,6})?$/
const URL_PATTERN = /^https?:\/\/\S+$/i
const MATCH_TYPES = new Set<string>(["EXACT", "PHRASE", "BROAD"])
const UNAVAILABLE =
  "Google Ads couldn't check this keyword. Check again, or decline and ask the agent to prepare it again."

type KeywordStatus = "ENABLED" | "PAUSED"

export type KeywordEntry = {
  adGroup: AdGroupReference
  // The ad group's resource name, which names it in the checks.
  key: string
  keywords: DraftKeyword[]
  // The reference as the agent sent it, so an edited request sends it back unchanged.
  raw: Record<string, unknown>
}

type AdGroupFacts = {
  campaignName: string | null
  defaultBid: string | null
  name: string
  problem: string | null
  strategyName: string | null
  usesCpcBid: boolean
}

type KeywordCheck = { unavailable: true } | { unavailable: false; problem: string | null }

export type CreateKeywordsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  adGroups: Map<string, AdGroupFacts>
  checks: Map<string, KeywordCheck>
  entries: KeywordEntry[]
  status: KeywordStatus
}

export type KeywordAdGroupRow = {
  bid: string
  campaignName: string
  entry: KeywordEntry
  name: string
  problems: number
}

function text(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function parseKeyword(value: unknown): DraftKeyword | null {
  if (!isRecord(value) || typeof value["text"] !== "string") return null
  const matchType = value["match_type"]
  if (typeof matchType !== "string" || !MATCH_TYPES.has(matchType)) return null
  return {
    cpcBid: text(value["cpc_bid"]),
    finalUrl: text(value["final_url"]),
    matchType: matchType as KeywordMatchType,
    text: value["text"],
  }
}

function parseEntry(value: unknown): KeywordEntry | null {
  if (!isRecord(value) || !isRecord(value["ad_group"]) || !Array.isArray(value["keywords"]))
    return null
  const adGroup = parseAdGroupReference(value["ad_group"])
  const keywords = value["keywords"].map(parseKeyword)
  if (!adGroup || keywords.some((keyword) => keyword === null)) return null
  return {
    adGroup,
    key: `customers/${adGroup.customerId}/adGroups/${adGroup.adGroupId}`,
    keywords: keywords as DraftKeyword[],
    raw: value["ad_group"],
  }
}

function parseFacts(value: unknown): AdGroupFacts | null {
  if (!isRecord(value) || typeof value["name"] !== "string") return null
  return {
    campaignName: text(value["campaign_name"]) || null,
    defaultBid: typeof value["default_bid"] === "string" ? value["default_bid"] : null,
    name: value["name"],
    problem: typeof value["problem"] === "string" ? value["problem"] : null,
    strategyName: typeof value["strategy_name"] === "string" ? value["strategy_name"] : null,
    usesCpcBid: value["uses_cpc_bid"] === true,
  }
}

function parseCheck(value: unknown): KeywordCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  return {
    unavailable: false,
    problem: typeof value["problem"] === "string" ? value["problem"] : null,
  }
}

function recordMap<T>(value: unknown, parse: (item: unknown) => T | null): Map<string, T> {
  if (!isRecord(value)) return new Map()
  return new Map(
    Object.entries(value).flatMap(([key, item]): [string, T][] => {
      const parsed = parse(item)
      return parsed === null ? [] : [[key, parsed]]
    })
  )
}

export function parseCreateKeywordsArgs(value: unknown): CreateKeywordsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["entries"])) return null
  const entries = value["entries"].map(parseEntry)
  if (entries.some((entry) => entry === null)) return null
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    adGroups: recordMap(value["_ad_groups"], parseFacts),
    checks: recordMap(value["_checks"], parseCheck),
    entries: entries as KeywordEntry[],
    status: value["status"] === "ENABLED" ? "ENABLED" : "PAUSED",
  }
}

/** Names a keyword in the checks, as the server writes it. */
function keywordCheckKey(entry: KeywordEntry, keyword: DraftKeyword): string {
  return `${entry.key}/${keyword.matchType}/${keyword.text.toLowerCase()}`
}

export function serializeEntries(entries: readonly KeywordEntry[]): Record<string, unknown>[] {
  return entries.map((entry) => ({
    ad_group: entry.raw,
    keywords: entry.keywords.map((keyword) => ({
      text: keyword.text,
      match_type: keyword.matchType,
      cpc_bid: keyword.cpcBid.trim() || null,
      final_url: keyword.finalUrl.trim() || null,
    })),
  }))
}

/** What stops one keyword: the card's own rules first, then what Google last said. */
export function keywordProblem(
  checked: CreateKeywordsArgs,
  entry: KeywordEntry,
  keyword: DraftKeyword
): string | null {
  const bid = keyword.cpcBid.trim()
  if (bid && (!MONEY_PATTERN.test(bid) || Number(bid) <= 0))
    return `Enter a max CPC above zero for “${keyword.text}”.`
  const url = keyword.finalUrl.trim()
  if (url && !URL_PATTERN.test(url))
    return `Enter a final URL starting with http:// or https:// for “${keyword.text}”.`
  const facts = checked.adGroups.get(entry.key)
  if (facts?.problem) return facts.problem
  const check = checked.checks.get(keywordCheckKey(entry, keyword))
  if (check?.unavailable) return UNAVAILABLE
  return check?.problem ?? null
}

export function keywordAdGroupRows(
  args: CreateKeywordsArgs,
  checked: CreateKeywordsArgs
): KeywordAdGroupRow[] {
  return args.entries.map((entry) => {
    const facts = checked.adGroups.get(entry.key)
    const currency = args.accounts.get(entry.adGroup.customerId)?.currencyCode
    return {
      bid: bidText(facts, currency),
      campaignName: facts?.campaignName ?? entry.adGroup.campaignLabel ?? "",
      entry,
      name: facts?.name ?? entry.adGroup.label,
      problems: entry.keywords.filter((keyword) => keywordProblem(checked, entry, keyword)).length,
    }
  })
}

function bidText(facts: AdGroupFacts | undefined, currency: string | undefined): string {
  if (!facts) return "—"
  if (!facts.usesCpcBid) return facts.strategyName ?? "Automated bidding"
  if (!facts.defaultBid) return "No default bid"
  return currency
    ? formatCurrencyAmount(canonicalMoney(facts.defaultBid), currency)
    : facts.defaultBid
}

export type KeywordCounts = { adGroups: number; keywords: number; problems: number; ready: number }

export function keywordCounts(
  args: CreateKeywordsArgs,
  checked: CreateKeywordsArgs
): KeywordCounts {
  const rows = keywordAdGroupRows(args, checked)
  const keywords = rows.reduce((total, row) => total + row.entry.keywords.length, 0)
  const problems = rows.reduce((total, row) => total + row.problems, 0)
  return { adGroups: rows.length, keywords, problems, ready: keywords - problems }
}

function signature(args: CreateKeywordsArgs): string {
  return JSON.stringify(serializeEntries(args.entries).map((entry) => entry["keywords"]))
}

export function keywordsNeedCheck(args: CreateKeywordsArgs, checked: CreateKeywordsArgs): boolean {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    args.entries.map((entry) => entry.key).join() !==
      checked.entries.map((entry) => entry.key).join() ||
    signature(args) !== signature(checked)
  )
}

/** Why the request can't be approved yet, or null. */
export function createKeywordsBlock(
  args: CreateKeywordsArgs | null,
  checked: CreateKeywordsArgs
): string | null {
  if (args === null) return null
  const counts = keywordCounts(args, checked)
  if (counts.keywords === 0) return "Every keyword is cancelled. Decline this request, or undo one."
  if (keywordsNeedCheck(args, checked))
    return "Click Check Changes so Google can check your edits, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "keyword")} to continue.`
  return null
}

function where(args: CreateKeywordsArgs, rows: readonly KeywordAdGroupRow[]): string {
  const campaigns = new Set(rows.map((row) => row.campaignName).filter(Boolean))
  const [campaign] = campaigns
  if (rows.length === 1 && rows[0]) return rows[0].name
  const groups = approvalCountLine(rows.length, "ad group")
  if (campaigns.size === 1 && campaign) return `${groups} in ${campaign}`
  const accounts = new Set(args.entries.map((entry) => entry.adGroup.customerId))
  return accounts.size > 1 ? `${groups} in ${String(accounts.size)} accounts` : groups
}

export function createKeywordsPrompt(args: CreateKeywordsArgs): string {
  const rows = keywordAdGroupRows(args, args)
  const counts = keywordCounts(args, args)
  if (counts.keywords === 0) return "Nothing is left to add."
  return `Add ${approvalCountLine(counts.keywords, "keyword")} to ${where(args, rows)}.`
}

export function createKeywordsApproveLabel(args: CreateKeywordsArgs): string {
  const { ready } = keywordCounts(args, args)
  if (ready === 0) return "Add Keywords"
  return `Add ${ready.toLocaleString("en-GB")} ${ready === 1 ? "Keyword" : "Keywords"}`
}

export function createKeywordsDetails(args: CreateKeywordsArgs | null): FanOutDetail[] {
  if (!args) return []
  const keywords = args.entries.reduce((total, entry) => total + entry.keywords.length, 0)
  return [
    { label: "Ad groups", value: String(args.entries.length) },
    { label: "Keywords", value: String(keywords) },
  ]
}
