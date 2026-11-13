// apps/web/src/integrations/google_ads/lib/create-campaign.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { PastedKeyword } from "@/integrations/ads/lib/keyword-notation"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  adGroupCardProblems,
  createAdGroupsCounts,
  listProblems,
  newAdGroupRows,
  objectCount,
  parseAdGroup,
  parseEach,
  parseItemProblems,
  roasPercent,
  serializeAdGroups,
  serializeRoas,
  text,
  validMoney,
  validRoas,
  type AdGroupContext,
  type AdGroupRow,
  type BidRules,
  type DraftAdGroup,
  type ItemProblem,
} from "@/integrations/google_ads/lib/create-ad-groups"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import {
  googleAssetProblems,
  newAssetProblems,
  parseNewAsset,
  serializeNewAssets,
  type DraftAsset,
} from "@/integrations/google_ads/lib/new-assets"
import {
  assetGroupRows,
  assetGroupsObjectCount,
  parseAssetGroup,
  parsePerformanceMax,
  parsePerformanceMaxChecks,
  performanceMaxProblems,
  serializeAssetGroups,
  serializePerformanceMax,
  type AssetGroupRow,
  type DraftAssetGroup,
  type DraftPerformanceMax,
  type PerformanceMaxChecks,
} from "@/integrations/google_ads/lib/performance-max"
import { formatCurrencyAmount } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const NAME_LENGTH = 255
const MAX_LOCATIONS = 1_000
const MAX_NEGATIVES = 1_000
const MAX_OBJECTS = 2_500
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
// Google's monthly charging limit is 30.4 times the average daily budget.
const DAYS_PER_MONTH = 30.4
const UNAVAILABLE =
  "Google Ads couldn't check this campaign. Check again, or decline and ask the agent to prepare it again."

export const STRATEGIES = [
  "MAXIMIZE_CONVERSIONS",
  "MAXIMIZE_CONVERSION_VALUE",
  "MAXIMIZE_CLICKS",
  "MANUAL_CPC",
  "TARGET_IMPRESSION_SHARE",
] as const
export type Strategy = (typeof STRATEGIES)[number]
// Performance Max bids only for conversions or their value.
export const PERFORMANCE_MAX_STRATEGIES = [
  "MAXIMIZE_CONVERSIONS",
  "MAXIMIZE_CONVERSION_VALUE",
] as const satisfies readonly Strategy[]

type CampaignType = "search" | "performance_max"

export const STRATEGY_LABELS: Record<Strategy, string> = {
  MANUAL_CPC: "Manual CPC",
  MAXIMIZE_CLICKS: "Maximise Clicks",
  MAXIMIZE_CONVERSIONS: "Maximise Conversions",
  MAXIMIZE_CONVERSION_VALUE: "Maximise Conversion Value",
  TARGET_IMPRESSION_SHARE: "Target Impression Share",
}

export const PAGE_LOCATIONS = ["ANYWHERE_ON_PAGE", "TOP_OF_PAGE", "ABSOLUTE_TOP_OF_PAGE"] as const
export type PageLocation = (typeof PAGE_LOCATIONS)[number]

export const PAGE_LOCATION_LABELS: Record<PageLocation, string> = {
  ABSOLUTE_TOP_OF_PAGE: "Very top of the page",
  ANYWHERE_ON_PAGE: "Anywhere on the page",
  TOP_OF_PAGE: "Top of the page",
}

/** Every strategy's fields, so switching strategy and back keeps what was entered. */
export type DraftBidding = {
  maxCpc: string
  pageLocation: PageLocation
  sharePercent: string
  strategy: Strategy
  targetCpa: string
  // A percentage, as the operator reads it; the tool takes a ratio.
  targetRoas: string
}

type DraftBudget =
  | { kind: "new"; dailyAmount: string }
  | {
      kind: "shared"
      // The daily amount, when the reference carries it.
      dailyAmount: string | null
      label: string
      // False for a budget that belongs to one campaign, which Google won't share.
      shared: boolean | null
      // The reference as received, so an edit keeps every field.
      reference: Record<string, unknown>
    }

export type DraftLocation = { key: string; name: string }

export type LocationSetting = "PRESENCE" | "PRESENCE_OR_INTEREST"

