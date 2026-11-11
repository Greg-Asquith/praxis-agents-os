// apps/web/src/integrations/google_ads/lib/remove-objects.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import { groupedByParent } from "@/integrations/ads/lib/parent-rows"
import {
  type GoogleAdsApprovalAccount,
  parseCheckedEntries,
} from "@/integrations/google_ads/lib/accounts"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { googleAdsId, textOrNull } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type RemovalKind =
  | "campaign"
  | "ad_group"
  | "ad"
  | "keyword"
  | "asset_group"
  | "budget"
  | "label"
  | "bidding_strategy"
  | "negative_keyword_list"

export const REMOVAL_KINDS: readonly RemovalKind[] = [
  "campaign",
  "ad_group",
  "ad",
  "keyword",
  "asset_group",
  "budget",
  "label",
  "bidding_strategy",
  "negative_keyword_list",
]

export const REMOVAL_KIND_TITLES: Record<RemovalKind, { one: string; many: string }> = {
  campaign: { one: "Campaign", many: "Campaigns" },
  ad_group: { one: "Ad Group", many: "Ad Groups" },
  ad: { one: "Ad", many: "Ads" },
  keyword: { one: "Keyword", many: "Keywords" },
  asset_group: { one: "Asset Group", many: "Asset Groups" },
  budget: { one: "Shared Budget", many: "Shared Budgets" },
  label: { one: "Label", many: "Labels" },
  bidding_strategy: { one: "Bid Strategy", many: "Bid Strategies" },
  negative_keyword_list: { one: "Negative Keyword List", many: "Negative Keyword Lists" },
}

// What each kind's line in the change summary says its removals do.
const KIND_DETAILS: Partial<Record<RemovalKind, string>> = {
  budget: "no campaign uses them",
  bidding_strategy: "no campaign uses them",
  label: "taken off every item",
  negative_keyword_list: "taken off every campaign",
}

// The reference's id fields, and the resource name built from them.
const KIND_IDS: Record<RemovalKind, { ids: readonly string[]; path: string }> = {
  campaign: { ids: ["campaign_id"], path: "campaigns" },
  ad_group: { ids: ["ad_group_id"], path: "adGroups" },
  ad: { ids: ["ad_group_id", "ad_id"], path: "adGroupAds" },
  keyword: { ids: ["ad_group_id", "criterion_id"], path: "adGroupCriteria" },
  asset_group: { ids: ["asset_group_id"], path: "assetGroups" },
  budget: { ids: ["budget_id"], path: "campaignBudgets" },
  label: { ids: ["label_id"], path: "labels" },
  bidding_strategy: { ids: ["bidding_strategy_id"], path: "biddingStrategies" },
  negative_keyword_list: { ids: ["shared_set_id"], path: "sharedSets" },
}

const DEPENDANT_KEYS = ["campaigns", "ad_groups", "ads", "keywords"] as const
type DependantKey = (typeof DEPENDANT_KEYS)[number]
const DEPENDANT_NOUNS: Record<DependantKey, string> = {
  ad_groups: "ad group",
  ads: "ad",
  campaigns: "campaign",
  keywords: "keyword",
}

export type RemovalDependants = Record<DependantKey, number> & { truncated: boolean }

type RemovalItem = {
  // From the reference, which names it for campaigns and usually for what sits in one.
  campaignId: string | null
  customerId: string
  // The entry as received, so cancelling one keeps every reference field of the rest.
  entry: Record<string, unknown>
  key: string
  kind: RemovalKind
  label: string
}

type RemovalCheck =
  | { unavailable: true }
  | {
      unavailable: false
      adGroupName: string | null
      // The campaign the item sits in, or is; null outside campaigns.
      campaignId: string | null
      campaignName: string | null
      dependants: RemovalDependants
      name: string
      problem: string | null
      // Null when Google Ads no longer has the item.
      status: string | null
    }

export type RemoveObjectsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  checks: Map<string, RemovalCheck>
  items: RemovalItem[]
}

export type RemovalRow = {
  alreadyRemoved: boolean
  // What the removal takes with it, or for a label what it comes off; empty when nothing.
  alsoRemoves: string
  campaignId: string | null
  campaignName: string | null
  cancelled: boolean
  dependants: RemovalDependants
  groupName: string | null
  item: RemovalItem
  key: string
  name: string
  // Blocks approval while set.
  problem: string | null
}

export type RemovalCounts = {
  byKind: Record<RemovalKind, number>
  dependants: RemovalDependants
  problems: number
  remove: number
  total: number
}

const UNAVAILABLE_PROBLEM =
  "Google Ads couldn't check this item. Ask the agent to prepare the removal again."
const NO_DEPENDANTS: RemovalDependants = {
  ad_groups: 0,
  ads: 0,
  campaigns: 0,
  keywords: 0,
  truncated: false,
}

function removalResourceName(
  kind: RemovalKind,
  customerId: string,
  reference: Record<string, unknown>
): string | null {
  const { ids, path } = KIND_IDS[kind]
  const values = ids.map((name) => googleAdsId(reference[name]))
  return values.every((value) => value !== null)
    ? `customers/${customerId}/${path}/${values.join("~")}`
    : null
}

