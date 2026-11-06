// apps/web/src/integrations/meta_ads/lib/campaign-edits.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { budgetMoney, isBudgetAmount } from "@/integrations/meta_ads/lib/budget-change"
import { bidAmountTitle, bidLabel } from "@/integrations/meta_ads/lib/create-ad-set"
import { AMOUNT_FORMAT } from "@/integrations/meta_ads/lib/create-campaign"
import { isNonEmptyString, isOneOf, isRecord, isStringArray } from "@/lib/guards"

export type CampaignSettingKey = "name" | "spend_limit" | "bid_strategy" | "share_between_ad_sets"
type CheckedKey = CampaignSettingKey | "ad_set_bids"

// In the order the tool lists them, with the Create Campaign card's titles.
const SETTINGS: readonly { key: CampaignSettingKey; title: string }[] = [
  { key: "name", title: "Name" },
  { key: "spend_limit", title: "Spending Limit" },
  { key: "bid_strategy", title: "Bid Strategy" },
  { key: "share_between_ad_sets", title: "Share Budget between Ad Sets" },
]
const TITLES = new Map(SETTINGS.map((setting) => [setting.key, setting.title]))
const CHECKED_KEYS: ReadonlySet<CheckedKey> = new Set([
  ...SETTINGS.map((setting) => setting.key),
  "ad_set_bids",
])
// Strategies that need a bid on every ad set.
const BID_STRATEGIES: ReadonlySet<string> = new Set(["bid_cap", "cost_per_result_goal"])

type CampaignCheck = {
  currency: string | null
  // Each setting now; null means not set. Ad set bids are JSON by ad set ID.
  before: Partial<Record<CheckedKey, string | null>>
  // The values the problems were found for.
  requested: Partial<Record<CheckedKey, string | null>>
  problems: string[]
  // Effects that can cost results for a while.
  warnings: string[]
  notes: string[]
  // The campaign's ad sets that aren't deleted, with their bids now.
  adSets: { id: string; name: string; bid: string | null }[]
  // What the campaign has spent over its life, read for a spending limit change.
  spent: string | null
  unavailable: boolean
}

/** One setting's new value as text. */
export type CampaignSetting = { key: CampaignSettingKey; value: string }
/** One ad set's new bid. */
export type AdSetBid = { id: string; value: string }

export type CampaignEdit = {
  id: string
  accountId: string
  name: string
  settings: CampaignSetting[]
  bids: AdSetBid[]
  check: CampaignCheck | null
  // The entry as sent, so edits keep the parts the card doesn't change.
  raw: Record<string, unknown>
}

export type CampaignEditArgs = { edits: CampaignEdit[] }

/** One proposed campaign, kept when the operator drops it so it can come back. */
export type CampaignEditRow = { edit: CampaignEdit; proposed: CampaignEdit; included: boolean }

export type CampaignChange =
  | { included: boolean }
  | { key: CampaignSettingKey; value: string }
  | { bid: string; value: string }

export function campaignSettingTitle(key: CampaignSettingKey): string {
  return TITLES.get(key) ?? key
}

/** The bid strategy the campaign has once this edit applies. */
export function campaignStrategy(edit: CampaignEdit): string | null {
  const requested = edit.settings.find((setting) => setting.key === "bid_strategy")
  return requested?.value ?? edit.check?.before.bid_strategy ?? null
}

/** The heading over the ad set bids, named after the strategy that needs them. */
export function bidsTitle(strategy: string | null): string {
  return strategy === "bid_cap" || strategy === "cost_per_result_goal"
    ? bidAmountTitle(strategy)
    : "Ad Set Bid"
}

/** One setting's value now and after, such as "£800.00 → £500.00", for its closed row. */
export function changeSummary(edit: CampaignEdit, setting: CampaignSetting): string {
  const currency = edit.check?.currency ?? null
  const after = formatCampaignValue(setting.key, setting.value, currency)
  const before = edit.check?.before[setting.key]
  return before === undefined
    ? after
    : `${formatCampaignValue(setting.key, before, currency)} → ${after}`
}

export function parseCampaignEditArgs(value: unknown): CampaignEditArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const checks = isRecord(value["_checks"]) ? value["_checks"] : {}
  const edits: CampaignEdit[] = []
  for (const item of value["changes"]) {
    const edit = parseEdit(item, checks)
    if (edit === null) return null
    edits.push(edit)
  }
  return { edits }
}

