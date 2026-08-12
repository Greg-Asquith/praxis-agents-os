// apps/web/src/features/audit/operation-detail.ts

import { isRecord } from "@/lib/guards"

export type AuditDetailValue =
  string | number | boolean | null | AuditDetailValue[] | { [key: string]: AuditDetailValue }

type OperationTarget = {
  entity_type: string
  external_id: string
  display_name: string | null
  integration_resource_id: string | null
  attributes: Record<string, AuditDetailValue>
}

type OperationIntent = { fields: Record<string, AuditDetailValue> }

export type OperationIntentGroup = {
  key: string
  action: string
  entity_type: string
  external_id: string | null
  display_name: string | null
  fields: Record<string, AuditDetailValue>
  items: OperationIntent[]
}

export type OperationOutcomeStatus = "applied" | "skipped" | "failed" | "unverified"
type OperationEffectStatus = Exclude<OperationOutcomeStatus, "skipped">

type OperationEffect = {
  status: OperationEffectStatus
  fields: Record<string, AuditDetailValue>
  external_ref: string | null
  error_code: string | null
}

export type OperationOutcome = {
  intent_index: number
  status: OperationOutcomeStatus
  fields: Record<string, AuditDetailValue>
  effects: OperationEffect[]
}

type OperationOutcomeGroup = { key: string; outcomes: OperationOutcome[] }

export type OperationCounts = Record<OperationOutcomeStatus, number>

type OperationDetailBase = {
  target: OperationTarget
  intent_groups: OperationIntentGroup[]
}

type PendingOperationDetail = OperationDetailBase & { phase: "pending" }
type TerminalOperationDetail = OperationDetailBase & {
  phase: "terminal"
  outcome_groups: OperationOutcomeGroup[]
  intent_counts: OperationCounts
  effect_counts: OperationCounts
}
export type OperationDetail = PendingOperationDetail | TerminalOperationDetail

const OUTCOME_STATUSES = new Set<OperationOutcomeStatus>([
  "applied",
  "skipped",
  "failed",
  "unverified",
])
const EFFECT_STATUSES = new Set<OperationEffectStatus>(["applied", "failed", "unverified"])

export function parseIntegrationOperationDetail(value: unknown): OperationDetail | null {
  if (!isRecord(value) || (value["phase"] !== "pending" && value["phase"] !== "terminal")) {
    return null
  }
  const target = parseTarget(value["target"])
  const intentGroups = parseIntentGroups(value["intent_groups"])
  if (!target || !intentGroups) return null
  if (value["phase"] === "pending") {
    return { phase: "pending", target, intent_groups: intentGroups }
  }

  const outcomeGroups = parseOutcomeGroups(value["outcome_groups"], intentGroups)
  const intentCounts = parseCounts(value["intent_counts"])
  const effectCounts = parseCounts(value["effect_counts"])
  if (!outcomeGroups || !intentCounts || !effectCounts) return null
  const outcomes = outcomeGroups.flatMap((group) => group.outcomes)
  const effects = outcomes.flatMap((outcome) => outcome.effects)
  if (!countsEqual(intentCounts, countStatuses(outcomes.map((outcome) => outcome.status)))) {
    return null
  }
  if (!countsEqual(effectCounts, countStatuses(effects.map((effect) => effect.status)))) {
    return null
  }
  return {
    phase: "terminal",
    target,
    intent_groups: intentGroups,
    outcome_groups: outcomeGroups,
    intent_counts: intentCounts,
    effect_counts: effectCounts,
  }
}

function parseTarget(value: unknown): OperationTarget | null {
  if (
    !isRecord(value) ||
    typeof value["entity_type"] !== "string" ||
    typeof value["external_id"] !== "string" ||
    !(value["display_name"] === null || typeof value["display_name"] === "string") ||
    !(
      value["integration_resource_id"] === null ||
      typeof value["integration_resource_id"] === "string"
    ) ||
    !isDetailRecord(value["attributes"])
  ) {
    return null
  }
  return {
    entity_type: value["entity_type"],
    external_id: value["external_id"],
    display_name: value["display_name"],
    integration_resource_id: value["integration_resource_id"],
    attributes: value["attributes"],
  }
}

function parseIntentGroups(value: unknown): OperationIntentGroup[] | null {
  if (!Array.isArray(value) || value.length === 0) return null
  const groups: OperationIntentGroup[] = []
  const keys = new Set<string>()
  for (const group of value) {
    if (
      !isRecord(group) ||
      typeof group["key"] !== "string" ||
      keys.has(group["key"]) ||
      typeof group["action"] !== "string" ||
      typeof group["entity_type"] !== "string" ||
      !(group["external_id"] === null || typeof group["external_id"] === "string") ||
      !(group["display_name"] === null || typeof group["display_name"] === "string") ||
      !isDetailRecord(group["fields"]) ||
      !Array.isArray(group["items"]) ||
      group["items"].length === 0
    ) {
      return null
    }
    const items: OperationIntent[] = []
    for (const item of group["items"]) {
      if (!isRecord(item) || !isDetailRecord(item["fields"])) return null
      items.push({ fields: item["fields"] })
    }
    keys.add(group["key"])
    groups.push({
      key: group["key"],
      action: group["action"],
      entity_type: group["entity_type"],
      external_id: group["external_id"],
      display_name: group["display_name"],
      fields: group["fields"],
      items,
    })
  }
  return groups
}

