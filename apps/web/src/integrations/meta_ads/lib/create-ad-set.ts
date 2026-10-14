// apps/web/src/integrations/meta_ads/lib/create-ad-set.ts

import { budgetMoney } from "@/integrations/meta_ads/lib/budget-change"
import {
  CONVERSION_EVENT_LABELS,
  GOAL_KEYS,
  goalSentence,
  type Goal,
} from "@/integrations/meta_ads/lib/goals"
import { targetingSentences } from "@/integrations/meta_ads/lib/targeting-sentence"
import { isNonEmptyString, isOneOf, isRecord, isStringArray, stringValue } from "@/lib/guards"

const GOALS: ReadonlySet<Goal> = new Set(GOAL_KEYS)
// Categories whose ads Meta limits to broad targeting.
const TARGETING_CATEGORIES = new Set([
  "HOUSING",
  "EMPLOYMENT",
  "FINANCIAL_PRODUCTS_SERVICES",
  "CREDIT",
])
const POSITION_LABELS: Record<string, string> = {
  "facebook:feed": "Facebook Feed",
  "facebook:profile_feed": "Facebook profile feed",
  "facebook:right_hand_column": "Facebook right column",
  "facebook:marketplace": "Facebook Marketplace",
  "facebook:story": "Facebook Stories",
  "facebook:facebook_reels": "Facebook Reels",
  "facebook:instream_video": "Facebook in-stream videos",
  "facebook:search": "Facebook search results",
  "instagram:stream": "Instagram Feed",
  "instagram:story": "Instagram Stories",
  "instagram:reels": "Instagram Reels",
  "instagram:profile_feed": "Instagram profile feed",
  "instagram:ig_search": "Instagram search results",
  "audience_network:classic": "Audience Network",
  "audience_network:rewarded_video": "Audience Network rewarded videos",
  "messenger:messenger_home": "Messenger inbox",
  "threads:threads_stream": "Threads",
}
const DAY = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
})
const LIST = new Intl.ListFormat("en", { type: "conjunction" })
const ADVANTAGE_PLUS_NOTE = "Manual placements stop the campaign qualifying as Advantage+."
export const PAUSED_NOTE = "This is created paused. Nothing runs or spends until you turn it on."
const EU_PUBLIC = "Meta shows these names publicly in its ad library."

type Budget = { kind: "daily" | "lifetime"; amount: string }

export type CreateAdSetArgs = {
  accountId: string | null
  accountName: string | null
  currency: string | null
  timezone: string | null
  minimum: string | null
  campaignName: string
  campaignBudget: { amount: string | null; period: string | null } | null
  specialCategory: boolean
  goal: Goal
  name: string
  asset: string | null
  event: string | null
  budget: Budget | null
  bidAmount: string | null
  minRoas: string | null
  startDate: string | null
  endDate: string | null
  positions: string[]
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
    !isOneOf(GOALS, goal) ||
    !isNonEmptyString(name) ||
    !isRecord(targeting)
  )
    return null
  const account = value["_account"]
  const eu = isRecord(value["_eu"]) ? value["_eu"] : {}
  const placements = isRecord(value["placements"]) ? value["placements"] : {}
  const categories = campaign["special_ad_categories"]
  return {
    accountId: isRecord(account) ? stringValue(account["account_id"]) : null,
    accountName: stringValue(value["_account_name"]),
    currency: stringValue(value["_currency"]),
    timezone: stringValue(value["_timezone"]),
    minimum: stringValue(value["_minimum"]),
    campaignName: stringValue(campaign["label"]) ?? `Campaign ${campaign["campaign_id"]}`,
    campaignBudget: isRecord(campaign["budget"])
      ? {
          amount: stringValue(campaign["budget"]["amount"]),
          period:
            stringValue(campaign["budget"]["period"]) ?? stringValue(campaign["budget"]["kind"]),
        }
      : null,
    specialCategory:
      isStringArray(categories) && categories.some((item) => TARGETING_CATEGORIES.has(item)),
    goal,
    name,
    asset: assetLabel(value),
    event: eventLabel(value),
    budget: parseBudget(value["budget"]),
    bidAmount: stringValue(value["bid_amount"]),
    minRoas: stringValue(value["min_roas"]),
    startDate: stringValue(value["start_date"]),
    endDate: stringValue(value["end_date"]),
    positions:
      placements["mode"] === "manual" && isStringArray(placements["positions"])
        ? placements["positions"]
        : [],
    targeting,
    euApplies: eu["applies"] === true,
    euPayer: stringValue(value["eu_payer"]),
    euBeneficiary: stringValue(value["eu_beneficiary"]),
    defaultPayer: stringValue(eu["default_payer"]),
    defaultBeneficiary: stringValue(eu["default_beneficiary"]),
    conversionPixelMismatch: conversionPixelMismatch(value),
  }
}

function assetLabel(value: Record<string, unknown>): string | null {
  for (const key of ["page", "pixel", "app"]) {
    const reference = value[key]
    if (isRecord(reference)) return stringValue(reference["label"])
  }
  return null
}

function eventLabel(value: Record<string, unknown>): string | null {
  const event = stringValue(value["conversion_event"])
  if (event) return CONVERSION_EVENT_LABELS[event] ?? event
  const custom = stringValue(value["custom_conversion_id"])
  if (!custom) return null
  const read = value["_custom_conversion"]
  const name = isRecord(read) ? stringValue(read["name"]) : null
  return name ? `custom conversion ${name}` : `custom conversion ${custom}`
}