function parseEdit(value: unknown, checks: Record<string, unknown>): CampaignEdit | null {
  if (!isRecord(value) || !isRecord(value["campaign"])) return null
  const reference = value["campaign"]
  const id = reference["campaign_id"]
  if (!isNonEmptyString(id)) return null
  const settings = SETTINGS.flatMap(({ key }): CampaignSetting[] => {
    const item = value[key]
    if (key === "share_between_ad_sets") return item === false ? [{ key, value: "false" }] : []
    return typeof item === "string" ? [{ key, value: item }] : []
  })
  const entries: unknown[] = Array.isArray(value["ad_set_bids"]) ? value["ad_set_bids"] : []
  const bids: AdSetBid[] = []
  for (const item of entries) {
    if (!isRecord(item) || !isRecord(item["ad_set"])) return null
    const adSet = item["ad_set"]["adset_id"]
    const amount = item["bid_amount"]
    if (!isNonEmptyString(adSet) || typeof amount !== "string") return null
    bids.push({ id: adSet, value: amount })
  }
  return {
    id,
    accountId: typeof reference["account_id"] === "string" ? reference["account_id"] : "",
    name: isNonEmptyString(reference["label"]) ? reference["label"] : id,
    settings,
    bids,
    check: parseCheck(checks[id]),
    raw: value,
  }
}

function parseCheck(value: unknown): CampaignCheck | null {
  if (!isRecord(value)) return null
  return {
    currency: isNonEmptyString(value["currency"]) ? value["currency"] : null,
    before: checkedValues(value["before"]),
    requested: checkedValues(value["requested"]),
    problems: isStringArray(value["problems"]) ? value["problems"] : [],
    warnings: isStringArray(value["warnings"]) ? value["warnings"] : [],
    notes: isStringArray(value["notes"]) ? value["notes"] : [],
    adSets: Array.isArray(value["ad_sets"])
      ? value["ad_sets"].flatMap((item) =>
          isRecord(item) && isNonEmptyString(item["id"]) && typeof item["name"] === "string"
            ? [
                {
                  id: item["id"],
                  name: item["name"],
                  bid: typeof item["bid"] === "string" ? item["bid"] : null,
                },
              ]
            : []
        )
      : [],
    spent: isNonEmptyString(value["spent"]) ? value["spent"] : null,
    unavailable: value["unavailable"] === true,
  }
}

function checkedValues(value: unknown): Partial<Record<CheckedKey, string | null>> {
  if (!isRecord(value)) return {}
  const values: Partial<Record<CheckedKey, string | null>> = {}
  for (const [key, item] of Object.entries(value))
    if (isOneOf(CHECKED_KEYS, key) && (item === null || typeof item === "string"))
      values[key] = item
  return values
}

/** Bids by ad set ID from the server's JSON; an unreadable value reads as none. */
function bidMap(text: string | null | undefined): Record<string, string | null> {
  try {
    const value: unknown = JSON.parse(text ?? "{}")
    if (!isRecord(value)) return {}
    return Object.fromEntries(
      Object.entries(value).map(([key, bid]) => [key, typeof bid === "string" ? bid : null])
    )
  } catch {
    return {}
  }
}

/** True when the server checked these bids: the same ad sets, at the same amounts. */
function bidsMatch(checked: string | null | undefined, bids: readonly AdSetBid[]): boolean {
  const map = bidMap(checked)
  return (
    Object.keys(map).length === bids.length &&
    bids.every((bid) => map[bid.id] != null && Number(map[bid.id]) === Number(bid.value))
  )
}

/** True when the server's problems were found for exactly the values now on the card. */
function checkIsCurrent(edit: CampaignEdit): boolean {
  const check = edit.check
  if (check === null) return false
  const keys = Object.keys(check.requested).length
  const bidsChecked = "ad_set_bids" in check.requested
  return (
    keys === edit.settings.length + (edit.bids.length > 0 ? 1 : 0) &&
    bidsChecked === edit.bids.length > 0 &&
    (!bidsChecked || bidsMatch(check.requested.ad_set_bids, edit.bids)) &&
    edit.settings.every(
      (setting) =>
        setting.key in check.requested &&
        check.requested[setting.key] === (setting.value === "remove" ? null : setting.value)
    )
  )
}