export type DraftCampaign = {
  // New sitelinks and callouts for every ad group.
  assets: DraftAsset[]
  // Set for a Performance Max campaign: its brand, goals, feed, and languages.
  performanceMax: DraftPerformanceMax | null
  type: CampaignType
  bidding: DraftBidding
  budget: DraftBudget
  displayExpansion: boolean
  endDate: string
  excludedLocations: DraftLocation[]
  locationSetting: LocationSetting
  locations: DraftLocation[]
  name: string
  negatives: PastedKeyword[]
  political: boolean
  searchPartners: boolean
  startDate: string
}

type CampaignItemProblem = {
  key: string | null
  kind: string
  matchType: string | null
  message: string
  text: string | null
}

type CampaignChecks =
  | { unavailable: true }
  | {
      unavailable: false
      campaignProblems: CampaignItemProblem[]
      // False when Google doesn't need the EU political answer for the checked locations.
      euPoliticalQuestion: boolean
      itemProblems: ItemProblem[]
      locationNames: Map<string, string>
      // Set for a Performance Max campaign.
      performanceMax: PerformanceMaxChecks | null
      requestProblems: string[]
      // The date in the account time zone when Google last checked.
      today: string
      unknownLocations: Set<string>
    }

export type CreateCampaignArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  adGroups: DraftAdGroup[]
  assetGroups: DraftAssetGroup[]
  campaign: DraftCampaign
  checks: CampaignChecks
  status: "PAUSED" | "ENABLED"
}

function isStrategy(value: unknown): value is Strategy {
  return typeof value === "string" && value in STRATEGY_LABELS
}

function isPageLocation(value: unknown): value is PageLocation {
  return typeof value === "string" && value in PAGE_LOCATION_LABELS
}

function microsAmount(value: unknown): string | null {
  const micros = typeof value === "number" ? String(value) : value
  if (typeof micros !== "string" || !/^\d+$/.test(micros)) return null
  return String(Number(micros) / 1_000_000)
}

function parseBudget(value: unknown): DraftBudget | null {
  if (!isRecord(value)) return null
  if (value["kind"] === "shared") {
    const reference = value["budget"]
    if (!isRecord(reference) || typeof reference["budget_id"] !== "string") return null
    return {
      dailyAmount: microsAmount(reference["amount_micros"]),
      kind: "shared",
      label: text(reference["label"]).trim() || `Budget ${reference["budget_id"]}`,
      reference,
      shared:
        typeof reference["explicitly_shared"] === "boolean" ? reference["explicitly_shared"] : null,
    }
  }
  if (value["kind"] !== undefined && value["kind"] !== "new") return null
  return { dailyAmount: text(value["daily_amount"]), kind: "new" }
}

function parseBidding(value: unknown): DraftBidding | null {
  if (!isRecord(value) || !isStrategy(value["strategy"])) return null
  const share = value["share_percent"]
  return {
    maxCpc: text(value["max_cpc"]),
    pageLocation: isPageLocation(value["location"]) ? value["location"] : "TOP_OF_PAGE",
    sharePercent: typeof share === "number" ? String(share) : text(share),
    strategy: value["strategy"],
    targetCpa: text(value["target_cpa"]),
    targetRoas: roasPercent(value["target_roas"]),
  }
}

function parseLocation(value: unknown): DraftLocation | null {
  if (!isRecord(value) || typeof value["key"] !== "string" || !/^\d+$/.test(value["key"]))
    return null
  return { key: value["key"], name: text(value["name"]) }
}

function parseNegative(value: unknown): PastedKeyword | null {
  if (!isRecord(value) || typeof value["text"] !== "string") return null
  const matchType = value["match_type"]
  if (matchType !== "EXACT" && matchType !== "PHRASE" && matchType !== "BROAD") return null
  return { matchType, text: value["text"] }
}

