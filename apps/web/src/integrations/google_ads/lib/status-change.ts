// apps/web/src/integrations/google_ads/lib/status-change.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import { groupedByParent } from "@/integrations/ads/lib/parent-rows"
import {
  type GoogleAdsApprovalAccount,
  parseCheckedEntries,
} from "@/integrations/google_ads/lib/accounts"
import {
  applyChangesLabel,
  approvalCountLine,
  unavailableProblem,
} from "@/integrations/google_ads/lib/copy"
import { googleAdsId, textOrNull } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type StatusKind = "campaign" | "ad_group" | "ad" | "keyword" | "asset_group"
export type RequestedStatus = "ENABLED" | "PAUSED"
export type LiveStatus = RequestedStatus | "REMOVED"

export const STATUS_KIND_TITLES: Record<StatusKind, string> = {
  campaign: "Campaign",
  ad_group: "Ad Group",
  ad: "Ad",
  keyword: "Keyword",
  asset_group: "Asset Group",
}

// The reference's id fields, and the resource name built from them.
const KIND_IDS: Record<StatusKind, { ids: readonly string[]; path: string; join: string }> = {
  campaign: { ids: ["campaign_id"], path: "campaigns", join: "" },
  ad_group: { ids: ["ad_group_id"], path: "adGroups", join: "" },
  ad: { ids: ["ad_group_id", "ad_id"], path: "adGroupAds", join: "~" },
  keyword: { ids: ["ad_group_id", "criterion_id"], path: "adGroupCriteria", join: "~" },
  asset_group: { ids: ["asset_group_id"], path: "assetGroups", join: "" },
}

type StatusItem = {
  adGroupId: string | null
  campaignId: string
  customerId: string
  // The change as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  key: string
  kind: StatusKind
  label: string
  scopeLabel: string | null
  status: RequestedStatus
}

type StatusCheck =
  | { unavailable: true }
  | {
      unavailable: false
      adGroupName: string | null
      adGroupStatus: LiveStatus | null
      campaignName: string
      campaignStatus: LiveStatus | null
      problem: string | null
      requested: RequestedStatus
      status: LiveStatus | null
    }

export type StatusChangeArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  checks: Map<string, StatusCheck>
  items: StatusItem[]
}

type StatusChange = "turn_on" | "turn_off" | "already_set"

export type StatusRow = {
  // The campaign this item sits under, with whether it is on once this request runs.
  campaignName: string
  campaignOn: boolean | null
  cancelled: boolean
  change: StatusChange
  // Names the item's ad group for ads and keywords.
  groupName: string | null
  item: StatusItem
  key: string
  // Blocks approval while set.
  problem: string | null
  status: RequestedStatus
  was: LiveStatus | null
  // Set when turning the item on still shows no ads, with the reason.
  wontShow: string | null
}

export type StatusCounts = {
  alreadySet: number
  apply: number
  campaigns: number
  problems: number
  total: number
  turnOff: number
  turnOn: number
  wontShow: number
}

export type StatusPatch = { cancelled: boolean } | { status: RequestedStatus }

const UNAVAILABLE_PROBLEM = unavailableProblem("item")

export function statusResourceName(
  kind: StatusKind,
  customerId: string,
  reference: Record<string, unknown>
): string | null {
  const { ids, join, path } = KIND_IDS[kind]
  const values = ids.map((name) => googleAdsId(reference[name]))
  return values.every((value) => value !== null)
    ? `customers/${customerId}/${path}/${values.join(join)}`
    : null
}

function liveStatus(value: unknown): LiveStatus | null {
  return value === "ENABLED" || value === "PAUSED" || value === "REMOVED" ? value : null
}

function parseCheck(value: unknown): StatusCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const requested = value["requested"]
  const campaignName = textOrNull(value["campaign_name"])
  if ((requested !== "ENABLED" && requested !== "PAUSED") || campaignName === null)
    return { unavailable: true }
  return {
    unavailable: false,
    adGroupName: textOrNull(value["ad_group_name"]),
    adGroupStatus: liveStatus(value["ad_group_status"]),
    campaignName,
    campaignStatus: liveStatus(value["campaign_status"]),
    problem: textOrNull(value["problem"]),
    requested,
    status: liveStatus(value["status"]),
  }
}

