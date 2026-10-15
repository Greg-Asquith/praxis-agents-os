// apps/web/src/integrations/meta_ads/lib/create-ad-set.ts

import type { EditedValue } from "@/components/tool-ui/edited-values"
import type { CreateStatus } from "@/integrations/meta_ads/components/status-choice"
import { budgetMoney } from "@/integrations/meta_ads/lib/budget-change"
import { BID_OPTIONS, type BidStrategy } from "@/integrations/meta_ads/lib/create-campaign"
import { scheduleSummary } from "@/integrations/meta_ads/lib/create-summary"
import {
  ASSET_LABELS,
  CONVERSION_EVENT_LABELS,
  GOAL_KEYS,
  GOALS,
  type Goal,
  type GoalAsset,
} from "@/integrations/meta_ads/lib/goals"
import { OBJECTIVE_KEYS, type Objective } from "@/integrations/meta_ads/lib/objectives"
import {
  detailedGroups,
  itemName,
  targetingItems,
} from "@/integrations/meta_ads/lib/targeting-edit"
import { isNonEmptyString, isOneOf, isRecord, isStringArray, stringValue } from "@/lib/guards"

const GOAL_SET: ReadonlySet<Goal> = new Set(GOAL_KEYS)
const OBJECTIVE_SET: ReadonlySet<string> = new Set(OBJECTIVE_KEYS)
const BID_KEYS: Record<string, BidStrategy> = {
  LOWEST_COST_WITHOUT_CAP: "highest_volume",
  COST_CAP: "cost_per_result_goal",
  LOWEST_COST_WITH_BID_CAP: "bid_cap",
  LOWEST_COST_WITH_MIN_ROAS: "roas_goal",
  highest_volume: "highest_volume",
  cost_per_result_goal: "cost_per_result_goal",
  bid_cap: "bid_cap",
  roas_goal: "roas_goal",
}
// Categories whose ads Meta limits to broad targeting.
const TARGETING_CATEGORIES = new Set([
  "HOUSING",
  "EMPLOYMENT",
  "FINANCIAL_PRODUCTS_SERVICES",
  "CREDIT",
])
const LIST = new Intl.ListFormat("en", { type: "conjunction" })
const GENDERS = { all: "All genders", men: "Men", women: "Women" } as const

export const PLACEMENT_GROUPS = [
  {
    label: "Facebook",
    positions: [
      ["facebook:feed", "Feed"],
      ["facebook:profile_feed", "Profile Feed"],
      ["facebook:right_hand_column", "Right Column"],
      ["facebook:marketplace", "Marketplace"],
      ["facebook:story", "Stories"],
      ["facebook:facebook_reels", "Reels"],
      ["facebook:instream_video", "In-Stream Videos"],
      ["facebook:search", "Search Results"],
    ],
  },
  {
    label: "Instagram",
    positions: [
      ["instagram:stream", "Feed"],
      ["instagram:story", "Stories"],
      ["instagram:reels", "Reels"],
      ["instagram:profile_feed", "Profile Feed"],
      ["instagram:ig_search", "Search Results"],
    ],
  },
  {
    label: "Audience Network",
    positions: [
      ["audience_network:classic", "Banners and Interstitials"],
      ["audience_network:rewarded_video", "Rewarded Videos"],
    ],
  },
  { label: "Messenger", positions: [["messenger:messenger_home", "Inbox"]] },
  { label: "Threads", positions: [["threads:threads_stream", "Feed"]] },
] as const
const POSITION_LABELS = new Map<string, string>(
  PLACEMENT_GROUPS.flatMap((group) =>
    group.positions.map(([key, label]) => [key, `${group.label} ${label}`] as const)
  )
)
export const DEFAULT_POSITIONS = ["facebook:feed", "instagram:stream"]

export type Placements = { mode: "automatic" | "manual"; positions: string[]; devices: string }
type CampaignFacts = {
  name: string
  objective: Objective | null
  status: string | null
  budget: { amount: string | null; period: string | null } | null
  bidStrategy: BidStrategy | null
  shareBetweenAdSets: boolean
}
type Budget = { kind: "daily" | "lifetime"; amount: string }