function parseDraftCampaign(value: unknown): DraftCampaign | null {
  if (!isRecord(value) || typeof value["name"] !== "string") return null
  const type = value["type"] ?? "search"
  if (type !== "search" && type !== "performance_max") return null
  const performanceMax = type === "performance_max" ? parsePerformanceMax(value) : null
  if (type === "performance_max" && performanceMax === null) return null
  const budget = parseBudget(value["budget"])
  const bidding = parseBidding(value["bidding"])
  const locations = parseEach(value["locations"], parseLocation)
  const excluded = parseEach(value["excluded_locations"], parseLocation)
  const negatives = parseEach(value["negative_keywords"], parseNegative)
  const assets = parseEach(value["assets"], parseNewAsset)
  const setting = value["location_setting"] ?? "PRESENCE"
  if (budget === null || bidding === null || locations === null || excluded === null) return null
  // Performance Max can't share a budget.
  if (type === "performance_max" && budget.kind === "shared") return null
  if (
    assets === null ||
    negatives === null ||
    (setting !== "PRESENCE" && setting !== "PRESENCE_OR_INTEREST")
  )
    return null
  return {
    assets,
    bidding,
    budget,
    displayExpansion: value["display_expansion"] === true,
    endDate: text(value["end_date"]),
    excludedLocations: excluded,
    locationSetting: setting,
    locations,
    name: value["name"],
    negatives,
    performanceMax,
    political: value["contains_eu_political_advertising"] === true,
    searchPartners: value["search_partners"] === true,
    startDate: text(value["start_date"]),
    type,
  }
}

function parseCampaignItemProblem(value: unknown): CampaignItemProblem[] {
  if (!isRecord(value) || typeof value["message"] !== "string") return []
  return [
    {
      key: text(value["key"]) || null,
      kind: text(value["kind"]),
      matchType: text(value["match_type"]) || null,
      message: value["message"],
      text: text(value["text"]) || null,
    },
  ]
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : []
}

function parseChecks(value: unknown): CampaignChecks {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const names = isRecord(value["locations"]) ? value["locations"] : {}
  const list = (key: string) => (Array.isArray(value[key]) ? (value[key] as unknown[]) : [])
  return {
    unavailable: false,
    campaignProblems: list("campaign_problems").flatMap(parseCampaignItemProblem),
    euPoliticalQuestion: value["eu_political_question"] !== false,
    itemProblems: parseItemProblems(value["problems"]),
    locationNames: new Map(
      Object.entries(names).flatMap(([key, name]) =>
        typeof name === "string" ? [[key, name] as const] : []
      )
    ),
    performanceMax: Array.isArray(value["account_goals"]) ? parsePerformanceMaxChecks(value) : null,
    requestProblems: strings(value["request_problems"]),
    today: text(value["today"]),
    unknownLocations: new Set(strings(value["unknown_locations"])),
  }
}

/** Reads the request with the trusted `_accounts` and `_checks`; null when malformed. */
export function parseCreateCampaignArgs(value: unknown): CreateCampaignArgs | null {
  if (!isRecord(value)) return null
  const campaign = parseDraftCampaign(value["campaign"])
  const adGroups = parseEach(value["ad_groups"], parseAdGroup)
  const assetGroups = parseEach(value["asset_groups"], parseAssetGroup)
  const status = value["status"] ?? "PAUSED"
  if (campaign === null || adGroups === null || assetGroups === null) return null
  if (status !== "PAUSED" && status !== "ENABLED") return null
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    adGroups,
    assetGroups,
    campaign,
    checks: parseChecks(value["_checks"]),
    status,
  }
}

export function performanceMaxChecks(args: CreateCampaignArgs): PerformanceMaxChecks | null {
  return args.checks.unavailable ? null : args.checks.performanceMax
}

export function campaignAssetGroupRows(args: CreateCampaignArgs): AssetGroupRow[] {
  return assetGroupRows(args.assetGroups, {
    checks: performanceMaxChecks(args),
    retail: args.campaign.performanceMax?.merchant != null,
  })
}

export function currencyOf(args: CreateCampaignArgs): string | null {
  return [...args.accounts.values()][0]?.currencyCode ?? null
}

/** What the new campaign's bidding lets its ad groups set, by Google's rules. */
export function biddingRules(bidding: DraftBidding): BidRules {
  return {
    acceptsCpcBid: bidding.strategy === "MANUAL_CPC",
    acceptsTargetCpa:
      bidding.strategy === "MAXIMIZE_CONVERSIONS" && bidding.targetCpa.trim() !== "",
    acceptsTargetRoas:
      bidding.strategy === "MAXIMIZE_CONVERSION_VALUE" && bidding.targetRoas.trim() !== "",
    strategyName: STRATEGY_LABELS[bidding.strategy],
  }
}

/** Whether the card asks if the ads are EU political ads. An answer of yes always shows. */
export function asksEuPolitical(args: CreateCampaignArgs): boolean {
  return args.campaign.political || args.checks.unavailable || args.checks.euPoliticalQuestion
}

export function locationName(location: DraftLocation, args: CreateCampaignArgs): string {
  const checked = args.checks.unavailable ? undefined : args.checks.locationNames.get(location.key)
  return checked ?? (location.name || `Location ${location.key}`)
}

