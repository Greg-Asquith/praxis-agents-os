// apps/web/src/integrations/meta_ads/lib/status-change.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { MetaAdsObjectType } from "@/integrations/meta_ads/lib/ads-manager-link"
import { formatCurrencyAmount, titleCaseToken } from "@/lib/format"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type MetaAdsRequestedStatus = "ACTIVE" | "PAUSED"
type Parent = "ad_set" | "campaign"

type Budget = {
  kind: "daily" | "lifetime" | "campaign"
  amount: string | null
  period: "daily" | "lifetime" | null
}

export type StatusTarget = {
  type: MetaAdsObjectType
  id: string
  accountId: string
  name: string
  scope: string | null
  status: string | null
  effectiveStatus: string | null
  budget: Budget | null
  currency: string | null
}

export type DeliveryImpact = {
  blockedBy: Parent[]
  alreadyOn: boolean
  startingChildren: number | null
  childrenTruncated: boolean
  dailyBudget: string | null
  lifetimeBudget: string | null
  budgetsIncomplete: boolean
  unavailable: boolean
}

export type StatusChangeArgs = {
  status: MetaAdsRequestedStatus
  targets: StatusTarget[]
  delivery: Record<string, DeliveryImpact>
  // True when an edit changed the status or objects since the server last checked them.
  needsReview: boolean
}

const LISTS = [
  { key: "campaigns", type: "campaign", idKey: "campaign_id" },
  { key: "ad_sets", type: "adset", idKey: "adset_id" },
  { key: "ads", type: "ad", idKey: "ad_id" },
] as const

const OBJECT_NOUNS = {
  campaign: ["campaign", "campaigns"],
  adset: ["ad set", "ad sets"],
  ad: ["ad", "ads"],
} as const

export const OBJECT_TITLES = { campaign: "Campaign", adset: "Ad Set", ad: "Ad" } as const

export function parseStatusChangeArgs(value: unknown): StatusChangeArgs | null {
  if (!isRecord(value) || (value["status"] !== "ACTIVE" && value["status"] !== "PAUSED"))
    return null
  const targets: StatusTarget[] = []
  for (const list of LISTS) {
    const items = value[list.key]
    if (items === undefined || items === null) continue
    if (!Array.isArray(items)) return null
    for (const item of items) {
      const target = parseTarget(item, list.type, list.idKey)
      if (target === null) return null
      targets.push(target)
    }
  }
  if (targets.length === 0) return null
  return {
    status: value["status"],
    targets,
    delivery: parseDelivery(value["_delivery"]),
    needsReview: !matchesReviewedSelection(value["_reviewed_selection"], value["status"], targets),
  }
}

function matchesReviewedSelection(
  reviewed: unknown,
  status: MetaAdsRequestedStatus,
  targets: readonly StatusTarget[]
): boolean {
  if (!isRecord(reviewed) || reviewed["status"] !== status) return false
  const objects = reviewed["objects"]
  return (
    Array.isArray(objects) &&
    objects.length === targets.length &&
    targets.every((target, index) => objects[index] === `${target.type}:${target.id}`)
  )
}

function parseTarget(value: unknown, type: MetaAdsObjectType, idKey: string): StatusTarget | null {
  if (!isRecord(value) || !isNonEmptyString(value[idKey])) return null
  const id = value[idKey]
  return {
    type,
    id,
    accountId: typeof value["account_id"] === "string" ? value["account_id"] : "",
    name: isNonEmptyString(value["label"]) ? value["label"] : id,
    scope: isNonEmptyString(value["scope_label"]) ? value["scope_label"] : null,
    status: typeof value["status"] === "string" ? value["status"] : null,
    effectiveStatus:
      typeof value["effective_status"] === "string" ? value["effective_status"] : null,
    budget: parseBudget(value["budget"]),
    currency: isNonEmptyString(value["currency"]) ? value["currency"] : null,
  }
}

function parseBudget(value: unknown): Budget | null {
  if (!isRecord(value)) return null
  const kind = value["kind"]
  if (kind !== "daily" && kind !== "lifetime" && kind !== "campaign") return null
  const period = value["period"]
  return {
    kind,
    amount: isNonEmptyString(value["amount"]) ? value["amount"] : null,
    period: period === "daily" || period === "lifetime" ? period : null,
  }
}

