// apps/web/src/integrations/google_ads/lib/campaign-goals.ts

import { humanizeKey } from "@/lib/format"
import { isRecord } from "@/lib/guards"

// A conversion goal by Google's category and origin tokens, such as PURCHASE and WEBSITE.
export type CampaignGoal = { category: string; origin: string }
// A goal the campaign can bid for, named by the server, and whether it bids now.
export type GoalOption = CampaignGoal & { biddable: boolean; name: string }

// The campaign bids for the account's goals, not a list of its own.
export const ACCOUNT_GOALS = "account"
// The campaign bids for a custom goal, which the card can't change.
export const CUSTOM_GOAL = "custom"

export const GOALS_RELEARN = "Bidding relearns what to aim for when a campaign's goals change."

function byCategoryThenOrigin(a: CampaignGoal, b: CampaignGoal): number {
  if (a.category !== b.category) return a.category < b.category ? -1 : 1
  return a.origin < b.origin ? -1 : a.origin > b.origin ? 1 : 0
}

/** Reads a list of goals, each once, in the order the server keeps them; null when it isn't one. */
export function parseGoals(value: unknown): CampaignGoal[] | null {
  if (!Array.isArray(value)) return null
  const goals = new Map<string, CampaignGoal>()
  for (const item of value) {
    if (!isRecord(item)) return null
    const { category, origin } = item
    if (typeof category !== "string" || typeof origin !== "string") return null
    goals.set(`${category}~${origin}`, { category, origin })
  }
  return [...goals.values()].sort(byCategoryThenOrigin)
}

export function parseGoalOptions(value: unknown): GoalOption[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item)) return []
    const { category, name, origin } = item
    return typeof category === "string" && typeof origin === "string" && typeof name === "string"
      ? [{ biddable: item["biddable"] === true, category, name, origin }]
      : []
  })
}

/** A goal in words, such as "Purchase from website", as the server names it. */
export function goalName(goal: CampaignGoal): string {
  return humanizeKey(`${goal.category} from ${goal.origin}`)
}

export function goalsText(value: string | readonly CampaignGoal[]): string {
  if (value === ACCOUNT_GOALS) return "Account goals"
  if (typeof value === "string") return "Custom goal"
  if (value.length === 0) return "No goals"
  const names = value.map(goalName)
  return value.length === 1 ? `${names[0] ?? ""} only` : names.join(", ")
}

/** Why the server refuses the goals, or null. */
export function goalsProblem(value: readonly CampaignGoal[]): string | null {
  return value.length === 0
    ? "Choose at least one conversion goal, or use the account's goals."
    : null
}

export function hasGoal(goals: readonly CampaignGoal[], goal: CampaignGoal): boolean {
  return goals.some((item) => item.category === goal.category && item.origin === goal.origin)
}

/** The goals with one added or taken out, in the order the server keeps them. */
export function toggledGoals(goals: readonly CampaignGoal[], goal: CampaignGoal): CampaignGoal[] {
  const { category, origin } = goal
  const rest = goals.filter((item) => item.category !== category || item.origin !== origin)
  return rest.length < goals.length
    ? rest
    : [...goals, { category, origin }].sort(byCategoryThenOrigin)
}