function biddingProblems(bidding: DraftBidding): string[] {
  const problems: string[] = []
  const maxCpc = bidding.maxCpc.trim()
  if (bidding.strategy === "TARGET_IMPRESSION_SHARE") {
    const share = Number(bidding.sharePercent)
    if (!Number.isInteger(share) || share < 1 || share > 100)
      problems.push("Enter the share of searches as a whole percentage from 1 to 100.")
    if (!maxCpc) problems.push("Target Impression Share needs a maximum click bid.")
  }
  const usesMaxCpc =
    bidding.strategy === "MAXIMIZE_CLICKS" || bidding.strategy === "TARGET_IMPRESSION_SHARE"
  if (usesMaxCpc && maxCpc && !validMoney(maxCpc))
    problems.push("Enter the maximum click bid as an amount above zero.")
  const cpa = bidding.targetCpa.trim()
  if (bidding.strategy === "MAXIMIZE_CONVERSIONS" && cpa && !validMoney(cpa))
    problems.push("Enter the target CPA as an amount above zero.")
  const roas = bidding.targetRoas.trim()
  if (bidding.strategy === "MAXIMIZE_CONVERSION_VALUE" && roas && !validRoas(roas))
    problems.push("Enter the target ROAS as a percentage, such as 350.")
  return problems
}

function dateProblems(campaign: DraftCampaign, today: string | null): string[] {
  const problems: string[] = []
  const start = campaign.startDate.trim()
  const end = campaign.endDate.trim()
  if (start && !DATE_PATTERN.test(start)) problems.push("Enter the start date as a date.")
  if (end && !DATE_PATTERN.test(end)) problems.push("Enter the end date as a date.")
  // ISO dates compare correctly as text.
  if (today && start && start < today) problems.push("The start date is in the past.")
  if (today && end && end < today) problems.push("The end date is in the past.")
  if (start && end && end < start) problems.push("The end date is before the start date.")
  return problems
}

function locationProblems(args: CreateCampaignArgs): string[] {
  const { campaign } = args
  const problems: string[] = []
  if (campaign.locations.length === 0)
    problems.push("Choose at least one location, so the ads don't show everywhere.")
  if (
    campaign.locations.length > MAX_LOCATIONS ||
    campaign.excludedLocations.length > MAX_LOCATIONS
  )
    problems.push(`Choose at most ${MAX_LOCATIONS.toLocaleString("en-GB")} locations of each kind.`)
  const unknown = args.checks.unavailable ? new Set<string>() : args.checks.unknownLocations
  for (const location of [...campaign.locations, ...campaign.excludedLocations]) {
    if (unknown.has(location.key))
      problems.push(`Google doesn't recognise ${locationName(location, args)}. Remove it.`)
  }
  return problems
}

/** What the card can find in the campaign's own settings without asking Google again. */
function campaignCardProblems(args: CreateCampaignArgs): string[] {
  const { campaign } = args
  const problems: string[] = []
  if (!campaign.name.trim()) problems.push("Give the campaign a name.")
  if (characterCount(campaign.name.trim()) > NAME_LENGTH)
    problems.push(`The campaign name is over ${String(NAME_LENGTH)} characters.`)
  if (campaign.budget.kind === "new" && !validMoney(campaign.budget.dailyAmount.trim()))
    problems.push("Enter the daily budget as an amount above zero.")
  if (campaign.budget.kind === "shared" && campaign.budget.shared === false)
    problems.push(
      `${campaign.budget.label} belongs to one campaign. Choose a shared budget, or give this campaign its own.`
    )
  return [
    ...problems,
    ...biddingProblems(campaign.bidding),
    ...locationProblems(args),
    ...dateProblems(campaign, args.checks.unavailable ? null : args.checks.today),
    ...listProblems("negative keyword", campaign.negatives, MAX_NEGATIVES, "A campaign"),
    ...newAssetProblems(campaign.assets),
    ...(campaign.performanceMax
      ? performanceMaxProblems(
          campaign.performanceMax,
          args.assetGroups,
          performanceMaxChecks(args)
        )
      : []),
  ]
}

