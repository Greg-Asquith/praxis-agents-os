// apps/web/src/integrations/google_ads/lib/status-change-result.ts

import {
  countsText,
  type EditOutcome,
  isEditOutcome,
} from "@/integrations/google_ads/lib/edit-outcomes"
import {
  STATUS_KIND_TITLES,
  type LiveStatus,
  type RequestedStatus,
  type StatusKind,
} from "@/integrations/google_ads/lib/status-change"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type StatusObjectResult = {
  after: LiveStatus | null
  before: LiveStatus | null
  campaignName: string
  errorCode: string | null
  kind: StatusKind
  message: string | null
  name: string
  outcome: EditOutcome
  requested: RequestedStatus
  resourceName: string
}

export type StatusChangeResult = { accountId: string; objects: StatusObjectResult[] }

function liveStatus(value: unknown): LiveStatus | null {
  return value === "ENABLED" || value === "PAUSED" || value === "REMOVED" ? value : null
}

function parseObject(value: unknown): StatusObjectResult | null {
  if (!isRecord(value)) return null
  const { kind, outcome, requested } = value
  if (
    typeof kind !== "string" ||
    !Object.hasOwn(STATUS_KIND_TITLES, kind) ||
    !isEditOutcome(outcome) ||
    (requested !== "ENABLED" && requested !== "PAUSED") ||
    !isNonEmptyString(value["resource_name"])
  )
    return null
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    after: liveStatus(value["after"]),
    before: liveStatus(value["before"]),
    campaignName: text("campaign_name") ?? "",
    errorCode: text("error_code"),
    kind: kind as StatusKind,
    message: text("message"),
    name: isNonEmptyString(value["name"]) ? value["name"] : value["resource_name"],
    outcome,
    requested,
    resourceName: value["resource_name"],
  }
}

export function parseStatusChangeResult(value: unknown): StatusChangeResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !Array.isArray(value["objects"])
  )
    return null
  const objects: StatusObjectResult[] = []
  for (const item of value["objects"]) {
    const object = parseObject(item)
    if (object === null) return null
    objects.push(object)
  }
  return { accountId: value["account_id"], objects }
}

const OUTCOME_LABELS = {
  failed: "Failed",
  unverified: "Unconfirmed",
  updated: "Changed",
} as const

export function outcomeLabel(object: StatusObjectResult): string {
  if (object.outcome === "already_set")
    return object.requested === "ENABLED" ? "Already On" : "Already Off"
  return OUTCOME_LABELS[object.outcome]
}

export function resultSummary(result: StatusChangeResult): string {
  const count = (outcome: EditOutcome) =>
    result.objects.filter((object) => object.outcome === outcome).length
  return countsText(
    [
      [count("updated"), "changed"],
      [count("already_set"), "already set"],
      [count("failed"), "failed"],
      [count("unverified"), "unconfirmed"],
    ],
    ", "
  )
}
