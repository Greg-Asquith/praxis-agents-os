// apps/web/src/integrations/google_ads/lib/research-keywords.ts

import type { DataRow, DataTableTab } from "@/components/ui/data-table"
import { collapseSpaces } from "@/integrations/ads/lib/keyword-notation"
import { formatGoogleAdsAccountId } from "@/lib/format"
import { isRecord, isStringArray } from "@/lib/guards"

const COMPETITION = new Set(["LOW", "MEDIUM", "HIGH"])
const MATCH_TYPES = new Set(["EXACT", "PHRASE", "BROAD"])
// More themes than this become Other Themes, so the tabs fit on one line.
const MAX_THEME_TABS = 3
// One ad group's worth, and short enough to send as one turn.
export const MAX_BUILD_KEYWORDS = 100

export type KeywordIdea = {
  adGroupId: string | null
  avgMonthlySearches: number | null
  competition: string | null
  highBid: string | null
  lowBid: string | null
  matchType: string | null
  requested: boolean
  text: string
  themes: string[]
  trend: number[]
}

type Place = { key: string; name: string }

export type KeywordResearchResult = {
  accountId: string
  adGroups: { id: string; name: string; usable: boolean }[]
  currency: string
  ideas: KeywordIdea[]
  language: Place | null
  locations: Place[]
  totalIdeas: number
  truncated: boolean
}

function nullableString(value: unknown, allowed?: Set<string>): string | null | undefined {
  if (value === null || value === undefined) return null
  if (typeof value !== "string" || (allowed && !allowed.has(value))) return undefined
  return value
}

function parseIdea(value: unknown): KeywordIdea | null {
  if (!isRecord(value) || typeof value["text"] !== "string") return null
  const searches = value["avg_monthly_searches"]
  const trend: unknown[] = Array.isArray(value["trend"]) ? value["trend"] : []
  const themes = value["themes"] ?? []
  const fields = {
    adGroupId: nullableString(value["ad_group_id"]),
    competition: nullableString(value["competition"], COMPETITION),
    highBid: nullableString(value["high_bid"]),
    lowBid: nullableString(value["low_bid"]),
    matchType: nullableString(value["match_type"], MATCH_TYPES),
  }
  if (
    Object.values(fields).some((field) => field === undefined) ||
    (searches !== null && searches !== undefined && typeof searches !== "number") ||
    !trend.every((month) => typeof month === "number" && Number.isFinite(month)) ||
    !isStringArray(themes)
  )
    return null
  return {
    adGroupId: fields.adGroupId ?? null,
    avgMonthlySearches: typeof searches === "number" ? searches : null,
    competition: fields.competition ?? null,
    highBid: fields.highBid ?? null,
    lowBid: fields.lowBid ?? null,
    matchType: fields.matchType ?? null,
    requested: value["requested"] === true,
    text: value["text"],
    themes,
    trend: trend.filter((month) => typeof month === "number"),
  }
}

function parsePlace(value: unknown): Place | null {
  return isRecord(value) && typeof value["key"] === "string" && typeof value["name"] === "string"
    ? { key: value["key"], name: value["name"] }
    : null
}

function parseAdGroup(value: unknown): KeywordResearchResult["adGroups"][number] | null {
  return isRecord(value) &&
    typeof value["ad_group_id"] === "string" &&
    typeof value["name"] === "string"
    ? { id: value["ad_group_id"], name: value["name"], usable: value["usable"] !== false }
    : null
}

function parseAll<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null
  const items = value.map(parse)
  const parsed = items.filter((item) => item !== null)
  return parsed.length === items.length ? parsed : null
}

export function parseKeywordResearch(value: unknown): KeywordResearchResult | null {
  if (
    !isRecord(value) ||
    typeof value["account_id"] !== "string" ||
    typeof value["currency"] !== "string"
  )
    return null
  const ideas = parseAll(value["ideas"], parseIdea)
  const locations = parseAll(value["locations"], parsePlace)
  const adGroups = parseAll(value["ad_groups"] ?? [], parseAdGroup)
  const language = value["language"] === null ? null : parsePlace(value["language"])
  if (!ideas || !locations || !adGroups || (value["language"] !== null && !language)) return null
  const total = value["total_ideas"]
  return {
    accountId: value["account_id"],
    adGroups,
    currency: value["currency"],
    ideas,
    language,
    locations,
    totalIdeas: typeof total === "number" ? total : ideas.length,
    truncated: value["truncated"] === true,
  }
}

/** The most common themes as tabs, then Other Themes for rows in none of them. */
export function themeTabs(ideas: readonly KeywordIdea[]): DataTableTab[] {
  const counts = new Map<string, number>()
  for (const idea of ideas) {
    for (const theme of idea.themes) counts.set(theme, (counts.get(theme) ?? 0) + 1)
  }
  const top = [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, MAX_THEME_TABS)
    .map(([theme]) => theme)
  if (top.length === 0) return []
  const themesOf = (row: DataRow): string[] => (isStringArray(row["themes"]) ? row["themes"] : [])
  return [
    { id: "all", label: "All", match: () => true },
    ...top.map((theme) => ({
      id: `theme:${theme}`,
      label: theme,
      match: (row: DataRow) => themesOf(row).includes(theme),
    })),
    {
      hideWhenEmpty: true,
      id: "other",
      label: "Other Themes",
      match: (row: DataRow) => !themesOf(row).some((theme) => top.includes(theme)),
    },
  ]
}

/** What the card sends as the operator's own turn to build an ad group from chosen rows.

Carries only Google's keyword text and match types, never names the agent supplied.
 */
export function buildAdGroupInstruction(
  result: KeywordResearchResult,
  keywords: readonly KeywordIdea[]
): string {
  const places = [
    result.locations.map((place) => place.name).join(", ") || "every location",
    result.language?.name ?? "every language",
  ].join(", ")
  return [
    `Build one new Search ad group in Google Ads account ${formatGoogleAdsAccountId(result.accountId)} ` +
      `from these ${String(keywords.length)} researched keywords (${places}). ` +
      "Ask me which campaign it goes in and which match types to use if I haven't said.",
    ...keywords.map(
      (idea) =>
        `- ${collapseSpaces(idea.text)}` +
        (idea.matchType ? ` (Google suggests ${idea.matchType.toLowerCase()} match)` : "")
    ),
  ].join("\n")
}