/** Google's rejections of the campaign's own objects, while what it rejected is still there. */
function googleCampaignProblems(args: CreateCampaignArgs): string[] {
  if (args.checks.unavailable) return []
  const { campaign } = args
  const own = args.checks.campaignProblems.flatMap((problem) => {
    if (problem.kind === "location" || problem.kind === "excluded_location") {
      const list = problem.kind === "location" ? campaign.locations : campaign.excludedLocations
      const location = list.find((item) => item.key === problem.key)
      return location ? [`${locationName(location, args)}: ${problem.message}`] : []
    }
    if (problem.kind === "negative_keyword") {
      const present = campaign.negatives.some(
        (item) => item.text === problem.text && item.matchType === problem.matchType
      )
      return present ? [`${String(problem.text)}: ${problem.message}`] : []
    }
    if (problem.kind === "asset" || problem.kind === "asset_link")
      return googleAssetProblems(campaign.assets, [
        { key: problem.key ?? "", message: problem.message },
      ])
    if (problem.kind === "language") {
      const language = campaign.performanceMax?.languages.find((item) => item.key === problem.key)
      return language ? [`${language.name || language.key}: ${problem.message}`] : []
    }
    return [problem.message]
  })
  // A new asset is made once for every place that links it, so an ad group's rejection applies here.
  const shared = args.checks.itemProblems
    .filter((problem) => problem.kind === "asset")
    .map((problem) => ({ key: problem.assetKey ?? "", message: problem.message }))
  return [...new Set([...own, ...googleAssetProblems(campaign.assets, shared)])]
}

export function campaignProblems(args: CreateCampaignArgs): string[] {
  return [...campaignCardProblems(args), ...googleCampaignProblems(args)]
}

/** Google's item problems, with the campaign's rejected new assets for the ad groups that link them. */
function adGroupGoogleProblems(checks: CampaignChecks & { unavailable: false }): ItemProblem[] {
  const shared = checks.campaignProblems
    .filter((problem) => problem.kind === "asset")
    .map((problem) => ({
      adCopy: null,
      adGroup: "",
      assetKey: problem.key,
      kind: problem.kind,
      matchType: null,
      message: problem.message,
      text: null,
    }))
  return [...checks.itemProblems, ...shared]
}

function adGroupContext(args: CreateCampaignArgs, withGoogle: boolean): AdGroupContext {
  return {
    currency: currencyOf(args),
    existing: null,
    googleProblems:
      withGoogle && !args.checks.unavailable ? adGroupGoogleProblems(args.checks) : [],
    requireServing: true,
    rules: biddingRules(args.campaign.bidding),
  }
}

export function campaignAdGroupRows(args: CreateCampaignArgs): AdGroupRow[] {
  return newAdGroupRows(args.adGroups, adGroupContext(args, true))
}

function campaignObjectCount(campaign: DraftCampaign): number {
  const performanceMax = campaign.performanceMax
  return (
    (campaign.budget.kind === "new" ? 2 : 1) +
    campaign.locations.length +
    campaign.excludedLocations.length +
    campaign.negatives.length +
    // Each new asset is created and linked.
    2 * campaign.assets.length +
    (performanceMax
      ? performanceMax.languages.length +
        performanceMax.logos.length +
        (performanceMax.businessName.trim() ? 2 : 0)
      : 0)
  )
}

/** Every object the request creates: the campaign's own and its groups'. */
function requestObjectCount(args: CreateCampaignArgs): number {
  return (
    campaignObjectCount(args.campaign) +
    objectCount(args.adGroups) +
    assetGroupsObjectCount(args.assetGroups)
  )
}

/** Problems with the whole request: Google unreachable, the size, and Google's own. */
export function requestProblems(args: CreateCampaignArgs): string[] {
  if (args.checks.unavailable) return [UNAVAILABLE]
  return [
    ...(requestObjectCount(args) > MAX_OBJECTS
      ? [`One request can create at most ${MAX_OBJECTS.toLocaleString("en-GB")} objects.`]
      : []),
    ...args.checks.requestProblems,
  ]
}

function requestKey(args: CreateCampaignArgs): string {
  return JSON.stringify([
    serializeCampaign(args.campaign),
    serializeAdGroups(args.adGroups),
    serializeAssetGroups(args.assetGroups),
  ])
}

/** True when Google hasn't answered for this request. Status doesn't change its answer. */
export function campaignNeedsCheck(args: CreateCampaignArgs, checked: CreateCampaignArgs): boolean {
  return args.checks.unavailable || requestKey(args) !== requestKey(checked)
}