function parseItem(value: unknown): StatusItem | null {
  if (!isRecord(value)) return null
  const kind = value["kind"]
  if (typeof kind !== "string" || !Object.hasOwn(KIND_IDS, kind)) return null
  const statusKind = kind as StatusKind
  const reference = value[statusKind]
  const status = value["status"]
  if (!isRecord(reference) || (status !== "ENABLED" && status !== "PAUSED")) return null
  const customerId = googleAdsId(reference["customer_id"])
  const campaignId = googleAdsId(reference["campaign_id"])
  const key = customerId === null ? null : statusResourceName(statusKind, customerId, reference)
  if (customerId === null || campaignId === null || key === null) return null
  return {
    adGroupId: googleAdsId(reference["ad_group_id"]),
    campaignId,
    customerId,
    entry: value,
    key,
    kind: statusKind,
    label: textOrNull(reference["label"]) ?? key,
    scopeLabel: textOrNull(reference["scope_label"]),
    status,
  }
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseStatusChangeArgs(value: unknown): StatusChangeArgs | null {
  const parsed = parseCheckedEntries(value, "changes", parseItem, parseCheck)
  return parsed && { accounts: parsed.accounts, checks: parsed.checks, items: parsed.entries }
}

function groupKey(customerId: string, id: string): string {
  return `${customerId}:${id}`
}

function changeOf(status: RequestedStatus, was: LiveStatus | null): StatusChange {
  if (status === was) return "already_set"
  return status === "ENABLED" ? "turn_on" : "turn_off"
}

/** Every proposed item once, cancelled when the current edit no longer holds it. */
export function statusRows(proposed: StatusChangeArgs, current: StatusChangeArgs): StatusRow[] {
  const kept = new Map(current.items.map((item) => [item.key, item]))
  // What each campaign and ad group is set to once the request runs.
  const requested = new Map<string, RequestedStatus>()
  for (const item of current.items) {
    if (item.kind === "campaign")
      requested.set(groupKey(item.customerId, item.campaignId), item.status)
    if (item.kind === "ad_group" && item.adGroupId !== null)
      requested.set(groupKey(item.customerId, item.adGroupId), item.status)
  }
  return proposed.items.map((original) => {
    const edited = kept.get(original.key)
    const item = edited ?? original
    const check = proposed.checks.get(item.key) ?? { unavailable: true as const }
    const was = check.unavailable ? null : check.status
    const parent = check.unavailable ? null : parentOf(item, check, requested)
    const change = changeOf(item.status, was)
    return {
      campaignName: campaignNameOf(item, check),
      campaignOn: check.unavailable
        ? null
        : onState(requested.get(groupKey(item.customerId, item.campaignId)), check.campaignStatus),
      cancelled: edited === undefined,
      change,
      groupName: check.unavailable ? null : check.adGroupName,
      item,
      key: item.key,
      problem: problemOf(item, check),
      status: item.status,
      was,
      wontShow:
        change === "turn_on" && parent !== null && parent.on === false
          ? `Won't show ads until ${parent.name} is on.`
          : null,
    }
  })
}

function campaignNameOf(item: StatusItem, check: StatusCheck): string {
  if (!check.unavailable) return check.campaignName
  return item.kind === "campaign" ? item.label : (item.scopeLabel ?? `Campaign ${item.campaignId}`)
}

function onState(requested: RequestedStatus | undefined, live: LiveStatus | null): boolean | null {
  const status = requested ?? live
  return status === null ? null : status === "ENABLED"
}

// The first parent that stays off: an ad or keyword's ad group, then the campaign.
function parentOf(
  item: StatusItem,
  check: Extract<StatusCheck, { unavailable: false }>,
  requested: ReadonlyMap<string, RequestedStatus>
): { name: string; on: boolean | null } | null {
  if (item.kind === "campaign") return null
  if ((item.kind === "ad" || item.kind === "keyword") && item.adGroupId !== null) {
    const adGroup = {
      name: check.adGroupName ?? "its ad group",
      on: onState(requested.get(groupKey(item.customerId, item.adGroupId)), check.adGroupStatus),
    }
    if (adGroup.on === false) return adGroup
  }
  return {
    name: check.campaignName,
    on: onState(requested.get(groupKey(item.customerId, item.campaignId)), check.campaignStatus),
  }
}

// Google's rejection applies to the status it was checked for, so changing the status clears it.
// A removed or missing object can't take any status.
function problemOf(item: StatusItem, check: StatusCheck): string | null {
  if (check.unavailable) return UNAVAILABLE_PROBLEM
  const anyStatus = check.status === "REMOVED" || check.status === null
  return anyStatus || item.status === check.requested ? check.problem : null
}

export function statusCounts(rows: readonly StatusRow[]): StatusCounts {
  const live = rows.filter((row) => !row.cancelled)
  const count = (change: StatusChange) => live.filter((row) => row.change === change).length
  const turnOn = count("turn_on")
  const turnOff = count("turn_off")
  return {
    alreadySet: count("already_set"),
    apply: turnOn + turnOff,
    campaigns: new Set(live.map((row) => groupKey(row.item.customerId, row.item.campaignId))).size,
    problems: live.filter((row) => row.problem !== null).length,
    total: live.length,
    turnOff,
    turnOn,
    wontShow: live.filter((row) => row.wontShow !== null).length,
  }
}

/** The `changes` value after patching the given rows; cancelled rows are left out. */
export function editedChanges(
  rows: readonly StatusRow[],
  keys: ReadonlySet<string>,
  patch: StatusPatch
): Record<string, unknown>[] {
  return rows.flatMap((row) => {
    const entry = (status: RequestedStatus) => ({ ...row.item.entry, status })
    const hit = keys.has(row.key) ? patch : null
    if (row.cancelled) return hit && "cancelled" in hit && !hit.cancelled ? [entry(row.status)] : []
    if (hit === null) return [entry(row.status)]
    if ("cancelled" in hit) return hit.cancelled ? [] : [entry(row.status)]
    return [entry(hit.status)]
  })
}

/** Why the request can't be approved yet, or null. */
export function statusBlock(args: StatusChangeArgs | null): string | null {
  if (args === null) return null
  const counts = statusCounts(statusRows(args, args))
  if (counts.total === 0) return "Every change is cancelled. Decline this request, or undo one."
  if (counts.problems > 0) return "Cancel or fix the changes that need attention to approve."
  if (counts.apply === 0) return "These items already have the status you chose."
  return null
}

export function statusPrompt(counts: StatusCounts, accountNames: readonly string[]): string {
  if (counts.apply === 0) return "Nothing is left to change."
  const parts = [
    counts.turnOff > 0 ? `turn off ${approvalCountLine(counts.turnOff, "item")}` : null,
    counts.turnOn > 0
      ? `turn on ${counts.turnOff > 0 ? String(counts.turnOn) : approvalCountLine(counts.turnOn, "item")}`
      : null,
  ].filter((part) => part !== null)
  const where =
    accountNames.length === 1 ? accountNames[0] : `${String(accountNames.length)} accounts`
  const sentence = `${parts.join(" and ")} in ${where ?? "Google Ads"}.`
  return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}`
}

export function statusApproveLabel(counts: StatusCounts): string {
  return applyChangesLabel(counts.apply)
}

export function statusAccountNames(
  rows: readonly StatusRow[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>
): string[] {
  const ids = new Set(rows.filter((row) => !row.cancelled).map((row) => row.item.customerId))
  return [...ids].map((id) => accounts.get(id)?.label ?? "Google Ads account")
}

export function statusBannerDetail(
  counts: StatusCounts,
  accountIds: readonly string[],
  accounts: ReadonlyMap<string, GoogleAdsApprovalAccount>
): string {
  const timeZone = accountIds.length === 1 ? accounts.get(accountIds[0] ?? "")?.timeZone : undefined
  return [
    approvalCountLine(counts.total, "item"),
    approvalCountLine(counts.campaigns, "campaign"),
    timeZone ? `Account time ${timeZone}` : null,
  ]
    .filter((part) => part !== null)
    .join(" · ")
}

export function statusLabel(status: LiveStatus | null): string {
  if (status === null) return "—"
  return status === "ENABLED" ? "On" : status === "PAUSED" ? "Off" : "Removed"
}

export function statusDetails(args: StatusChangeArgs | null): FanOutDetail[] {
  if (args === null) return []
  const counts = statusCounts(statusRows(args, args))
  return [
    { label: "Items", value: String(args.items.length) },
    ...(counts.turnOff > 0 ? [{ label: "Turn Off", value: String(counts.turnOff) }] : []),
    ...(counts.turnOn > 0 ? [{ label: "Turn On", value: String(counts.turnOn) }] : []),
  ]
}

export function statusCampaign(row: StatusRow): string {
  return `${row.item.customerId}:${row.item.campaignId}`
}

/** One row per campaign the items sit in, in the order its items first appear. */
export function campaignParents(
  rows: readonly StatusRow[],
  accounts: StatusChangeArgs["accounts"],
  showAccount: boolean
): ParentRow[] {
  return groupedByParent(rows, statusCampaign).map(({ items, key, live }) => {
    const first = items[0]
    const on = items.find((row) => row.campaignOn !== null)?.campaignOn ?? null
    return {
      cancelled: live.length === 0,
      context: showAccount && first ? (accounts.get(first.item.customerId)?.label ?? null) : null,
      key,
      name: first?.campaignName ?? key,
      problems: live.filter((row) => row.problem !== null).length,
      values: { campaign_on: on === null ? "—" : on ? "On" : "Off", items: live.length },
    }
  })
}