function parseDelivery(value: unknown): Record<string, DeliveryImpact> {
  const impacts: Record<string, DeliveryImpact> = {}
  if (!isRecord(value)) return impacts
  for (const [id, item] of Object.entries(value)) {
    if (!isRecord(item)) continue
    const blocked = Array.isArray(item["blocked_by"]) ? item["blocked_by"] : []
    impacts[id] = {
      blockedBy: (["ad_set", "campaign"] as const).filter((parent) => blocked.includes(parent)),
      alreadyOn: item["already_on"] === true,
      startingChildren:
        typeof item["starting_children"] === "number" ? item["starting_children"] : null,
      childrenTruncated: item["children_truncated"] === true,
      dailyBudget: isNonEmptyString(item["daily_budget"]) ? item["daily_budget"] : null,
      lifetimeBudget: isNonEmptyString(item["lifetime_budget"]) ? item["lifetime_budget"] : null,
      budgetsIncomplete: item["budgets_incomplete"] === true,
      unavailable: item["unavailable"] === true,
    }
  }
  return impacts
}

// A parent that stays off keeps this object from delivering even when it is on.
function staysOffNote(type: MetaAdsObjectType, blockedBy: readonly Parent[]): string | null {
  const parents = (["ad_set", "campaign"] as const)
    .filter((parent) => blockedBy.includes(parent) && !(type === "adset" && parent === "ad_set"))
    .map((parent) => (parent === "ad_set" ? "ad set" : "campaign"))
  if (type === "campaign" || parents.length === 0) return null
  return `This ${OBJECT_NOUNS[type][0]} stays off until its ${parents.join(" and ")} ${
    parents.length === 1 ? "is" : "are"
  } turned on.`
}

function blockedByEffectiveStatus(effectiveStatus: string | null): Parent[] {
  if (effectiveStatus === "ADSET_PAUSED") return ["ad_set"]
  if (effectiveStatus === "CAMPAIGN_PAUSED") return ["campaign"]
  return []
}

function money(amount: string, currency: string | null): string {
  return currency ? formatCurrencyAmount(amount, currency) : amount
}

function startingChildrenNote(type: MetaAdsObjectType, impact: DeliveryImpact): string | null {
  if (impact.startingChildren === null) return null
  const noun = type === "campaign" ? OBJECT_NOUNS.adset : OBJECT_NOUNS.ad
  if (impact.startingChildren === 0 && !impact.childrenTruncated)
    return `No ${noun[1]} will be on, so nothing starts delivering yet.`
  const count = `${impact.childrenTruncated ? "At least " : ""}${String(impact.startingChildren)}`
  return `${count} ${noun[impact.startingChildren === 1 && !impact.childrenTruncated ? 0 : 1]} can start delivering.`
}

function budgetNote(target: StatusTarget, impact: DeliveryImpact): string | null {
  const budget = target.budget
  // With a complete count of zero children on, the budget is held but nothing spends yet.
  const idle = impact.startingChildren === 0 && !impact.childrenTruncated
  if (budget?.kind === "campaign" && target.type === "adset") {
    const period = budget.period ? `${budget.period} ` : ""
    const source = budget.amount
      ? `the campaign's ${period}budget of ${money(budget.amount, target.currency)}`
      : "the campaign budget"
    return idle ? `Uses ${source} once its ads are on.` : `Spends from ${source}.`
  }
  if (budget && budget.kind !== "campaign" && budget.amount) {
    const limit = `${money(budget.amount, target.currency)}${
      budget.kind === "daily" ? " a day" : " in total"
    }`
    return idle ? `Holds a budget of up to ${limit}.` : `Starts spending up to ${limit}.`
  }
  if (target.type !== "campaign") return null
  const parts = [
    impact.dailyBudget ? `${money(impact.dailyBudget, target.currency)} a day` : null,
    impact.lifetimeBudget ? `${money(impact.lifetimeBudget, target.currency)} in total` : null,
  ].filter(isNonEmptyString)
  // Unread or uncounted budgets mean the total is a lower bound, never zero.
  const partial = impact.budgetsIncomplete || impact.childrenTruncated
  if (parts.length === 0)
    return partial ? "Some ad set budgets couldn't be read, so spending isn't shown." : null
  return `Ad set budgets that start spending: ${partial ? "at least " : ""}${parts.join(" and ")}.`
}