export function canCheckCampaign(args: CreateCampaignArgs): boolean {
  if (args.campaign.type === "performance_max")
    return (
      args.assetGroups.length > 0 &&
      requestObjectCount(args) <= MAX_OBJECTS &&
      campaignCardProblems(args).length === 0 &&
      // Image shapes need Google's read, so only the rules the card holds count here.
      assetGroupRows(args.assetGroups, {
        checks: null,
        retail: args.campaign.performanceMax?.merchant != null,
      }).every((row) => row.problems.length === 0)
    )
  return (
    args.adGroups.length > 0 &&
    requestObjectCount(args) <= MAX_OBJECTS &&
    campaignCardProblems(args).length === 0 &&
    args.adGroups.every(
      (group) => !adGroupCardProblems(group, args.adGroups, adGroupContext(args, false)).length
    )
  )
}

/** Why the request can't be approved yet, or null. */
export function createCampaignBlock(
  args: CreateCampaignArgs | null,
  checked: CreateCampaignArgs
): string | null {
  if (args === null) return null
  const performanceMax = args.campaign.type === "performance_max"
  const groups = performanceMax ? args.assetGroups : args.adGroups
  const noun = performanceMax ? "asset group" : "ad group"
  if (groups.length === 0)
    return `Every ${noun} is cancelled. Decline this request, or restore one.`
  const [problem] = requestProblems(args)
  if (problem) return problem
  if (campaignProblems(args).length > 0) return "Fix the campaign settings to continue."
  const failing = performanceMax
    ? campaignAssetGroupRows(args).filter((row) => row.problems.length > 0).length
    : createAdGroupsCounts(campaignAdGroupRows(args)).problems
  if (failing > 0) return `Fix or cancel ${approvalCountLine(failing, noun)} to continue.`
  return campaignNeedsCheck(args, checked)
    ? "Click Check Changes so Google can check your edits, then approve."
    : null
}

function number(count: number, noun: string): string {
  return `${count.toLocaleString("en-GB")} ${noun}${count === 1 ? "" : "s"}`
}

export function createCampaignPrompt(args: CreateCampaignArgs): string {
  const name = args.campaign.name.trim() || "this campaign"
  if (args.campaign.type === "performance_max") {
    if (args.assetGroups.length === 0) return "Nothing is left to create."
    return `Build ${name} with ${number(args.assetGroups.length, "asset group")}. Everything is created together, or nothing is.`
  }
  const counts = createAdGroupsCounts(campaignAdGroupRows(args))
  if (counts.adGroups === 0) return "Nothing is left to create."
  return `Build ${name} with ${number(counts.adGroups, "ad group")}, ${number(counts.keywords, "keyword")}, and ${number(counts.ads, "ad")}. Everything is created together, or nothing is.`
}

/** The daily amount the campaign can spend, as entered or read from the shared budget. */
export function dailyBudget(campaign: DraftCampaign): string | null {
  const amount = campaign.budget.dailyAmount?.trim() ?? ""
  return validMoney(amount) ? amount : null
}

export function money(amount: string, args: CreateCampaignArgs): string {
  const currency = currencyOf(args)
  return currency ? formatCurrencyAmount(amount, currency) : amount
}

/** About what a month at the daily budget costs, by Google's monthly charging limit. */
export function monthlyEstimate(campaign: DraftCampaign): string | null {
  const daily = dailyBudget(campaign)
  return daily === null ? null : (Math.round(Number(daily) * DAYS_PER_MONTH * 100) / 100).toFixed(2)
}

export function budgetSummary(args: CreateCampaignArgs): string {
  const { budget } = args.campaign
  const daily = dailyBudget(args.campaign)
  const amount = daily ? `${money(daily, args)} a day` : "No amount yet"
  return budget.kind === "shared" ? `Shared: ${budget.label} · ${amount}` : amount
}

export function biddingSummary(args: CreateCampaignArgs): string {
  const { bidding } = args.campaign
  const label = STRATEGY_LABELS[bidding.strategy]
  const cpa = bidding.targetCpa.trim()
  const roas = bidding.targetRoas.trim()
  const maxCpc = bidding.maxCpc.trim()
  if (bidding.strategy === "MAXIMIZE_CONVERSIONS" && cpa)
    return `${label} · Target CPA ${money(cpa, args)}`
  if (bidding.strategy === "MAXIMIZE_CONVERSION_VALUE" && roas)
    return `${label} · Target ROAS ${roas}%`
  if (bidding.strategy === "TARGET_IMPRESSION_SHARE")
    return `${label} · ${bidding.sharePercent || "?"}% ${PAGE_LOCATION_LABELS[bidding.pageLocation].toLowerCase()}`
  if (bidding.strategy === "MAXIMIZE_CLICKS" && maxCpc)
    return `${label} · Up to ${money(maxCpc, args)} a click`
  return label
}