export function campaignProblems(edit: CampaignEdit): string[] {
  return checkIsCurrent(edit) ? (edit.check?.problems ?? []) : []
}

export function campaignWarnings(edit: CampaignEdit): string[] {
  return checkIsCurrent(edit) ? (edit.check?.warnings ?? []) : []
}

/** Notes under a campaign; a note on values since edited could be wrong, so it says so. */
export function campaignNotes(edit: CampaignEdit): string[] {
  const check = edit.check
  if (check === null || check.unavailable)
    return ["This campaign couldn't be checked before approval. Meta checks it when you approve."]
  if (!checkIsCurrent(edit))
    return ["You changed these values, so Meta checks them again when you approve."]
  return check.notes
}

export function formatCampaignValue(
  key: CampaignSettingKey,
  value: string | null,
  currency: string | null
): string {
  if (key === "spend_limit")
    return value === null || value === "remove" ? "No limit" : budgetMoney(value, currency)
  if (key === "share_between_ad_sets") return value === "true" ? "On" : "Off"
  if (value === null) return "Not set"
  return key === "bid_strategy" ? bidLabel(value) : value
}

export function formatBid(value: string | null, currency: string | null): string {
  return value === null ? "Not set" : budgetMoney(value, currency)
}

/** The current bid of each ad set, and its name, for the bid list. */
export function adSetBidRows(
  edit: CampaignEdit
): (AdSetBid & { name: string; now: string | null })[] {
  const live = new Map(edit.check?.adSets.map((item) => [item.id, item]))
  return edit.bids.map((bid) => ({
    ...bid,
    name: live.get(bid.id)?.name ?? bid.id,
    now: live.get(bid.id)?.bid ?? null,
  }))
}

/** The new values on one line, for the campaign's closed row. */
export function campaignSummary(edit: CampaignEdit): string {
  const currency = edit.check?.currency ?? null
  const parts = edit.settings.map(
    (setting) =>
      `${campaignSettingTitle(setting.key)}: ${formatCampaignValue(setting.key, setting.value, currency)}`
  )
  if (edit.bids.length > 0) parts.push(`${String(edit.bids.length)} ad set bids`)
  return parts.join(" · ")
}

/** Why one value on the card can't be sent, or null. */
export function campaignSettingProblem(setting: CampaignSetting): string | null {
  const value = setting.value.trim()
  if (setting.key === "name") return value === "" ? "Enter a name." : null
  if (setting.key === "spend_limit" && value !== "remove")
    return isBudgetAmount(value) ? null : AMOUNT_FORMAT
  return null
}

export function bidProblem(bid: AdSetBid): string | null {
  return isBudgetAmount(bid.value.trim()) ? null : AMOUNT_FORMAT
}

/** Why the proposed changes can't be approved yet, or null. */
export function campaignEditProblem(args: CampaignEditArgs | null): string | null {
  if (args === null) return null
  if (args.edits.length === 0) return "Keep at least one campaign, or decline this request."
  if (
    args.edits.some(
      (edit) =>
        edit.settings.some((setting) => campaignSettingProblem(setting)) ||
        edit.bids.some((bid) => bidProblem(bid))
    )
  )
    return "Correct the highlighted values before approving."
  if (args.edits.some((edit) => campaignProblems(edit).length > 0))
    return "Change the campaigns Meta won't accept or switch them off, or decline this request."
  return null
}

/** The proposed campaigns with the ones the operator dropped, in the proposed order. */
export function campaignEditRows(
  proposed: CampaignEditArgs,
  current: CampaignEditArgs
): CampaignEditRow[] {
  const kept = new Map(current.edits.map((edit) => [edit.id, edit]))
  return proposed.edits.map((edit) => {
    const edited = kept.get(edit.id)
    return { edit: edited ?? edit, proposed: edit, included: edited !== undefined }
  })
}

