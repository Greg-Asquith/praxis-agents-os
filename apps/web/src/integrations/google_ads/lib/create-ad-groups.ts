// apps/web/src/integrations/google_ads/lib/create-ad-groups.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  matchTypeCounts,
  type KeywordMatchType,
  type PastedKeyword,
} from "@/integrations/ads/lib/keyword-notation"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  adCopyProblems,
  characterCount,
  copyKey,
  parseCopy,
  serializeCopy,
  type AdCopy,
} from "@/integrations/google_ads/lib/create-ads"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { formatCurrencyAmount } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const NAME_LENGTH = 255
const KEYWORD_LENGTH = 80
const KEYWORD_WORDS = 10
const MAX_KEYWORDS = 1_000
const MAX_NEGATIVES = 500
export const MAX_ADS = 3
const MAX_OBJECTS = 2_500
const MONEY_PATTERN = /^\d+(?:\.\d{1,6})?$/
const URL_PATTERN = /^https?:\/\/\S+$/i
const UNAVAILABLE =
  "Google Ads couldn't check these ad groups. Check again, or decline and ask the agent to prepare them again."

export type DraftKeyword = PastedKeyword & { cpcBid: string; finalUrl: string }

export type DraftAdGroup = {
  ads: AdCopy[]
  cpcBid: string
  keywords: DraftKeyword[]
  name: string
  negatives: PastedKeyword[]
  targetCpa: string
  // A percentage, as the operator reads it; the tool takes a ratio.
  targetRoas: string
}

export type CampaignTarget = {
  key: string
  label: string
  // The reference as received, so an edit keeps every field.
  reference: Record<string, unknown>
}

type CampaignCheck = {
  acceptsCpcBid: boolean
  acceptsTargetCpa: boolean
  acceptsTargetRoas: boolean
  key: string
  name: string
  problem: string | null
  strategyName: string | null
}

type ItemProblem = {
  adCopy: string | null
  adGroup: string
  kind: string
  matchType: string | null
  message: string
  text: string | null
}

type AdGroupChecks =
  | { unavailable: true }
  | {
      unavailable: false
      campaign: CampaignCheck
      existingNames: Set<string>
      itemProblems: ItemProblem[]
      requestProblems: string[]
    }

export type CreateAdGroupsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  adGroups: DraftAdGroup[]
  campaign: CampaignTarget
  checks: AdGroupChecks
  status: "PAUSED" | "ENABLED"
}

export type AdGroupRow = {
  adGroup: DraftAdGroup
  // The ad group's position in the edited request, from zero.
  index: number
  problems: string[]
}

function text(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function parseMatchType(value: unknown): KeywordMatchType | null {
  return value === "EXACT" || value === "PHRASE" || value === "BROAD" ? value : null
}

export function parseCampaign(value: unknown): CampaignTarget | null {
  if (!isRecord(value)) return null
  const customerId = googleAdsId(value["customer_id"])
  const campaignId = googleAdsId(value["campaign_id"])
  if (customerId === null || campaignId === null) return null
  return {
    key: `customers/${customerId}/campaigns/${campaignId}`,
    label: text(value["label"]).trim() || `Campaign ${campaignId}`,
    reference: value,
  }
}

function parseKeyword(value: unknown): DraftKeyword | null {
  if (!isRecord(value)) return null
  const matchType = parseMatchType(value["match_type"])
  if (matchType === null || typeof value["text"] !== "string") return null
  return {
    cpcBid: text(value["cpc_bid"]),
    finalUrl: text(value["final_url"]),
    matchType,
    text: value["text"],
  }
}

function roasPercent(value: unknown): string {
  if (typeof value === "string") return value
  if (typeof value !== "number") return ""
  // Rounds away floating point noise, so 3.5 reads as 350 and not 350.00000000000006.
  return String(Math.round(value * 1_000_000) / 10_000)
}

function parseEach<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) return null
  const items: T[] = []
  for (const item of value) {
    const parsed = parse(item)
    if (parsed === null) return null
    items.push(parsed)
  }
  return items
}

