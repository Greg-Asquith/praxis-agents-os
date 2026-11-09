// apps/web/src/integrations/google_ads/lib/campaign-bidding.ts

import {
  PAGE_LOCATION_LABELS,
  PAGE_LOCATIONS,
  STRATEGIES,
  STRATEGY_LABELS,
  type PageLocation,
  type Strategy,
} from "@/integrations/google_ads/lib/create-campaign"
import { formatCurrencyAmount, titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

// A campaign's bidding in the server's card terms: the strategy and only its own fields. Money is
// a canonical decimal string, target ROAS a ratio (3.5 is 350%), impression share a percentage.
// `TARGETS` changes targets on the current strategy; `TARGET_CPA`, `TARGET_ROAS`, and `OTHER`
// are only ever read from Google.
export type Bidding = {
  strategy: string
  location?: PageLocation | null
  max_cpc?: string | null
  portfolio?: string
  // The portfolio's reference as the request holds it; never compared.
  reference?: Record<string, unknown>
  share_percent?: number | null
  target_cpa?: string | null
  target_roas?: number | null
  type?: string | null
}

export type BiddingContext = {
  currency: string | null
  portfolios: ReadonlyMap<string, string>
}

export const STANDARD_STRATEGIES = STRATEGIES
export const PORTFOLIO = "PORTFOLIO"
export const TARGETS = "TARGETS"
export const TARGET_KEYS = ["target_cpa", "target_roas", "max_cpc"] as const
type TargetKey = (typeof TARGET_KEYS)[number]

// Which current strategies each target in a `TARGETS` request changes, as on the server.
const TARGET_STRATEGIES: Record<TargetKey, readonly string[]> = {
  max_cpc: ["MAXIMIZE_CLICKS", "TARGET_IMPRESSION_SHARE"],
  target_cpa: ["MAXIMIZE_CONVERSIONS", "TARGET_CPA"],
  target_roas: ["MAXIMIZE_CONVERSION_VALUE", "TARGET_ROAS"],
}

/** An amount as an input shows it: whole and one-decimal amounts get two places, "1" is "1.00". */
export function moneyInput(value: string): string {
  return /^\d+(\.\d)?$/.test(value) ? Number(value).toFixed(2) : value
}

/** A decimal amount as the server writes it: "18.00" is "18", "0.50" is "0.5". */
export function canonicalMoney(value: string): string {
  const trimmed = value.trim()
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return trimmed
  const [whole = "0", fraction = ""] = trimmed.split(".")
  const digits = whole.replace(/^0+(?=\d)/, "")
  const decimals = fraction.replace(/0+$/, "")
  return decimals ? `${digits}.${decimals}` : digits
}

function amount(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? canonicalMoney(value) : null
}

function ratio(value: unknown): number | null {
  const number = typeof value === "string" ? Number(value) : value
  return typeof number === "number" && Number.isFinite(number) && number > 0 ? number : null
}

function portfolioName(value: unknown): string | null {
  if (typeof value === "string" && value) return value
  if (!isRecord(value)) return null
  const customer = value["customer_id"]
  const id = value["bidding_strategy_id"]
  return typeof customer === "string" && typeof id === "string"
    ? `customers/${customer.replaceAll("-", "")}/biddingStrategies/${id}`
    : null
}

/** Reads bidding in card terms, from the server or from a request, in the server's key order. */
export function parseBidding(value: unknown): Bidding | null {
  if (!isRecord(value) || typeof value["strategy"] !== "string") return null
  const strategy = value["strategy"]
  if (strategy === PORTFOLIO) {
    const portfolio = portfolioName(value["portfolio"])
    if (portfolio === null) return null
    return isRecord(value["portfolio"])
      ? { strategy, portfolio, reference: value["portfolio"] }
      : { strategy, portfolio }
  }
  if (strategy === TARGETS) {
    const targets: Bidding = { strategy }
    if (amount(value["target_cpa"])) targets.target_cpa = amount(value["target_cpa"])
    if (ratio(value["target_roas"]) !== null) targets.target_roas = ratio(value["target_roas"])
    if (amount(value["max_cpc"])) targets.max_cpc = amount(value["max_cpc"])
    return targets
  }
  if (strategy === "MANUAL_CPC") return { strategy }
  if (strategy === "MAXIMIZE_CLICKS") return { strategy, max_cpc: amount(value["max_cpc"]) }
  if (strategy === "MAXIMIZE_CONVERSIONS" || strategy === "TARGET_CPA")
    return { strategy, target_cpa: amount(value["target_cpa"]) }
  if (strategy === "MAXIMIZE_CONVERSION_VALUE" || strategy === "TARGET_ROAS")
    return { strategy, target_roas: ratio(value["target_roas"]) }
  if (strategy === "TARGET_IMPRESSION_SHARE") {
    const location = value["location"]
    const share = ratio(value["share_percent"])
    return {
      strategy,
      location: (PAGE_LOCATIONS as readonly unknown[]).includes(location)
        ? (location as PageLocation)
        : null,
      share_percent: share === null ? null : Math.round(share),
      max_cpc: amount(value["max_cpc"]),
    }
  }
  return { strategy: "OTHER", type: typeof value["type"] === "string" ? value["type"] : null }
}

/** Bidding without the request-only reference, for comparing with what the server checked. */
export function comparableBidding(bidding: Bidding): Bidding {
  const { reference: _reference, ...rest } = bidding
  return rest
}

/** The bidding as the tool's `bidding` argument; null when a portfolio has no reference. */
export function biddingArgument(bidding: Bidding): Record<string, unknown> | null {
  if (bidding.strategy === PORTFOLIO)
    return bidding.reference ? { strategy: PORTFOLIO, portfolio: bidding.reference } : null
  return Object.fromEntries(
    Object.entries(comparableBidding(bidding)).filter(([, value]) => value != null)
  )
}

/** The strategy a request leaves the campaign on, and why it can't, as on the server. */
export function resolvedBidding(
  requested: Bidding,
  current: Bidding | undefined
): { bidding: Bidding; problem: string | null } {
  if (requested.strategy !== TARGETS || current === undefined)
    return { bidding: requested, problem: null }
  if (current.strategy === PORTFOLIO)
    return { bidding: current, problem: "This campaign uses a portfolio strategy." }
  const resolved: Bidding = { ...current }
  for (const key of TARGET_KEYS) {
    if (requested[key] === undefined) continue
    if (!TARGET_STRATEGIES[key].includes(current.strategy))
      return { bidding: current, problem: "The current strategy doesn't take this target." }
    Object.assign(resolved, { [key]: requested[key] })
  }
  return { bidding: resolved, problem: null }
}

/** Whether a change moves to another strategy, which restarts Google's learning. */
export function changesStrategy(requested: Bidding, current: Bidding): boolean {
  if (requested.strategy === PORTFOLIO || current.strategy === PORTFOLIO)
    return requested.portfolio !== current.portfolio
  return requested.strategy !== current.strategy
}

export function strategyLabel(strategy: string): string {
  if (strategy in STRATEGY_LABELS) return STRATEGY_LABELS[strategy as Strategy]
  if (strategy === "TARGET_CPA") return "Target CPA"
  if (strategy === "TARGET_ROAS") return "Target ROAS"
  if (strategy === PORTFOLIO) return "Portfolio Strategy"
  if (strategy === TARGETS) return "Change Targets Only"
  return titleCaseToken(strategy, "Other Strategy")
}

function money(value: string, context: BiddingContext): string {
  return context.currency ? formatCurrencyAmount(value, context.currency) : value
}

/** Turns a ratio into the percentage the card shows: 3.5 is "350". */
export function roasPercent(value: number): string {
  return String(Math.round(value * 10_000) / 100)
}

function targetParts(bidding: Bidding, context: BiddingContext): string[] {
  const parts: string[] = []
  if (bidding.target_cpa) parts.push(`Target CPA ${money(bidding.target_cpa, context)}`)
  if (bidding.target_roas != null) parts.push(`Target ROAS ${roasPercent(bidding.target_roas)}%`)
  if (bidding.strategy === "TARGET_IMPRESSION_SHARE") {
    const where = bidding.location ? PAGE_LOCATION_LABELS[bidding.location].toLowerCase() : null
    parts.push(`${String(bidding.share_percent ?? "?")}% ${where ?? ""}`.trim())
  }
  if (bidding.max_cpc) parts.push(`Up to ${money(bidding.max_cpc, context)} a click`)
  return parts
}

export function portfolioLabel(bidding: Bidding, context: BiddingContext): string {
  const known = bidding.portfolio ? context.portfolios.get(bidding.portfolio) : undefined
  const label = bidding.reference?.["label"]
  return known ?? (typeof label === "string" && label ? label : "Portfolio strategy")
}

/** Why the card can't send this bidding yet, or null. */
export function biddingProblem(bidding: Bidding): string | null {
  if (bidding.strategy !== "TARGET_IMPRESSION_SHARE") return null
  return bidding.location && bidding.share_percent != null && bidding.max_cpc
    ? null
    : "Target Impression Share needs where on the page, a share of searches, and a maximum click bid."
}

/** Bidding in the words the card uses, such as "Maximise Conversions · Target CPA £18.00". */
export function biddingText(bidding: Bidding, context: BiddingContext): string {
  if (bidding.strategy === PORTFOLIO) return `Portfolio: ${portfolioLabel(bidding, context)}`
  if (bidding.strategy === "OTHER") return strategyLabel(bidding.type ?? "OTHER")
  const parts = targetParts(bidding, context)
  if (bidding.strategy === TARGETS) return parts.join(" · ") || "No targets"
  return [strategyLabel(bidding.strategy), ...parts].join(" · ")
}

// The strategy that takes each target, for the fix offered when a target-only change can't apply.
const TARGET_HOMES: Record<TargetKey, Strategy> = {
  max_cpc: "MAXIMIZE_CLICKS",
  target_cpa: "MAXIMIZE_CONVERSIONS",
  target_roas: "MAXIMIZE_CONVERSION_VALUE",
}

export const TARGET_LABELS: Record<TargetKey, string> = {
  max_cpc: "Maximum Click Bid",
  target_cpa: "Target CPA",
  target_roas: "Target ROAS",
}

/** The strategy and targets the editor shows: a target-only change sits on the live strategy. */
export function shownBidding(value: Bidding, was: Bidding | undefined): Bidding {
  if (value.strategy !== TARGETS || was === undefined) return value
  return { ...value, strategy: was.strategy }
}

/** A change that keeps the requested target by moving to the strategy that takes it, or null. */
export function targetFix(value: Bidding, was: Bidding | undefined): Bidding | null {
  if (value.strategy !== TARGETS || resolvedBidding(value, was).problem === null) return null
  const key = TARGET_KEYS.find((item) => value[item] != null)
  return key ? parseBidding({ strategy: TARGET_HOMES[key], [key]: value[key] }) : null
}

/** What the strategy does, in a sentence the operator can check before approving. */
export function biddingSentence(bidding: Bidding, context: BiddingContext): string {
  const cpc = bidding.max_cpc ? `, paying up to ${money(bidding.max_cpc, context)} a click` : ""
  switch (bidding.strategy) {
    case "MANUAL_CPC":
      return "You set the bids: each ad group and keyword uses its own CPC bid."
    case "MAXIMIZE_CLICKS":
      return `Google bids to get as many clicks as it can within the budget${cpc}.`
    case "MAXIMIZE_CONVERSIONS":
    case "TARGET_CPA":
      return bidding.target_cpa
        ? `Google bids for as many conversions as it can at about ${money(bidding.target_cpa, context)} each.`
        : "Google bids to get as many conversions as it can within the budget."
    case "MAXIMIZE_CONVERSION_VALUE":
    case "TARGET_ROAS":
      return bidding.target_roas != null
        ? `Google bids for the most conversion value it can, aiming for ${roasPercent(bidding.target_roas)}% return on ad spend.`
        : "Google bids to get as much conversion value as it can within the budget."
    case "TARGET_IMPRESSION_SHARE": {
      const where = bidding.location
        ? PAGE_LOCATION_LABELS[bidding.location].toLowerCase()
        : "on the page"
      return `Google bids to show your ads on ${String(bidding.share_percent ?? "?")}% of searches, ${where}${cpc}.`
    }
    case PORTFOLIO:
      return `The campaign follows the ${portfolioLabel(bidding, context)} portfolio strategy, shared with other campaigns.`
    default:
      return ""
  }
}

/** The strategy's name on its own, such as "Maximise Clicks" or "Portfolio: Brand tCPA". */
export function biddingName(bidding: Bidding, context: BiddingContext): string {
  if (bidding.strategy === PORTFOLIO) return `Portfolio: ${portfolioLabel(bidding, context)}`
  return strategyLabel(bidding.strategy === "OTHER" ? (bidding.type ?? "OTHER") : bidding.strategy)
}

const NO_TARGET: Record<string, string> = {
  MANUAL_CPC: "Each ad group sets its own CPC bid",
  MAXIMIZE_CLICKS: "No maximum click bid",
  MAXIMIZE_CONVERSIONS: "No target CPA",
  MAXIMIZE_CONVERSION_VALUE: "No target ROAS",
}

/** The strategy's targets, such as "Target CPA £18.00", or what having none means. */
export function biddingDetail(bidding: Bidding, context: BiddingContext): string {
  return targetParts(bidding, context).join(" · ") || (NO_TARGET[bidding.strategy] ?? "")
}
