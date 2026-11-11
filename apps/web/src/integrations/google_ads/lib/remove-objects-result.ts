// apps/web/src/integrations/google_ads/lib/remove-objects-result.ts

import { countsText } from "@/integrations/google_ads/lib/edit-outcomes"
import {
  alsoRemovesText,
  parseDependants,
  REMOVAL_KIND_TITLES,
  type RemovalKind,
} from "@/integrations/google_ads/lib/remove-objects"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type RemovalOutcome = "removed" | "already_removed" | "failed" | "unverified"

type RemovalObjectResult = {
  alsoRemoved: string
  campaignName: string | null
  errorCode: string | null
  kind: RemovalKind
  message: string | null
  name: string
  outcome: RemovalOutcome
  resourceName: string
}

export type RemoveObjectsResult = { accountId: string; objects: RemovalObjectResult[] }

const OUTCOMES = new Set<string>(["removed", "already_removed", "failed", "unverified"])

export const REMOVAL_OUTCOME_LABELS: Record<RemovalOutcome, string> = {
  already_removed: "Already Removed",
  failed: "Failed",
  removed: "Removed",
  unverified: "Unconfirmed",
}

export const REMOVAL_OUTCOME_BADGES = {
  already_removed: "secondary",
  failed: "destructive",
  removed: "success",
  unverified: "warning",
} as const

function parseObject(value: unknown): RemovalObjectResult | null {
  if (!isRecord(value)) return null
  const { kind, outcome } = value
  if (
    typeof kind !== "string" ||
    !Object.hasOwn(REMOVAL_KIND_TITLES, kind) ||
    typeof outcome !== "string" ||
    !OUTCOMES.has(outcome) ||
    !isNonEmptyString(value["resource_name"])
  )
    return null
  const text = (key: string) => (isNonEmptyString(value[key]) ? value[key] : null)
  const removalKind = kind as RemovalKind
  return {
    alsoRemoved: alsoRemovesText(removalKind, parseDependants(value["dependants"])),
    campaignName: text("campaign_name"),
    errorCode: text("error_code"),
    kind: removalKind,
    message: text("message"),
    name: text("name") ?? value["resource_name"],
    outcome: outcome as RemovalOutcome,
    resourceName: value["resource_name"],
  }
}

export function parseRemoveObjectsResult(value: unknown): RemoveObjectsResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !Array.isArray(value["objects"])
  )
    return null
  const objects: RemovalObjectResult[] = []
  for (const item of value["objects"]) {
    const object = parseObject(item)
    if (object === null) return null
    objects.push(object)
  }
  return { accountId: value["account_id"], objects }
}

export function removalResultSummary(result: RemoveObjectsResult): string {
  const count = (outcome: RemovalOutcome) =>
    result.objects.filter((object) => object.outcome === outcome).length
  return countsText([
    [count("removed"), "removed"],
    [count("already_removed"), "already removed"],
    [count("failed"), "failed"],
    [count("unverified"), "unconfirmed"],
  ])
}