function parseAdGroup(value: unknown): DraftAdGroup | null {
  if (!isRecord(value) || typeof value["name"] !== "string") return null
  const keywords = parseEach(value["keywords"], parseKeyword)
  const negatives = parseEach(value["negative_keywords"], parseKeyword)
  const ads = parseEach(value["ads"], parseCopy)
  if (keywords === null || negatives === null || ads === null) return null
  return {
    ads,
    cpcBid: text(value["cpc_bid"]),
    keywords,
    name: value["name"],
    negatives: negatives.map(({ matchType, text: keyword }) => ({ matchType, text: keyword })),
    targetCpa: text(value["target_cpa"]),
    targetRoas: roasPercent(value["target_roas"]),
  }
}

/** Reads the cancelled ad groups the card keeps across a check, in the tool's own shape. */
export function parseCancelledAdGroups(value: unknown): DraftAdGroup[] {
  return parseEach(value, parseAdGroup) ?? []
}

function parseItemProblem(value: unknown): ItemProblem[] {
  if (!isRecord(value) || typeof value["message"] !== "string") return []
  const copy = parseCopy(value["ad"])
  return [
    {
      adCopy: copy ? copyKey(copy) : null,
      adGroup: text(value["ad_group"]),
      kind: text(value["kind"]),
      matchType: text(value["match_type"]) || null,
      message: value["message"],
      text: text(value["text"]) || null,
    },
  ]
}

function parseChecks(value: unknown): AdGroupChecks {
  if (!isRecord(value) || value["unavailable"] !== false || !isRecord(value["campaign"]))
    return { unavailable: true }
  const campaign = value["campaign"]
  const strings = (item: unknown) =>
    Array.isArray(item) ? item.filter((entry): entry is string => typeof entry === "string") : []
  return {
    unavailable: false,
    campaign: {
      acceptsCpcBid: campaign["accepts_cpc_bid"] === true,
      acceptsTargetCpa: campaign["accepts_target_cpa"] === true,
      acceptsTargetRoas: campaign["accepts_target_roas"] === true,
      key: text(campaign["key"]),
      name: text(campaign["name"]),
      problem: text(campaign["problem"]) || null,
      strategyName: text(campaign["strategy_name"]) || null,
    },
    existingNames: new Set(strings(value["existing_names"]).map(foldName)),
    itemProblems: (Array.isArray(value["problems"]) ? value["problems"] : []).flatMap(
      parseItemProblem
    ),
    requestProblems: strings(value["request_problems"]),
  }
}

/** Reads the request with the trusted `_accounts` and `_checks`; null when malformed. */
export function parseCreateAdGroupsArgs(value: unknown): CreateAdGroupsArgs | null {
  if (!isRecord(value)) return null
  const campaign = parseCampaign(value["campaign"])
  const adGroups = parseEach(value["ad_groups"], parseAdGroup)
  const status = value["status"] ?? "PAUSED"
  if (campaign === null || adGroups === null) return null
  if (status !== "PAUSED" && status !== "ENABLED") return null
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    adGroups,
    campaign,
    checks: parseChecks(value["_checks"]),
    status,
  }
}

function foldName(name: string): string {
  return name.trim().split(/\s+/).join(" ").toLowerCase()
}

/** The campaign's checks, unless the operator has since chosen a different campaign. */
export function campaignCheck(args: CreateAdGroupsArgs): CampaignCheck | null {
  if (args.checks.unavailable || args.checks.campaign.key !== args.campaign.key) return null
  return args.checks.campaign
}

function nameProblems(name: string, others: readonly DraftAdGroup[], args: CreateAdGroupsArgs) {
  const problems: string[] = []
  const folded = foldName(name)
  if (!folded) problems.push("Give this ad group a name.")
  if (characterCount(name.trim()) > NAME_LENGTH)
    problems.push(`The name is over ${String(NAME_LENGTH)} characters.`)
  if (folded && others.filter((other) => foldName(other.name) === folded).length > 1)
    problems.push("Another new ad group has this name.")
  const check = campaignCheck(args)
  if (check && !args.checks.unavailable && args.checks.existingNames.has(folded))
    problems.push(`${check.name} already has an ad group with this name.`)
  return problems
}