function conversionPixelMismatch(value: Record<string, unknown>): boolean {
  const read = value["_custom_conversion"]
  const pixel = value["pixel"]
  const conversionPixel = isRecord(read) ? stringValue(read["pixel_id"]) : null
  const chosen = isRecord(pixel) ? stringValue(pixel["pixel_id"]) : null
  return Boolean(conversionPixel && chosen && conversionPixel !== chosen)
}

function parseBudget(value: unknown): Budget | null {
  if (!isRecord(value) || !isNonEmptyString(value["amount"])) return null
  const kind = value["kind"]
  return kind === "daily" || kind === "lifetime" ? { kind, amount: value["amount"] } : null
}

function day(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? value : DAY.format(parsed)
}

export type SummaryLine = { label: string; sentences: string[] }

/** The ad set in sentences: goal, budget, schedule, who, where, and EU transparency. */
export function adSetSummary(args: CreateAdSetArgs): SummaryLine[] {
  const lines: SummaryLine[] = [
    { label: "Goal", sentences: [goalSentence(args.goal, args.asset, args.event)] },
    { label: "Budget", sentences: budgetSentences(args) },
    { label: "Schedule", sentences: [scheduleSentence(args)] },
    {
      label: "Who",
      sentences: targetingSentences(args.targeting, { specialCategory: args.specialCategory }),
    },
    { label: "Where", sentences: placementSentences(args.positions) },
  ]
  if (args.euApplies) lines.push({ label: "EU Transparency", sentences: euSentences(args) })
  return lines
}

function budgetSentences(args: CreateAdSetArgs): string[] {
  const sentences: string[] = []
  if (args.budget) {
    const money = budgetMoney(args.budget.amount, args.currency)
    sentences.push(args.budget.kind === "daily" ? `${money} a day.` : `${money} in total.`)
  } else {
    const held = args.campaignBudget
    const money = held?.amount ? budgetMoney(held.amount, args.currency) : null
    sentences.push(
      money
        ? `Uses the campaign budget of ${money}${held?.period === "lifetime" ? " in total" : " a day"}.`
        : "Uses the campaign budget."
    )
  }
  if (args.bidAmount)
    sentences.push(`Bids up to ${budgetMoney(args.bidAmount, args.currency)} per result.`)
  if (args.minRoas) sentences.push(`Aims for at least ${args.minRoas} times the ad spend back.`)
  return sentences
}

function scheduleSentence(args: CreateAdSetArgs): string {
  const start = args.startDate ? `Starts ${day(args.startDate)}` : "Starts when you turn it on"
  const end = args.endDate ? `ends ${day(args.endDate)}` : "runs until you turn it off"
  const zone = args.timezone ? ` (${args.timezone})` : ""
  return `${start} and ${end}${zone}.`
}

function placementSentences(positions: string[]): string[] {
  if (positions.length === 0)
    return ["Automatic placements: Meta shows the ads where they usually cost less."]
  return [
    `Only on ${LIST.format(positions.map((item) => POSITION_LABELS[item] ?? item))}.`,
    ADVANTAGE_PLUS_NOTE,
  ]
}

function euSentences(args: CreateAdSetArgs): string[] {
  const payer = args.euPayer ?? args.defaultPayer
  const beneficiary = args.euBeneficiary ?? args.defaultBeneficiary
  if (!payer || !beneficiary) return ["Meta needs who pays for the ads and who they benefit."]
  const source = args.euPayer && args.euBeneficiary ? "" : " (the ad account's defaults)"
  return [`Paid for by ${payer}, for ${beneficiary}${source}.`, EU_PUBLIC]
}

function euProblem(args: CreateAdSetArgs): string | null {
  if (!args.euApplies) return null
  if ((args.euPayer ?? args.defaultPayer) && (args.euBeneficiary ?? args.defaultBeneficiary))
    return null
  return "This ad set reaches the EU. Add who pays for the ads and who they benefit under More settings."
}

/** Blocks approval for what Meta would refuse: missing EU names or a budget under the minimum. */
export function createAdSetProblem(args: CreateAdSetArgs | null): string | null {
  if (!args) return null
  const eu = euProblem(args)
  if (eu) return eu
  if (args.conversionPixelMismatch)
    return "The custom conversion counts events from another pixel. Choose that pixel, or decline and ask the agent."
  if (
    args.budget?.kind === "daily" &&
    args.minimum &&
    Number(args.budget.amount) < Number(args.minimum)
  )
    return `The minimum daily budget for this goal is ${budgetMoney(args.minimum, args.currency)}.`
  return null
}

export function adSetPrompt(args: CreateAdSetArgs): string {
  return `Create the ad set ${args.name} in ${args.campaignName}${args.accountName ? `, in ${args.accountName}` : ""}.`
}

type AdSetOutcome = "created" | "failed" | "unverified"
const OUTCOMES: ReadonlySet<AdSetOutcome> = new Set(["created", "failed", "unverified"])

export type CreateAdSetResult = {
  accountId: string
  adSet: {
    name: string
    outcome: AdSetOutcome
    recovered: boolean
    verified: boolean
    adSetId: string | null
    message: string | null
    errorCode: string | null
  }
}

export function parseCreateAdSetResult(value: unknown): CreateAdSetResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["account_id"]) || !isRecord(value["ad_set"]))
    return null
  const adSet = value["ad_set"]
  if (!isNonEmptyString(adSet["name"]) || !isOneOf(OUTCOMES, adSet["outcome"])) return null
  return {
    accountId: value["account_id"],
    adSet: {
      name: adSet["name"],
      outcome: adSet["outcome"],
      recovered: adSet["recovered"] === true,
      verified: adSet["verified"] === true,
      adSetId: stringValue(adSet["adset_id"]),
      message: stringValue(adSet["message"]),
      errorCode: stringValue(adSet["error_code"]),
    },
  }
}