export function createCampaignTitle(args: CreateCampaignArgs): string {
  return args.campaign.type === "performance_max"
    ? "Create Performance Max Campaign"
    : "Create Search Campaign"
}

export function createCampaignDetails(args: CreateCampaignArgs | null): FanOutDetail[] {
  if (args === null) return []
  if (args.campaign.type === "performance_max")
    return [
      { label: "Campaign", value: args.campaign.name },
      { label: "Type", value: "Performance Max" },
      { label: "Budget", value: budgetSummary(args) },
      { label: "Bidding", value: biddingSummary(args) },
      { label: "Asset Groups", value: String(args.assetGroups.length) },
      { label: "Status", value: args.status === "ENABLED" ? "Active" : "Paused" },
    ]
  const counts = createAdGroupsCounts(campaignAdGroupRows(args))
  return [
    { label: "Campaign", value: args.campaign.name },
    { label: "Budget", value: budgetSummary(args) },
    { label: "Bidding", value: biddingSummary(args) },
    { label: "Ad Groups", value: String(counts.adGroups) },
    { label: "Keywords", value: String(counts.keywords) },
    { label: "Ads", value: String(counts.ads) },
    { label: "Status", value: args.status === "ENABLED" ? "Active" : "Paused" },
  ]
}

function serializeBidding(bidding: DraftBidding): Record<string, unknown> {
  const maxCpc = bidding.maxCpc.trim() || null
  switch (bidding.strategy) {
    case "MANUAL_CPC":
      return { strategy: bidding.strategy }
    case "MAXIMIZE_CLICKS":
      return { strategy: bidding.strategy, max_cpc: maxCpc }
    case "MAXIMIZE_CONVERSIONS":
      return { strategy: bidding.strategy, target_cpa: bidding.targetCpa.trim() || null }
    case "MAXIMIZE_CONVERSION_VALUE":
      return { strategy: bidding.strategy, target_roas: serializeRoas(bidding.targetRoas) }
    case "TARGET_IMPRESSION_SHARE": {
      const share = Number(bidding.sharePercent)
      return {
        strategy: bidding.strategy,
        location: bidding.pageLocation,
        // Left as typed when invalid, so the card can show it and approval stays blocked.
        share_percent: Number.isInteger(share) ? share : bidding.sharePercent,
        max_cpc: maxCpc,
      }
    }
  }
}

/** The `campaign` value for the draft; blank optional fields are null. */
export function serializeCampaign(campaign: DraftCampaign): Record<string, unknown> {
  const location = (item: DraftLocation) => ({ key: item.key, name: item.name || null })
  const shared = {
    name: campaign.name,
    bidding: serializeBidding(campaign.bidding),
    locations: campaign.locations.map(location),
    excluded_locations: campaign.excludedLocations.map(location),
    location_setting: campaign.locationSetting,
    start_date: campaign.startDate.trim() || null,
    end_date: campaign.endDate.trim() || null,
    contains_eu_political_advertising: campaign.political,
  }
  if (campaign.performanceMax)
    return {
      ...shared,
      budget: { kind: "new", daily_amount: campaign.budget.dailyAmount?.trim() ?? "" },
      ...serializePerformanceMax(campaign.performanceMax),
    }
  return {
    name: campaign.name,
    budget:
      campaign.budget.kind === "new"
        ? { kind: "new", daily_amount: campaign.budget.dailyAmount.trim() }
        : { kind: "shared", budget: campaign.budget.reference },
    bidding: serializeBidding(campaign.bidding),
    search_partners: campaign.searchPartners,
    display_expansion: campaign.displayExpansion,
    locations: campaign.locations.map(location),
    excluded_locations: campaign.excludedLocations.map(location),
    location_setting: campaign.locationSetting,
    start_date: campaign.startDate.trim() || null,
    end_date: campaign.endDate.trim() || null,
    negative_keywords: campaign.negatives.map((item) => ({
      text: item.text,
      match_type: item.matchType,
    })),
    contains_eu_political_advertising: campaign.political,
    assets: serializeNewAssets(campaign.assets),
  }
}
