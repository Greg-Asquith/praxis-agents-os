// apps/web/src/features/conversations/components/workflow-outcome-summary.ts

import type { ToolActivity } from "@/features/conversations/message-parts"
import { isRecord } from "@/lib/guards"

const APPLIED_OUTCOME_LABELS = {
  added: "Added",
  applied: "Applied",
  created: "Created",
  enabled: "Enabled",
  linked: "Linked",
  paused: "Paused",
  removed: "Removed",
  unlinked: "Unlinked",
  updated: "Updated",
} as const

const SKIPPED_OUTCOMES = new Set([
  "already_linked",
  "not_found",
  "not_linked",
  "skipped",
  "skipped_existing",
])

type AppliedOutcome = keyof typeof APPLIED_OUTCOME_LABELS
type OutcomeTotals = {
  applied: Map<string, { count: number; label: string; noun: string }>
  denied: number
  failed: number
  skipped: number
}

export function workflowOutcomeSummary(children: ToolActivity[]): string | null {
  const totals: OutcomeTotals = {
    applied: new Map(),
    denied: 0,
    failed: 0,
    skipped: 0,
  }

  for (const child of children) {
    if (child.status === "denied") {
      totals.denied += 1
      continue
    }
    const foundOutcome = collectResultOutcomes(child, totals)
    if (child.status === "failed" && !foundOutcome) {
      totals.failed += 1
    }
  }

  const segments = [...totals.applied.values()].map(
    ({ count, label, noun }) => `${label} ${String(count)} ${pluralizeNoun(noun, count)}`
  )
  if (totals.skipped > 0) {
    segments.push(`${String(totals.skipped)} skipped`)
  }
  if (totals.failed > 0) {
    segments.push(`${String(totals.failed)} failed`)
  }
  if (totals.denied > 0) {
    segments.push(`${String(totals.denied)} ${totals.denied === 1 ? "action" : "actions"} declined`)
  }
  return segments.length > 0 ? segments.join(" · ") : null
}

function collectResultOutcomes(child: ToolActivity, totals: OutcomeTotals): boolean {
  const result = parseResult(child.result)
  if (!result) {
    return false
  }

  let found = collectRecordOutcomes(child, result, totals)
  const resources = result["results"]
  if (Array.isArray(resources)) {
    for (const resource of resources) {
      if (!isRecord(resource)) {
        continue
      }
      if (resource["status"] === "error") {
        totals.failed += 1
        found = true
        continue
      }
      if (!isRecord(resource["data"])) {
        continue
      }
      found = collectRecordOutcomes(child, resource["data"], totals) || found
    }
  }
  return found
}

function collectRecordOutcomes(
  child: ToolActivity,
  value: Record<string, unknown>,
  totals: OutcomeTotals
): boolean {
  let found = false
  const counts = value["counts"]
  if (isRecord(counts)) {
    for (const [outcome, rawCount] of Object.entries(counts)) {
      const count = outcomeCount(rawCount)
      if (count === null) {
        continue
      }
      if (isAppliedOutcome(outcome)) {
        addApplied(totals, outcome, nounForTool(child.name), count)
        found = true
      } else if (SKIPPED_OUTCOMES.has(outcome)) {
        totals.skipped += count
        found = true
      } else if (outcome === "failed" || outcome === "unverified") {
        totals.failed += count
        found = true
      }
    }
  }

  const resourceNames = value["resource_names"]
  if (Array.isArray(resourceNames)) {
    const count = resourceNames.length
    const status = isRecord(child.args) ? child.args["status"] : null
    const outcome = status === "PAUSED" ? "paused" : status === "ENABLED" ? "enabled" : "updated"
    addApplied(totals, outcome, "campaign", count)
    found = true
  }
  const errors = value["campaign_errors"]
  if (Array.isArray(errors)) {
    totals.failed += errors.length
    found = true
  }
  return found
}

function addApplied(totals: OutcomeTotals, outcome: AppliedOutcome, noun: string, count: number) {
  if (count === 0) {
    return
  }
  const label = APPLIED_OUTCOME_LABELS[outcome]
  const key = `${label}:${noun}`
  const current = totals.applied.get(key)
  totals.applied.set(key, { count: (current?.count ?? 0) + count, label, noun })
}

function isAppliedOutcome(value: string): value is AppliedOutcome {
  return Object.hasOwn(APPLIED_OUTCOME_LABELS, value)
}

function nounForTool(toolName: string): string {
  if (toolName.includes("negative_keywords")) {
    return "keyword"
  }
  if (toolName.includes("campaign")) {
    return "campaign"
  }
  if (toolName.includes("keyword_list")) {
    return "list"
  }
  if (toolName.includes("record")) {
    return "record"
  }
  return "change"
}

function outcomeCount(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null
}

function parseResult(value: unknown): Record<string, unknown> | null {
  if (isRecord(value)) {
    return value
  }
  if (typeof value !== "string" || value.includes("[excerpt truncated]")) {
    return null
  }
  try {
    const parsed: unknown = JSON.parse(value)
    return isRecord(parsed) ? parsed : null
  } catch {
    return null
  }
}

function pluralizeNoun(noun: string, count: number): string {
  return count === 1 ? noun : `${noun}s`
}