export type CreateAdSetArgs = {
  accountId: string | null
  accountName: string | null
  currency: string | null
  timezone: string | null
  minimum: string | null
  // The goal the minimum was read for; null when the backend didn't say.
  minimumGoal: string | null
  name: string
  status: CreateStatus
  campaign: CampaignFacts
  specialCategory: boolean
  goal: Goal
  references: Record<GoalAsset, Record<string, unknown> | null>
  event: string | null
  customConversion: { id: string; name: string | null } | null
  appStore: string | null
  budget: Budget | null
  bidStrategy: BidStrategy | null
  bidAmount: string | null
  minRoas: string | null
  payPerClick: boolean
  startDate: string | null
  endDate: string | null
  placements: Placements
  targeting: Record<string, unknown>
  euApplies: boolean
  euPayer: string | null
  euBeneficiary: string | null
  defaultPayer: string | null
  defaultBeneficiary: string | null
  // True when the custom conversion counts events from a pixel other than the one chosen.
  conversionPixelMismatch: boolean
}

export function parseCreateAdSetArgs(value: unknown): CreateAdSetArgs | null {
  if (!isRecord(value)) return null
  const { campaign, goal, name, targeting } = value
  if (
    !isRecord(campaign) ||
    !isNonEmptyString(campaign["campaign_id"]) ||
    !isOneOf(GOAL_SET, goal) ||
    !isNonEmptyString(name) ||
    !isRecord(targeting)
  )
    return null
  const account = value["_account"]
  const eu = isRecord(value["_eu"]) ? value["_eu"] : {}
  const placements = isRecord(value["placements"]) ? value["placements"] : {}
  const read = isRecord(value["_custom_conversion"]) ? value["_custom_conversion"] : null
  const customId = stringValue(value["custom_conversion_id"])
  return {
    accountId: isRecord(account) ? stringValue(account["account_id"]) : null,
    accountName: stringValue(value["_account_name"]),
    currency: stringValue(value["_currency"]),
    timezone: stringValue(value["_timezone"]),
    minimum: stringValue(value["_minimum"]),
    minimumGoal: stringValue(value["_minimum_goal"]),
    name,
    status: value["status"] === "active" ? "active" : "paused",
    campaign: parseCampaign(campaign),
    specialCategory: parseSpecialCategory(campaign),
    goal,
    references: {
      page: isRecord(value["page"]) ? value["page"] : null,
      pixel: isRecord(value["pixel"]) ? value["pixel"] : null,
      app: isRecord(value["app"]) ? value["app"] : null,
    },
    event: stringValue(value["conversion_event"]),
    customConversion: customId
      ? { id: customId, name: read ? stringValue(read["name"]) : null }
      : null,
    appStore: stringValue(value["app_store"]),
    budget: parseBudget(value["budget"]),
    bidStrategy: BID_KEYS[String(value["bid_strategy"])] ?? null,
    bidAmount: stringValue(value["bid_amount"]),
    minRoas: stringValue(value["min_roas"]),
    payPerClick: value["pay_per_click"] === true,
    startDate: stringValue(value["start_date"]),
    endDate: stringValue(value["end_date"]),
    placements: {
      mode: placements["mode"] === "manual" ? "manual" : "automatic",
      positions: isStringArray(placements["positions"]) ? placements["positions"] : [],
      devices: stringValue(placements["devices"]) ?? "all",
    },
    targeting,
    euApplies: eu["applies"] === true,
    euPayer: stringValue(value["eu_payer"]),
    euBeneficiary: stringValue(value["eu_beneficiary"]),
    defaultPayer: stringValue(eu["default_payer"]),
    defaultBeneficiary: stringValue(eu["default_beneficiary"]),
    conversionPixelMismatch: Boolean(
      read &&
      isRecord(value["pixel"]) &&
      stringValue(read["pixel_id"]) &&
      stringValue(value["pixel"]["pixel_id"]) &&
      read["pixel_id"] !== value["pixel"]["pixel_id"]
    ),
  }
}

function parseCampaign(campaign: Record<string, unknown>): CampaignFacts {
  const objective = (stringValue(campaign["objective"]) ?? "")
    .replace(/^OUTCOME_/, "")
    .toLowerCase()
  const budget = campaign["budget"]
  return {
    name: stringValue(campaign["label"]) ?? `Campaign ${String(campaign["campaign_id"])}`,
    objective: OBJECTIVE_SET.has(objective) ? (objective as Objective) : null,
    status: stringValue(campaign["effective_status"]) ?? stringValue(campaign["status"]),
    budget: isRecord(budget)
      ? {
          amount: stringValue(budget["amount"]),
          period: stringValue(budget["period"]) ?? stringValue(budget["kind"]),
        }
      : null,
    bidStrategy: BID_KEYS[String(campaign["bid_strategy"])] ?? null,
    shareBetweenAdSets: campaign["share_between_ad_sets"] === true,
  }
}

function parseSpecialCategory(campaign: Record<string, unknown>): boolean {
  const categories = campaign["special_ad_categories"]
  return isStringArray(categories) && categories.some((item) => TARGETING_CATEGORIES.has(item))
}