function money(amount: string, args: CreateAdGroupsArgs): string {
  const currency = [...args.accounts.values()][0]?.currencyCode
  return currency ? formatCurrencyAmount(amount, currency) : amount
}

function bidProblems(group: DraftAdGroup, args: CreateAdGroupsArgs): string[] {
  const problems: string[] = []
  const check = campaignCheck(args)
  const strategy = check?.strategyName ?? "its own bidding"
  const cpc = group.cpcBid.trim()
  const cpa = group.targetCpa.trim()
  const roas = group.targetRoas.trim()
  if (cpc && !validMoney(cpc)) problems.push("Enter the click bid as an amount above zero.")
  else if (cpc && check && !check.acceptsCpcBid)
    problems.push(
      `Has a ${money(cpc, args)} click bid, but the campaign uses ${strategy}. Remove the bid to continue.`
    )
  if (group.keywords.some((keyword) => keyword.cpcBid.trim()) && check && !check.acceptsCpcBid)
    problems.push(
      `Has keyword click bids, but the campaign uses ${strategy}. Remove them to continue.`
    )
  if (cpa && !validMoney(cpa)) problems.push("Enter the target CPA as an amount above zero.")
  else if (cpa && check && !check.acceptsTargetCpa)
    problems.push(`Has a target CPA, but ${strategy} doesn't use one here. Remove it to continue.`)
  if (roas && !validRoas(roas)) problems.push("Enter the target ROAS as a percentage, such as 350.")
  else if (roas && check && !check.acceptsTargetRoas)
    problems.push(`Has a target ROAS, but ${strategy} doesn't use one here. Remove it to continue.`)
  return problems
}

function validMoney(value: string): boolean {
  return MONEY_PATTERN.test(value) && Number(value) > 0
}

function validRoas(value: string): boolean {
  const percent = Number(value)
  return Number.isFinite(percent) && percent >= 1 && percent <= 100_000
}

function keywordKey(keyword: PastedKeyword): string {
  return `${keyword.text.toLowerCase()}|${keyword.matchType}`
}