function isRemovalKind(value: unknown): value is RemovalKind {
  return typeof value === "string" && Object.hasOwn(KIND_IDS, value)
}

export function parseDependants(value: unknown): RemovalDependants {
  if (!isRecord(value)) return NO_DEPENDANTS
  const count = (key: DependantKey) => {
    const raw = value[key]
    return typeof raw === "number" && Number.isInteger(raw) && raw > 0 ? raw : 0
  }
  return {
    ad_groups: count("ad_groups"),
    ads: count("ads"),
    campaigns: count("campaigns"),
    keywords: count("keywords"),
    truncated: value["truncated"] === true,
  }
}

function parseCheck(value: unknown): RemovalCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const name = textOrNull(value["name"])
  if (name === null) return { unavailable: true }
  return {
    unavailable: false,
    adGroupName: textOrNull(value["ad_group_name"]),
    campaignId: googleAdsId(value["campaign_id"]),
    campaignName: textOrNull(value["campaign_name"]),
    dependants: parseDependants(value["dependants"]),
    name,
    problem: textOrNull(value["problem"]),
    status: textOrNull(value["status"]),
  }
}

function parseItem(value: unknown): RemovalItem | null {
  if (!isRecord(value) || !isRemovalKind(value["kind"])) return null
  const kind = value["kind"]
  const reference = value[kind]
  if (!isRecord(reference)) return null
  const customerId = googleAdsId(reference["customer_id"])
  const key = customerId === null ? null : removalResourceName(kind, customerId, reference)
  if (customerId === null || key === null) return null
  return {
    campaignId: googleAdsId(reference["campaign_id"]),
    customerId,
    entry: value,
    key,
    kind,
    label: textOrNull(reference["label"]) ?? key,
  }
}

/** Reads `items` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseRemoveObjectsArgs(value: unknown): RemoveObjectsArgs | null {
  const parsed = parseCheckedEntries(value, "items", parseItem, parseCheck)
  return parsed && { accounts: parsed.accounts, checks: parsed.checks, items: parsed.entries }
}

/** Counts such as "92 keywords, 6 ads", with "+" on counts that stopped at Google's read limit. */
function dependantsText(dependants: RemovalDependants): string {
  return DEPENDANT_KEYS.filter((key) => dependants[key] > 0)
    .map((key) => {
      const count = dependants[key]
      const noun = `${DEPENDANT_NOUNS[key]}${count === 1 ? "" : "s"}`
      return `${count.toLocaleString("en-GB")}${dependants.truncated ? "+" : ""} ${noun}`
    })
    .join(", ")
}

export function alsoRemovesText(kind: RemovalKind, dependants: RemovalDependants): string {
  if (kind === "negative_keyword_list") {
    // Its keywords go with it; the campaigns only lose the list.
    const keywords = dependantsText({ ...NO_DEPENDANTS, keywords: dependants.keywords })
    const campaigns = dependantsText({ ...dependants, keywords: 0 })
    return [keywords, campaigns ? `comes off ${campaigns}` : ""].filter(Boolean).join("; ")
  }
  const text = dependantsText(dependants)
  if (!text) return ""
  if (kind === "budget") return `Funds ${text}`
  if (kind === "bidding_strategy") return `Used by ${text}`
  return kind === "label" ? `Comes off ${text}` : text
}

/** Every proposed item once, cancelled when the current edit no longer holds it. */
export function removalRows(proposed: RemoveObjectsArgs, current: RemoveObjectsArgs): RemovalRow[] {
  const kept = new Set(current.items.map((item) => item.key))
  return proposed.items.map((item) => {
    const check = proposed.checks.get(item.key) ?? { unavailable: true as const }
    const dependants = check.unavailable ? NO_DEPENDANTS : check.dependants
    return {
      alreadyRemoved: !check.unavailable && check.status === "REMOVED",
      alsoRemoves: alsoRemovesText(item.kind, dependants),
      campaignId: (check.unavailable ? null : check.campaignId) ?? item.campaignId,
      campaignName: check.unavailable ? null : check.campaignName,
      cancelled: !kept.has(item.key),
      dependants,
      groupName: check.unavailable ? null : check.adGroupName,
      item,
      key: item.key,
      name: check.unavailable ? item.label : check.name,
      problem: check.unavailable ? UNAVAILABLE_PROBLEM : check.problem,
    }
  })
}

export function removalCounts(rows: readonly RemovalRow[]): RemovalCounts {
  const live = rows.filter((row) => !row.cancelled)
  const byKind = Object.fromEntries(REMOVAL_KINDS.map((kind) => [kind, 0])) as Record<
    RemovalKind,
    number
  >
  const dependants = { ...NO_DEPENDANTS }
  for (const row of live) {
    byKind[row.item.kind] += 1
    // A label's uses aren't removed with it, so they don't count towards what goes.
    if (row.item.kind !== "campaign" && row.item.kind !== "ad_group") continue
    for (const key of DEPENDANT_KEYS) dependants[key] += row.dependants[key]
    dependants.truncated ||= row.dependants.truncated
  }
  const problems = live.filter((row) => row.problem !== null).length
  return {
    byKind,
    dependants,
    problems,
    remove: live.filter((row) => !row.alreadyRemoved && row.problem === null).length,
    total: live.length,
  }
}