function parseBudget(value: unknown): Budget | null {
  if (!isRecord(value) || typeof value["amount"] !== "string") return null
  const kind = value["kind"]
  return kind === "daily" || kind === "lifetime" ? { kind, amount: value["amount"] } : null
}

/** The strategy the ad set bids by: its campaign's, or its own. */
export function effectiveBid(args: CreateAdSetArgs): BidStrategy {
  return args.campaign.bidStrategy ?? args.bidStrategy ?? "highest_volume"
}

/** Goals that suit the campaign's objective, or every goal when the campaign's is unknown. */
export function goalsForCampaign(campaign: CampaignFacts): Goal[] {
  return GOAL_KEYS.filter(
    (goal) => !campaign.objective || GOALS[goal].objective === campaign.objective
  )
}

/** The edits that move the ad set to another goal, dropping settings the new goal doesn't use. */
export function goalEdits(args: CreateAdSetArgs, goal: Goal): Record<string, EditedValue> {
  const { asset, clicksBilling } = GOALS[goal]
  const edits: Record<string, EditedValue> = { goal }
  for (const key of ["page", "pixel", "app"] as const) {
    if (key !== asset && args.references[key]) edits[key] = null
  }
  if (asset !== "pixel") {
    if (args.event) edits["conversion_event"] = null
    if (args.customConversion) edits["custom_conversion_id"] = null
  } else if (!args.event && !args.customConversion) edits["conversion_event"] = "PURCHASE"
  if (asset === "app") {
    if (!args.appStore) edits["app_store"] = "google_play"
  } else if (args.appStore) edits["app_store"] = null
  if (!clicksBilling && args.payPerClick) edits["pay_per_click"] = false
  return edits
}

/** The edits that switch the ad set's own bid strategy, clearing the amounts of the old one. */
export function bidEdits(strategy: BidStrategy): Record<string, EditedValue> {
  return { bid_strategy: strategy, bid_amount: null, min_roas: null }
}

function placementLabel(position: string): string {
  return POSITION_LABELS.get(position) ?? position
}

function placementSummary(placements: Placements): string {
  if (placements.mode === "automatic") return "Automatic: Meta shows the ads where they cost less"
  const labels = placements.positions.map(placementLabel)
  return `${String(labels.length)} places: ${LIST.format(labels)}`
}

function goalSummary(args: CreateAdSetArgs): string {
  const { asset } = GOALS[args.goal]
  const reference = asset ? args.references[asset] : null
  const event = args.customConversion
    ? `Custom conversion ${args.customConversion.name ?? args.customConversion.id}`
    : args.event
      ? (CONVERSION_EVENT_LABELS[args.event] ?? args.event)
      : null
  return [
    GOALS[args.goal].label,
    asset ? (stringValue(reference?.["label"]) ?? `Choose a ${ASSET_LABELS[asset]}`) : null,
    event,
  ]
    .filter(Boolean)
    .join(" · ")
}

function budgetSummary(args: CreateAdSetArgs): string {
  const { budget, campaign, currency } = args
  const held = campaign.budget?.amount
  const money = budget
    ? `${budgetMoney(budget.amount, currency)} ${budget.kind === "daily" ? "a day" : "in total"}`
    : held
      ? `Campaign budget of ${budgetMoney(held, currency)}${campaign.budget?.period === "lifetime" ? " in total" : " a day"}`
      : "Uses the campaign budget"
  return `${money} · ${scheduleSummary(args.startDate, args.endDate)}`
}

/** One line for each setting row, shown while the row is closed. */
export function adSetSummaries(args: CreateAdSetArgs) {
  const { targeting } = args
  const places = targetingItems(targeting["locations"]).map(itemName)
  const interests = detailedGroups(targeting).flat().map(itemName)
  const audiences = targetingItems(targeting["audiences"]).map(itemName)
  const max = typeof targeting["age_max"] === "number" ? String(targeting["age_max"]) : "65+"
  const gender =
    GENDERS[
      targeting["genders"] === "men" || targeting["genders"] === "women"
        ? targeting["genders"]
        : "all"
    ]
  const payer = args.euPayer ?? args.defaultPayer
  const beneficiary = args.euBeneficiary ?? args.defaultBeneficiary
  const chosen = [...interests, ...audiences]
  return {
    goal: goalSummary(args),
    budget: budgetSummary(args),
    locations: places.length > 0 ? places.join(", ") : "No location yet",
    people: `${typeof targeting["age_min"] === "number" ? String(targeting["age_min"]) : "18"} to ${max} · ${gender.toLowerCase()}`,
    interests: chosen.length > 0 ? chosen.join(", ") : "Anyone in these places",
    placements: placementSummary(args.placements),
    eu:
      payer && beneficiary
        ? `Paid for by ${payer}, for ${beneficiary}`
        : "Needs who pays and who benefits",
  }
}