function listProblems(noun: string, keywords: readonly PastedKeyword[], limit: number): string[] {
  const problems: string[] = []
  if (keywords.length > limit)
    problems.push(`An ad group can have at most ${String(limit)} ${noun}s.`)
  const over = keywords.filter((keyword) => {
    const words = keyword.text.split(/\s+/).length
    return characterCount(keyword.text) > KEYWORD_LENGTH || words > KEYWORD_WORDS
  })
  if (over[0])
    problems.push(
      `${approvalCountLine(over.length, noun)} over ${String(KEYWORD_LENGTH)} characters or ${String(KEYWORD_WORDS)} words, such as "${over[0].text}".`
    )
  const marked = keywords.find((keyword) => /[[\]"]/.test(keyword.text))
  if (marked) problems.push(`Check the brackets or quotes on: ${marked.text}`)
  if (new Set(keywords.map(keywordKey)).size !== keywords.length)
    problems.push(`List each ${noun} and match type once.`)
  return problems
}

function keywordUrlProblems(group: DraftAdGroup): string[] {
  const bad = group.keywords.find(
    (keyword) => keyword.finalUrl.trim() && !URL_PATTERN.test(keyword.finalUrl.trim())
  )
  const badBid = group.keywords.find(
    (keyword) => keyword.cpcBid.trim() && !validMoney(keyword.cpcBid.trim())
  )
  return [
    ...(bad ? [`Enter a final URL starting with http:// or https:// for: ${bad.text}`] : []),
    ...(badBid ? [`Enter the click bid as an amount above zero for: ${badBid.text}`] : []),
  ]
}

function adProblems(group: DraftAdGroup): string[] {
  const problems =
    group.ads.length > MAX_ADS ? [`An ad group can have at most ${String(MAX_ADS)} ads.`] : []
  group.ads.forEach((ad, index) => {
    for (const problem of adCopyProblems(ad)) problems.push(`Ad ${String(index + 1)}: ${problem}`)
  })
  return problems
}

/** Google's rejections for this ad group, while the item it rejected is still in it. */
function googleProblems(group: DraftAdGroup, args: CreateAdGroupsArgs): string[] {
  if (args.checks.unavailable || campaignCheck(args) === null) return []
  const name = group.name.trim()
  return args.checks.itemProblems.flatMap((problem) => {
    if (problem.adGroup !== name) return []
    const matches = (keyword: PastedKeyword) =>
      keyword.text === problem.text && keyword.matchType === problem.matchType
    if (problem.kind === "keyword") {
      return group.keywords.some(matches) ? [`${String(problem.text)}: ${problem.message}`] : []
    }
    if (problem.kind === "negative_keyword") {
      return group.negatives.some(matches) ? [`${String(problem.text)}: ${problem.message}`] : []
    }
    if (problem.kind === "ad") {
      const position = group.ads.findIndex((ad) => copyKey(ad) === problem.adCopy)
      return position >= 0 ? [`Ad ${String(position + 1)}: ${problem.message}`] : []
    }
    return [problem.message]
  })
}

/** What the card can find without asking Google again, so these block a check. */
function cardProblems(group: DraftAdGroup, args: CreateAdGroupsArgs): string[] {
  return [
    ...nameProblems(group.name, args.adGroups, args),
    ...bidProblems(group, args),
    ...listProblems("keyword", group.keywords, MAX_KEYWORDS),
    ...listProblems("negative keyword", group.negatives, MAX_NEGATIVES),
    ...keywordUrlProblems(group),
    ...adProblems(group),
  ]
}

export function adGroupRows(args: CreateAdGroupsArgs): AdGroupRow[] {
  return args.adGroups.map((adGroup, index) => ({
    adGroup,
    index,
    problems: args.checks.unavailable
      ? [UNAVAILABLE]
      : [...cardProblems(adGroup, args), ...googleProblems(adGroup, args)],
  }))
}

function objectCount(adGroups: readonly DraftAdGroup[]): number {
  return adGroups.reduce(
    (total, group) => total + 1 + group.keywords.length + group.negatives.length + group.ads.length,
    0
  )
}

/** Problems with the whole request, not one ad group: the campaign, the size, and Google's. */
export function requestProblems(args: CreateAdGroupsArgs): string[] {
  const check = campaignCheck(args)
  return [
    ...(check?.problem ? [check.problem] : []),
    ...(objectCount(args.adGroups) > MAX_OBJECTS
      ? [`One request can create at most ${MAX_OBJECTS.toLocaleString("en-GB")} objects.`]
      : []),
    ...(check && !args.checks.unavailable ? args.checks.requestProblems : []),
  ]
}

export type CreateAdGroupsCounts = {
  adGroups: number
  ads: number
  keywords: number
  negatives: number
  problems: number
}

export function createAdGroupsCounts(rows: readonly AdGroupRow[]): CreateAdGroupsCounts {
  const sum = (pick: (group: DraftAdGroup) => number) =>
    rows.reduce((total, row) => total + pick(row.adGroup), 0)
  return {
    adGroups: rows.length,
    ads: sum((group) => group.ads.length),
    keywords: sum((group) => group.keywords.length),
    negatives: sum((group) => group.negatives.length),
    problems: rows.filter((row) => row.problems.length > 0).length,
  }
}

export function keywordMixLine(rows: readonly AdGroupRow[]): string {
  const counts = matchTypeCounts(rows.flatMap((row) => row.adGroup.keywords))
  return [
    counts.phrase ? `${String(counts.phrase)} phrase` : null,
    counts.exact ? `${String(counts.exact)} exact` : null,
    counts.broad ? `${String(counts.broad)} broad` : null,
  ]
    .filter(Boolean)
    .join(", ")
}

function requestKey(args: CreateAdGroupsArgs): string {
  return JSON.stringify([args.campaign.reference, serializeAdGroups(args.adGroups)])
}

/** True when Google hasn't answered for this request. Status doesn't change its answer. */
export function adGroupsNeedCheck(args: CreateAdGroupsArgs, checked: CreateAdGroupsArgs): boolean {
  return args.checks.unavailable || requestKey(args) !== requestKey(checked)
}

export function canCheckAdGroups(args: CreateAdGroupsArgs): boolean {
  return (
    args.adGroups.length > 0 &&
    objectCount(args.adGroups) <= MAX_OBJECTS &&
    args.adGroups.every((group) => !cardProblems(group, args).length)
  )
}

/** Why the request can't be approved yet, or null. */
export function createAdGroupsBlock(
  args: CreateAdGroupsArgs | null,
  checked: CreateAdGroupsArgs
): string | null {
  if (args === null) return null
  const counts = createAdGroupsCounts(adGroupRows(args))
  if (counts.adGroups === 0)
    return "Every ad group is cancelled. Decline this request, or restore one."
  const [problem] = requestProblems(args)
  if (problem) return problem
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "ad group")} to continue.`
  return adGroupsNeedCheck(args, checked) ? "Check the changes before approving." : null
}

export function createAdGroupsPrompt(args: CreateAdGroupsArgs): string {
  const counts = createAdGroupsCounts(adGroupRows(args))
  if (counts.adGroups === 0) return "Nothing is left to create."
  const number = (count: number, noun: string) =>
    `${count.toLocaleString("en-GB")} ${noun}${count === 1 ? "" : "s"}`
  return `Create ${number(counts.adGroups, "ad group")} with ${number(counts.keywords, "keyword")} and ${number(counts.ads, "ad")} in ${args.campaign.label}.`
}

export function createAdGroupsApproveLabel(args: CreateAdGroupsArgs): string {
  const count = args.adGroups.length
  return count === 0
    ? "Create Ad Groups"
    : `Create ${String(count)} ${count === 1 ? "Ad Group" : "Ad Groups"}`
}

export function createAdGroupsDetails(args: CreateAdGroupsArgs | null): FanOutDetail[] {
  if (args === null) return []
  const counts = createAdGroupsCounts(adGroupRows(args))
  return [
    { label: "Campaign", value: args.campaign.label },
    { label: "Ad Groups", value: String(counts.adGroups) },
    { label: "Keywords", value: String(counts.keywords) },
    { label: "Ads", value: String(counts.ads) },
    { label: "Status", value: args.status === "ENABLED" ? "Active" : "Paused" },
  ]
}

function serializeRoas(percent: string): number | string | null {
  const trimmed = percent.trim()
  if (!trimmed) return null
  // Left as typed when invalid, so the card can show it and approval stays blocked.
  return validRoas(trimmed) ? Number(trimmed) / 100 : trimmed
}

/** The `ad_groups` value for the given drafts; blank optional fields are null. */
export function serializeAdGroups(adGroups: readonly DraftAdGroup[]): Record<string, unknown>[] {
  return adGroups.map((group) => ({
    name: group.name,
    cpc_bid: group.cpcBid.trim() || null,
    target_cpa: group.targetCpa.trim() || null,
    target_roas: serializeRoas(group.targetRoas),
    keywords: group.keywords.map((keyword) => ({
      text: keyword.text,
      match_type: keyword.matchType,
      cpc_bid: keyword.cpcBid.trim() || null,
      final_url: keyword.finalUrl.trim() || null,
    })),
    negative_keywords: group.negatives.map((keyword) => ({
      text: keyword.text,
      match_type: keyword.matchType,
    })),
    ads: group.ads.map(serializeCopy),
  }))
}

/** Pasted keywords, keeping the bid and URL of any that were already in the list. */
export function mergePastedKeywords(
  pasted: readonly PastedKeyword[],
  current: readonly DraftKeyword[]
): DraftKeyword[] {
  const known = new Map(current.map((keyword) => [keywordKey(keyword), keyword]))
  return pasted.map((keyword) => ({
    cpcBid: known.get(keywordKey(keyword))?.cpcBid ?? "",
    finalUrl: known.get(keywordKey(keyword))?.finalUrl ?? "",
    ...keyword,
  }))
}

/** A blank ad, starting from the same links as the ad group's first ad. */
export function blankAd(first: AdCopy | undefined): AdCopy {
  const blank = { pin: null, text: "" }
  return {
    descriptions: [blank, blank],
    finalUrl: first?.finalUrl ?? "",
    headlines: [blank, blank, blank],
    mobileFinalUrl: first?.mobileFinalUrl ?? "",
    path1: first?.path1 ?? "",
    path2: first?.path2 ?? "",
  }
}