export function kindDetail(kind: RemovalKind, rows: readonly RemovalRow[]): string | undefined {
  if (kind !== "campaign" && kind !== "ad_group") return KIND_DETAILS[kind]
  const counts = removalCounts(rows.filter((row) => row.item.kind === kind)).dependants
  const text = dependantsText(counts)
  return text ? `takes ${text} with them` : undefined
}

// Shared budgets, labels, strategies, and lists sit outside every campaign.
const SHARED_KINDS: ReadonlySet<RemovalKind> = new Set([
  "budget",
  "label",
  "bidding_strategy",
  "negative_keyword_list",
])
const OUTSIDE_CAMPAIGNS = "outside"
// An item Google couldn't read, whose reference doesn't name its campaign.
const UNKNOWN_CAMPAIGN = "unknown"

/** The campaign row a removal sits under; a removed campaign is its own. */
export function removalParentKey(row: RemovalRow): string {
  const campaign = SHARED_KINDS.has(row.item.kind)
    ? OUTSIDE_CAMPAIGNS
    : (row.campaignId ?? UNKNOWN_CAMPAIGN)
  return `${row.item.customerId}:${campaign}`
}

function parentName(key: string, items: readonly RemovalRow[]): string {
  if (key.endsWith(`:${OUTSIDE_CAMPAIGNS}`)) return "Not in a Campaign"
  if (key.endsWith(`:${UNKNOWN_CAMPAIGN}`)) return "Couldn't Check"
  const removed = items.find((row) => row.item.kind === "campaign")
  return removed?.name ?? items.find((row) => row.campaignName)?.campaignName ?? "Campaign"
}

/** One row per campaign the removals sit in, in the order its items first appear. */
export function removalParents(
  rows: readonly RemovalRow[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>,
  showAccount: boolean
): ParentRow[] {
  return groupedByParent(rows, removalParentKey).map(({ items, key, live }) => {
    const first = items[0]
    return {
      cancelled: live.length === 0,
      context: showAccount && first ? (accounts.get(first.item.customerId)?.label ?? null) : null,
      key,
      name: parentName(key, items),
      problems: live.filter((row) => row.problem !== null).length,
      values: {
        also: dependantsText(removalCounts(live).dependants) || "—",
        items: live.length,
      },
    }
  })
}

/** The `items` value with the given rows cancelled or restored. */
export function editedItems(
  rows: readonly RemovalRow[],
  keys: ReadonlySet<string>,
  cancelled: boolean
): Record<string, unknown>[] {
  return rows
    .filter((row) => (keys.has(row.key) ? !cancelled : !row.cancelled))
    .map((row) => row.item.entry)
}

/** Why the request can't be approved yet, or null. */
export function removalBlock(args: RemoveObjectsArgs | null): string | null {
  if (args === null) return null
  const counts = removalCounts(removalRows(args, args))
  if (counts.total === 0) return "Every removal is cancelled. Decline this request, or undo one."
  if (counts.problems > 0)
    return `Cancel ${approvalCountLine(counts.problems, "change")} that can't go ahead to continue.`
  if (counts.remove === 0) return "These items are already removed."
  return null
}

export function removalAccountNames(
  rows: readonly RemovalRow[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>
): string[] {
  const ids = new Set(rows.filter((row) => !row.cancelled).map((row) => row.item.customerId))
  return [...ids].map((id) => accounts.get(id)?.label ?? "Google Ads account")
}

export function removalPrompt(counts: RemovalCounts, accountNames: readonly string[]): string {
  if (counts.remove === 0) return "Nothing is left to remove."
  const where =
    accountNames.length === 1 ? accountNames[0] : `${String(accountNames.length)} accounts`
  return `Remove ${approvalCountLine(counts.remove, "item")} from ${where ?? "Google Ads"}.`
}

export function removalApproveLabel(counts: RemovalCounts): string {
  return counts.remove === 0
    ? "Remove Items"
    : `Remove ${String(counts.remove)} ${counts.remove === 1 ? "Item" : "Items"}`
}

export function removalBannerDetail(counts: RemovalCounts): string {
  const taken = dependantsText(counts.dependants)
  return [
    approvalCountLine(counts.total, "item"),
    taken ? `also removes ${taken} inside them` : null,
  ]
    .filter((part) => part !== null)
    .join(" · ")
}

export function removalDetails(args: RemoveObjectsArgs | null): FanOutDetail[] {
  if (args === null) return []
  const counts = removalCounts(removalRows(args, args))
  return REMOVAL_KINDS.filter((kind) => counts.byKind[kind] > 0).map((kind) => ({
    label: REMOVAL_KIND_TITLES[kind].many,
    value: String(counts.byKind[kind]),
  }))
}