/** What the status choice says the ad set will do, and whether its campaign holds it back. */
export function adSetStatusNote(args: CreateAdSetArgs): string {
  const { budget, campaign, currency } = args
  const amount = budget?.amount ?? campaign.budget?.amount
  const kind = budget?.kind ?? (campaign.budget?.period === "lifetime" ? "lifetime" : "daily")
  const limit = amount
    ? `Up to ${budgetMoney(amount, currency)}${kind === "daily" ? " a day" : " in total"}`
    : "It spends"
  if (campaign.status === "PAUSED")
    return `Turns on when created, but it won't spend yet: its campaign ${campaign.name} is paused. ${limit} once that's on.`
  return `Turns on when created. ${limit} once it has approved ads.`
}

export function bidLabel(strategy: BidStrategy): string {
  return BID_OPTIONS.find((item) => item.value === strategy)?.label ?? strategy
}

function euProblem(args: CreateAdSetArgs): string | null {
  if (!args.euApplies) return null
  if ((args.euPayer ?? args.defaultPayer) && (args.euBeneficiary ?? args.defaultBeneficiary))
    return null
  return "This ad set reaches the EU. Add who pays for the ads and who they benefit under EU Transparency."
}

function goalProblem(args: CreateAdSetArgs): string | null {
  const { asset } = GOALS[args.goal]
  if (asset && !args.references[asset]) return `Choose a ${ASSET_LABELS[asset]} for this goal.`
  if (asset === "pixel" && !args.event && !args.customConversion)
    return "Choose what counts as a result for the pixel."
  if (asset === "app" && !args.appStore) return "Choose the app store the app is in."
  if (args.conversionPixelMismatch)
    return "The custom conversion counts events from another pixel. Choose that pixel, or a standard event."
  const strategy = effectiveBid(args)
  if ((strategy === "cost_per_result_goal" || strategy === "bid_cap") && !args.bidAmount)
    return strategy === "bid_cap" ? "Set the maximum bid." : "Set the target cost per result."
  if (strategy === "roas_goal" && !args.minRoas) return "Set the minimum return on ad spend."
  return null
}

function budgetProblem(args: CreateAdSetArgs): string | null {
  const { budget, campaign } = args
  if (!campaign.budget && !budget?.amount) return "Set the ad set's budget."
  if (budget?.kind === "lifetime" && !args.endDate) return "A lifetime budget needs an end date."
  // The minimum was read for the proposed goal, so it holds only while the goal is unchanged.
  if (
    budget?.kind === "daily" &&
    args.minimum &&
    args.minimumGoal === args.goal &&
    Number(budget.amount) < Number(args.minimum)
  )
    return `The minimum daily budget for this goal is ${budgetMoney(args.minimum, args.currency)}.`
  return null
}

function targetingProblem(args: CreateAdSetArgs): string | null {
  const { targeting } = args
  const locations = targetingItems(targeting["locations"])
  const min = typeof targeting["age_min"] === "number" ? targeting["age_min"] : 18
  const max = typeof targeting["age_max"] === "number" ? targeting["age_max"] : null
  if (locations.length === 0) return "Add at least one location."
  if (max !== null && max < min) return "The maximum age can't be below the minimum age."
  if (targeting["advantage_audience"] !== false && (max !== null || min < 18 || min > 25))
    return "Advantage+ audience needs a minimum age of 18 to 25 and no maximum age. Turn it off under Interests to set an exact age range."
  if (args.specialCategory && locations.some((item) => item["kind"] === "postcode"))
    return "Housing, employment, and financial ads can't target postcodes. Remove them under Locations."
  if (args.placements.mode === "manual" && args.placements.positions.length === 0)
    return "Choose at least one place for the ads, or let Meta choose."
  return null
}

/** Blocks approval for what Meta would refuse, such as missing settings or a budget under the minimum. */
export function createAdSetProblem(args: CreateAdSetArgs | null): string | null {
  if (!args) return null
  return euProblem(args) ?? goalProblem(args) ?? budgetProblem(args) ?? targetingProblem(args)
}

export function adSetPrompt(args: CreateAdSetArgs): string {
  return `Create the ad set ${args.name} in ${args.campaign.name}${args.accountName ? `, in ${args.accountName}` : ""}.`
}