// Notes shown under each object when turning it on. Pausing needs none.
export function activationNotes(
  target: StatusTarget,
  impact: DeliveryImpact | undefined
): string[] {
  if (impact === undefined) return []
  if (impact.unavailable) return ["Delivery impact couldn't be checked."]
  if (impact.alreadyOn) return ["Already on, so this changes nothing."]
  const stayOff = staysOffNote(target.type, impact.blockedBy)
  if (stayOff) return [stayOff]
  return [startingChildrenNote(target.type, impact), budgetNote(target, impact)].filter(
    isNonEmptyString
  )
}

export function statusLabel(status: string | null): string {
  if (status === null) return "—"
  if (status === "ACTIVE") return "On"
  if (status === "PAUSED") return "Off"
  return titleCaseToken(status.toLowerCase(), status)
}

// Meta's delivery status, shown only when it adds something to the configured status.
export function deliveryLabel(
  status: string | null,
  effectiveStatus: string | null
): string | null {
  if (effectiveStatus === null || effectiveStatus === status) return null
  return titleCaseToken(effectiveStatus.toLowerCase(), effectiveStatus)
}

export function requestedStatusLabel(status: MetaAdsRequestedStatus): string {
  return status === "ACTIVE" ? "Turn On" : "Pause"
}

export function targetCounts(targets: readonly StatusTarget[]): string {
  return LISTS.map(({ type }) => {
    const count = targets.filter((target) => target.type === type).length
    return count === 0 ? null : `${String(count)} ${OBJECT_NOUNS[type][count === 1 ? 0 : 1]}`
  })
    .filter(isNonEmptyString)
    .join(", ")
}

export function statusChangeDetails(args: StatusChangeArgs | null): FanOutDetail[] {
  if (args === null) return []
  return [
    { label: "Change", value: requestedStatusLabel(args.status) },
    { label: "Objects", value: targetCounts(args.targets) },
  ]
}

// Result models

type StatusOutcomeToken = "updated" | "already_set" | "failed" | "unverified"

export type StatusObjectResult = {
  type: MetaAdsObjectType
  id: string
  name: string
  previousStatus: string | null
  status: string | null
  effectiveStatus: string | null
  outcome: StatusOutcomeToken
  errorCode: string | null
  message: string | null
}

export type StatusChangeResult = {
  accountId: string
  requestedStatus: MetaAdsRequestedStatus
  objects: StatusObjectResult[]
}

const OBJECT_TYPES = new Set<string>(["campaign", "adset", "ad"])
const OUTCOMES = new Set<string>(["updated", "already_set", "failed", "unverified"])

export function parseStatusChangeResult(value: unknown): StatusChangeResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    (value["requested_status"] !== "ACTIVE" && value["requested_status"] !== "PAUSED") ||
    !Array.isArray(value["objects"])
  )
    return null
  const objects: StatusObjectResult[] = []
  for (const item of value["objects"]) {
    const object = parseObjectResult(item)
    if (object === null) return null
    objects.push(object)
  }
  return { accountId: value["account_id"], requestedStatus: value["requested_status"], objects }
}

function parseObjectResult(value: unknown): StatusObjectResult | null {
  if (
    !isRecord(value) ||
    typeof value["object_type"] !== "string" ||
    !OBJECT_TYPES.has(value["object_type"]) ||
    !isNonEmptyString(value["object_id"]) ||
    typeof value["outcome"] !== "string" ||
    !OUTCOMES.has(value["outcome"])
  )
    return null
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    type: value["object_type"] as MetaAdsObjectType,
    id: value["object_id"],
    name: isNonEmptyString(value["object_name"]) ? value["object_name"] : value["object_id"],
    previousStatus: text("previous_status"),
    status: text("status"),
    effectiveStatus: text("effective_status"),
    outcome: value["outcome"] as StatusOutcomeToken,
    errorCode: text("error_code"),
    message: text("message"),
  }
}

// An object that is on but held off by a parent still is not delivering.
export function outcomeNote(object: StatusObjectResult): string | null {
  if (object.status !== "ACTIVE" || object.outcome === "failed") return null
  return staysOffNote(object.type, blockedByEffectiveStatus(object.effectiveStatus))
}
