// apps/web/src/integrations/meta_ads/lib/create-campaign.ts

import { budgetMoney } from "@/integrations/meta_ads/lib/budget-change"
import { scheduleSentence, type SummaryLine } from "@/integrations/meta_ads/lib/create-summary"
import {
  OBJECTIVE_KEYS,
  OBJECTIVE_SENTENCES,
  type Objective,
} from "@/integrations/meta_ads/lib/objectives"
import { isNonEmptyString, isOneOf, isRecord, isStringArray, stringValue } from "@/lib/guards"

const OBJECTIVES: ReadonlySet<Objective> = new Set(OBJECTIVE_KEYS)
const BUDGET_MODES = new Set(["campaign_daily", "campaign_lifetime", "ad_set"] as const)
const BID_STRATEGIES = new Set([
  "highest_volume",
  "cost_per_result_goal",
  "bid_cap",
  "roas_goal",
] as const)
const BID_SENTENCES: Record<BidStrategy, string[]> = {
  highest_volume: ["Highest volume: Meta gets as many results as it can for the budget."],
  cost_per_result_goal: [
    "Cost per result goal: Meta aims to keep the average cost per result near a target.",
    "Each ad set needs its own target cost.",
  ],
  bid_cap: [
    "Bid cap: Meta never bids more than a set amount in each auction.",
    "Each ad set needs its own maximum bid.",
  ],
  roas_goal: [
    "Return on ad spend goal: Meta aims for a minimum return on what you spend.",
    "Each ad set needs its own minimum return. This can't be changed later.",
  ],
}
const CATEGORY_LABELS: Record<string, string> = {
  housing: "Housing",
  employment: "Employment",
  financial_products_services: "Financial products and services",
  online_gambling_and_gaming: "Online gambling and gaming",
}
const LIST = new Intl.ListFormat("en", { type: "conjunction" })
const REGIONS = new Intl.DisplayNames(["en-GB"], { type: "region" })
const FLEXIBLE_SPEND =
  "Meta may spend up to 75% more on some days, but no more than 7 times this amount in a week."

type BudgetMode = "campaign_daily" | "campaign_lifetime" | "ad_set"
type BidStrategy = "highest_volume" | "cost_per_result_goal" | "bid_cap" | "roas_goal"
type Category = { category: string; countries: string[] }

export type CreateCampaignArgs = {
  accountId: string | null
  accountName: string | null
  currency: string | null
  timezone: string | null
  minimum: string | null
  minimumSpendLimit: string | null
  name: string
  objective: Objective
  budget: { mode: BudgetMode; amount: string | null; shareBetweenAdSets: boolean | null }
  bidStrategy: BidStrategy
  categories: Category[]
  startDate: string | null
  endDate: string | null
  spendLimit: string | null
}

export function parseCreateCampaignArgs(value: unknown): CreateCampaignArgs | null {
  if (!isRecord(value)) return null
  const { name, objective, budget } = value
  if (!isNonEmptyString(name) || !isOneOf(OBJECTIVES, objective) || !isRecord(budget)) return null
  const mode = budget["mode"] ?? "campaign_daily"
  const bidStrategy = value["bid_strategy"] ?? "highest_volume"
  if (!isOneOf(BUDGET_MODES, mode) || !isOneOf(BID_STRATEGIES, bidStrategy)) return null
  const account = value["_account"]
  const share = budget["share_between_ad_sets"]
  return {
    accountId: isRecord(account) ? stringValue(account["account_id"]) : null,
    accountName: stringValue(value["_account_name"]),
    currency: stringValue(value["_currency"]),
    timezone: stringValue(value["_timezone"]),
    minimum: stringValue(value["_minimum"]),
    minimumSpendLimit: stringValue(value["_minimum_spend_limit"]),
    name,
    objective,
    budget: {
      mode,
      amount: stringValue(budget["amount"]),
      shareBetweenAdSets: typeof share === "boolean" ? share : null,
    },
    bidStrategy,
    categories: parseCategories(value["special_ad_categories"]),
    startDate: stringValue(value["start_date"]),
    endDate: stringValue(value["end_date"]),
    spendLimit: stringValue(value["spend_limit"]),
  }
}

function parseCategories(value: unknown): Category[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) =>
    isRecord(item) && isNonEmptyString(item["category"]) && isStringArray(item["countries"])
      ? [{ category: item["category"], countries: item["countries"] }]
      : []
  )
}

function region(code: string): string {
  try {
    return REGIONS.of(code) ?? code
  } catch {
    return code
  }
}

/** The campaign in sentences: objective, budget, bidding, categories, and schedule. */
export function campaignSummary(args: CreateCampaignArgs): SummaryLine[] {
  return [
    { label: "Objective", sentences: [OBJECTIVE_SENTENCES[args.objective]] },
    { label: "Budget", sentences: budgetSentences(args) },
    { label: "Bidding", sentences: BID_SENTENCES[args.bidStrategy] },
    { label: "Special Category", sentences: categorySentences(args.categories) },
    {
      label: "Schedule",
      sentences: [scheduleSentence(args.startDate, args.endDate, args.timezone)],
    },
  ]
}

function budgetSentences(args: CreateCampaignArgs): string[] {
  const { budget, currency } = args
  if (budget.mode === "ad_set") {
    return [
      "Each ad set has its own budget.",
      budget.shareBetweenAdSets
        ? "Ad sets can share up to 20% of their budgets with each other. Each needs a daily budget."
        : "Ad sets don't share their budgets.",
    ]
  }
  const money = budget.amount ? budgetMoney(budget.amount, currency) : "No amount"
  const sentences =
    budget.mode === "campaign_daily"
      ? [`${money} a day, shared across the campaign's ad sets.`, FLEXIBLE_SPEND]
      : [`${money} in total, shared across the campaign's ad sets.`]
  if (args.minimum)
    sentences.push(`The ad account's minimum is ${budgetMoney(args.minimum, currency)} a day.`)
  return sentences
}

function categorySentences(categories: Category[]): string[] {
  if (categories.length === 0) return ["None."]
  return [
    ...categories.map(
      (item) =>
        `${CATEGORY_LABELS[item.category] ?? item.category}, in ${LIST.format(item.countries.map(region))}.`
    ),
    "Ad sets in this campaign can't target by age, gender, or postcode.",
  ]
}

/** Blocks approval for amounts under the ad account's minimums, which Meta would refuse. */
export function createCampaignProblem(args: CreateCampaignArgs | null): string | null {
  if (!args) return null
  const { budget } = args
  if (
    budget.mode === "campaign_daily" &&
    budget.amount &&
    args.minimum &&
    Number(budget.amount) < Number(args.minimum)
  )
    return `The minimum daily budget for this ad account is ${budgetMoney(args.minimum, args.currency)}.`
  if (budget.mode === "campaign_lifetime" && !args.endDate)
    return "A lifetime budget needs an end date."
  if (
    args.spendLimit &&
    args.minimumSpendLimit &&
    Number(args.spendLimit) < Number(args.minimumSpendLimit)
  )
    return `The smallest spending limit for this ad account is ${budgetMoney(args.minimumSpendLimit, args.currency)}.`
  return null
}

export function campaignPrompt(args: CreateCampaignArgs): string {
  return `Create the campaign ${args.name}${args.accountName ? ` in ${args.accountName}` : ""}.`
}