function parseOutcomeGroups(
  value: unknown,
  intentGroups: OperationIntentGroup[]
): OperationOutcomeGroup[] | null {
  if (!Array.isArray(value) || value.length !== intentGroups.length) return null
  const groups: OperationOutcomeGroup[] = []
  for (const [groupIndex, group] of value.entries()) {
    const intentGroup = intentGroups[groupIndex]
    if (
      !intentGroup ||
      !isRecord(group) ||
      group["key"] !== intentGroup.key ||
      !Array.isArray(group["outcomes"]) ||
      group["outcomes"].length !== intentGroup.items.length
    ) {
      return null
    }
    const outcomes: OperationOutcome[] = []
    for (const [intentIndex, outcome] of group["outcomes"].entries()) {
      const parsed = parseOutcome(outcome, intentIndex)
      if (!parsed) return null
      outcomes.push(parsed)
    }
    groups.push({ key: intentGroup.key, outcomes })
  }
  return groups
}

function parseOutcome(value: unknown, intentIndex: number): OperationOutcome | null {
  if (
    !isRecord(value) ||
    value["intent_index"] !== intentIndex ||
    !isOutcomeStatus(value["status"]) ||
    !isDetailRecord(value["fields"]) ||
    !Array.isArray(value["effects"])
  ) {
    return null
  }
  const effects = value["effects"].map(parseEffect)
  if (effects.some((effect) => effect === null)) return null
  const parsedEffects = effects.filter((effect): effect is OperationEffect => effect !== null)
  const statuses = new Set(parsedEffects.map((effect) => effect.status))
  if (
    (value["status"] === "skipped" && parsedEffects.length > 0) ||
    (value["status"] !== "skipped" && parsedEffects.length === 0) ||
    (value["status"] === "applied" && (statuses.size !== 1 || !statuses.has("applied"))) ||
    (value["status"] === "failed" && (!statuses.has("failed") || statuses.has("unverified"))) ||
    (value["status"] === "unverified" && !statuses.has("unverified"))
  ) {
    return null
  }
  return {
    intent_index: intentIndex,
    status: value["status"],
    fields: value["fields"],
    effects: parsedEffects,
  }
}

function parseEffect(value: unknown): OperationEffect | null {
  if (
    !isRecord(value) ||
    !isEffectStatus(value["status"]) ||
    !isDetailRecord(value["fields"]) ||
    !(value["external_ref"] === null || typeof value["external_ref"] === "string") ||
    !(value["error_code"] === null || typeof value["error_code"] === "string")
  ) {
    return null
  }
  if (
    (value["status"] === "applied" && value["error_code"] !== null) ||
    (value["status"] !== "applied" &&
      (value["external_ref"] !== null || value["error_code"] === null))
  ) {
    return null
  }
  return {
    status: value["status"],
    fields: value["fields"],
    external_ref: value["external_ref"],
    error_code: value["error_code"],
  }
}

function parseCounts(value: unknown): OperationCounts | null {
  if (!isRecord(value)) return null
  const parsed = {
    applied: value["applied"],
    skipped: value["skipped"],
    failed: value["failed"],
    unverified: value["unverified"],
  }
  return Object.values(parsed).every(isCount) ? (parsed as OperationCounts) : null
}

function countStatuses(
  statuses: (OperationOutcomeStatus | OperationEffectStatus)[]
): OperationCounts {
  const counts: OperationCounts = { applied: 0, skipped: 0, failed: 0, unverified: 0 }
  for (const status of statuses) counts[status] += 1
  return counts
}

function countsEqual(left: OperationCounts, right: OperationCounts): boolean {
  return Object.keys(left).every(
    (key) => left[key as OperationOutcomeStatus] === right[key as OperationOutcomeStatus]
  )
}

function isDetailRecord(value: unknown): value is Record<string, AuditDetailValue> {
  return isRecord(value) && Object.values(value).every(isDetailValue)
}

function isDetailValue(value: unknown): value is AuditDetailValue {
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) return true
  if (Array.isArray(value)) return value.every(isDetailValue)
  return isDetailRecord(value)
}

function isOutcomeStatus(value: unknown): value is OperationOutcomeStatus {
  return typeof value === "string" && OUTCOME_STATUSES.has(value as OperationOutcomeStatus)
}

function isEffectStatus(value: unknown): value is OperationEffectStatus {
  return typeof value === "string" && EFFECT_STATUSES.has(value as OperationEffectStatus)
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}