/** The `changes` argument after one edit to one campaign. */
export function editCampaigns(
  rows: readonly CampaignEditRow[],
  id: string,
  change: CampaignChange
): Record<string, unknown>[] {
  return rows.flatMap((row) => {
    const same = row.edit.id === id
    const included = same && "included" in change ? change.included : row.included
    if (!included) return []
    if (!same || "included" in change) return [row.edit.raw]
    if ("bid" in change)
      return [{ ...row.edit.raw, ad_set_bids: bidEntries(row.edit.raw, change.bid, change.value) }]
    if (change.key !== "bid_strategy") return [{ ...row.edit.raw, [change.key]: change.value }]
    // Only bid caps and cost goals take ad set bids; switching back restores the proposed ones.
    const rest = Object.fromEntries(
      Object.entries(row.edit.raw).filter(([key]) => key !== "ad_set_bids")
    )
    const bids = row.edit.raw["ad_set_bids"] ?? row.proposed.raw["ad_set_bids"]
    return [
      BID_STRATEGIES.has(change.value) && bids !== undefined
        ? { ...rest, bid_strategy: change.value, ad_set_bids: bids }
        : { ...rest, bid_strategy: change.value },
    ]
  })
}

function bidEntries(raw: Record<string, unknown>, id: string, value: string): unknown[] {
  const entries: unknown[] = Array.isArray(raw["ad_set_bids"]) ? raw["ad_set_bids"] : []
  return entries.map((entry) =>
    isRecord(entry) && isRecord(entry["ad_set"]) && entry["ad_set"]["adset_id"] === id
      ? { ...entry, bid_amount: value }
      : entry
  )
}

export function campaignEditDetails(args: CampaignEditArgs | null): FanOutDetail[] {
  if (args === null) return []
  return [{ label: "Campaigns", value: String(args.edits.length) }]
}

// Result models

type EditOutcomeToken = "updated" | "already_set" | "failed" | "unverified"
const OUTCOMES: ReadonlySet<EditOutcomeToken> = new Set([
  "updated",
  "already_set",
  "failed",
  "unverified",
])

type SettingResult = {
  key: CampaignSettingKey
  before: string | null
  after: string | null
}

type BidResult = { id: string; name: string; before: string | null; after: string | null }

type CampaignEditOutcome = {
  id: string
  name: string
  changes: SettingResult[]
  bids: BidResult[]
  outcome: EditOutcomeToken
  errorCode: string | null
  message: string | null
}

export type CampaignEditResult = {
  accountId: string
  currency: string
  campaigns: CampaignEditOutcome[]
}

const RESULT_KEYS: ReadonlySet<CampaignSettingKey> = new Set(SETTINGS.map((item) => item.key))

export function parseCampaignEditResult(value: unknown): CampaignEditResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !isNonEmptyString(value["currency"]) ||
    !Array.isArray(value["campaigns"])
  )
    return null
  const campaigns: CampaignEditOutcome[] = []
  for (const item of value["campaigns"]) {
    const row = parseOutcome(item)
    if (row === null) return null
    campaigns.push(row)
  }
  return { accountId: value["account_id"], currency: value["currency"], campaigns }
}

function parseOutcome(value: unknown): CampaignEditOutcome | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["campaign_id"]) ||
    !isOneOf(OUTCOMES, value["outcome"]) ||
    !Array.isArray(value["changes"])
  )
    return null
  const changes: SettingResult[] = []
  for (const item of value["changes"]) {
    if (!isRecord(item) || !isOneOf(RESULT_KEYS, item["setting"])) return null
    changes.push({ key: item["setting"], before: text(item, "before"), after: text(item, "after") })
  }
  const bids = (Array.isArray(value["ad_set_bids"]) ? value["ad_set_bids"] : []).flatMap((item) =>
    isRecord(item) && isNonEmptyString(item["adset_id"])
      ? [
          {
            id: item["adset_id"],
            name: isNonEmptyString(item["name"]) ? item["name"] : item["adset_id"],
            before: text(item, "before"),
            after: text(item, "after"),
          },
        ]
      : []
  )
  return {
    id: value["campaign_id"],
    name: isNonEmptyString(value["name"]) ? value["name"] : value["campaign_id"],
    changes,
    bids,
    outcome: value["outcome"],
    errorCode: text(value, "error_code"),
    message: text(value, "message"),
  }
}

function text(value: Record<string, unknown>, key: string): string | null {
  const item = value[key]
  return typeof item === "string" ? item : null
}
