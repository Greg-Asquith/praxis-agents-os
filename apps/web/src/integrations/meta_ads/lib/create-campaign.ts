// apps/web/src/integrations/meta_ads/lib/create-campaign.ts

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { budgetMoney, isBudgetAmount } from "@/integrations/meta_ads/lib/budget-change"
import { scheduleSummary } from "@/integrations/meta_ads/lib/create-summary"
import { OBJECTIVE_KEYS, OBJECTIVES, type Objective } from "@/integrations/meta_ads/lib/objectives"
import type { CreateStatus } from "@/integrations/meta_ads/components/status-choice"
import { isNonEmptyString, isOneOf, isRecord, isStringArray, stringValue } from "@/lib/guards"

const OBJECTIVE_SET: ReadonlySet<Objective> = new Set(OBJECTIVE_KEYS)
const BUDGET_MODES = new Set(["campaign_daily", "campaign_lifetime", "ad_set"] as const)
const BID_STRATEGIES = new Set([
  "highest_volume",
  "cost_per_result_goal",
  "bid_cap",
  "roas_goal",
] as const)
export const AMOUNT_FORMAT = "Enter amounts above zero, with at most two decimal places."
const LIST = new Intl.ListFormat("en", { type: "conjunction" })
const REGIONS = new Intl.DisplayNames(["en-GB"], { type: "region" })

export type BudgetMode = "campaign_daily" | "campaign_lifetime" | "ad_set"
export type BidStrategy = "highest_volume" | "cost_per_result_goal" | "bid_cap" | "roas_goal"
export type Category = { category: string; countries: string[] }

export const BID_OPTIONS: readonly { value: BidStrategy; label: string; description: string }[] = [
  {
    value: "highest_volume",
    label: "Highest Volume",
    description: "Meta gets as many results as it can for the budget.",
  },
  {
    value: "cost_per_result_goal",
    label: "Cost per Result Goal",
    description:
      "Meta aims to keep the average cost per result near a target. Each ad set sets its own target cost.",
  },
  {
    value: "bid_cap",
    label: "Bid Cap",
    description:
      "Meta never bids more than a set amount in each auction. Each ad set sets its own maximum bid.",
  },
  {
    value: "roas_goal",
    label: "Return on Ad Spend Goal",
    description:
      "Meta aims for a minimum return on what you spend. Each ad set sets its own minimum return. This can't be changed later.",
  },
]
export const CATEGORY_OPTIONS = [
  { value: "housing", label: "Housing" },
  { value: "employment", label: "Employment" },
  { value: "financial_products_services", label: "Financial Products and Services" },
  { value: "online_gambling_and_gaming", label: "Online Gambling and Gaming" },
] as const

export type CreateCampaignArgs = {
  accountId: string | null
  accountName: string | null
  currency: string | null
  timezone: string | null
  minimum: string | null
  minimumSpendLimit: string | null
  name: string
  status: CreateStatus
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
  if (typeof name !== "string" || !isOneOf(OBJECTIVE_SET, objective) || !isRecord(budget))
    return null
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
    status: value["status"] === "active" ? "active" : "paused",
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

export function regionName(code: string): string {
  try {
    return REGIONS.of(code) ?? code
  } catch {
    return code
  }
}

/** The budget as the tool takes it: an ad set budget has no amount, a campaign budget no sharing. */
export function campaignBudgetValue(budget: CreateCampaignArgs["budget"]): EditedValue {
  if (budget.mode === "ad_set")
    return { mode: budget.mode, share_between_ad_sets: budget.shareBetweenAdSets ?? false }
  return { mode: budget.mode, ...(budget.amount ? { amount: budget.amount } : {}) }
}

/** Return on ad spend goals need a sales campaign with a campaign budget. */
export function roasAllowed(objective: Objective, mode: BudgetMode): boolean {
  return objective === "sales" && mode !== "ad_set"
}

export function categoryLabel(category: string): string {
  return CATEGORY_OPTIONS.find((item) => item.value === category)?.label ?? category
}

/** One line for each setting row, shown while the row is closed. */
export function campaignSummaries(args: CreateCampaignArgs) {
  const { budget, currency } = args
  const money = budget.amount ? budgetMoney(budget.amount, currency) : "No amount"
  const objective = OBJECTIVES[args.objective]
  const bidding = BID_OPTIONS.find((item) => item.value === args.bidStrategy)
  return {
    objective: `${objective.label}: ${objective.description}`,
    budget:
      budget.mode === "ad_set"
        ? "A budget in each ad set"
        : `${money} ${budget.mode === "campaign_daily" ? "a day" : "in total"} · one budget for the campaign`,
    bidding: bidding?.label ?? "",
    schedule:
      scheduleSummary(args.startDate, args.endDate) +
      (args.spendLimit ? ` · limit ${budgetMoney(args.spendLimit, currency)}` : ""),
    categories:
      args.categories.length === 0
        ? "None"
        : args.categories
            .map(
              (item) =>
                `${categoryLabel(item.category)}${item.countries.length > 0 ? ` in ${LIST.format(item.countries.map(regionName))}` : ""}`
            )
            .join(", "),
  }
}

/** What the status choice says the campaign will do, with the most it can spend. */
export function campaignStatusNote(args: CreateCampaignArgs): string {
  const { budget, currency } = args
  const limit =
    budget.mode === "ad_set" || !budget.amount
      ? "what its ad sets are budgeted"
      : `up to ${budgetMoney(budget.amount, currency)}${budget.mode === "campaign_daily" ? " a day" : " in total"}`
  return `Turns on when created. It spends ${limit} once it has active ad sets and approved ads.`
}

/** Blocks approval for what Meta would refuse: a missing name, amount, or country, or amounts under the minimums. */
export function createCampaignProblem(args: CreateCampaignArgs | null): string | null {
  if (!args) return null
  const { budget } = args
  if (!args.name.trim()) return "Name the campaign."
  if (budget.mode !== "ad_set" && !budget.amount) return "Set the campaign's budget amount."
  if (
    (budget.amount && !isBudgetAmount(budget.amount)) ||
    (args.spendLimit && !isBudgetAmount(args.spendLimit))
  )
    return AMOUNT_FORMAT
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
  const missing = args.categories.find((item) => item.countries.length === 0)
  if (missing) return `Choose at least one country for ${categoryLabel(missing.category)}.`
  return null
}

export function campaignPrompt(args: CreateCampaignArgs): string {
  return `Create the campaign ${args.name}${args.accountName ? ` in ${args.accountName}` : ""}.`
}
