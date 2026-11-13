// apps/web/src/integrations/google_ads/lib/update-asset-groups-result.ts

import { countsText, outcomeTabs } from "@/integrations/google_ads/lib/edit-outcomes"
import {
  GROUP_CHANGE_LABELS,
  type GroupChangeKind,
} from "@/integrations/google_ads/lib/update-asset-groups"
import { isRecord } from "@/lib/guards"

const OUTCOMES = [
  "added",
  "removed",
  "changed",
  "already_set",
  "not_found",
  "failed",
  "unverified",
] as const

export type GroupOutcome = (typeof OUTCOMES)[number]

export type GroupOutcomeRow = {
  action: "add" | "remove" | "set"
  assetGroupName: string
  before: string | null
  campaignName: string | null
  errorCode: string | null
  item: string
  kind: GroupChangeKind
  message: string | null
  outcome: GroupOutcome
}

export type UpdateAssetGroupsResult = { accountId: string; rows: GroupOutcomeRow[] }

export const GROUP_OUTCOME_LABELS: Record<GroupOutcome, string> = {
  added: "Added",
  already_set: "Already Set",
  changed: "Changed",
  failed: "Failed",
  not_found: "Not There",
  removed: "Removed",
  unverified: "Unconfirmed",
}

export const GROUP_OUTCOME_BADGES = {
  added: "success",
  already_set: "secondary",
  changed: "success",
  failed: "destructive",
  not_found: "secondary",
  removed: "success",
  unverified: "warning",
} as const

function parseRow(value: unknown): GroupOutcomeRow | null {
  if (!isRecord(value)) return null
  const { action, item, kind, outcome } = value
  const name = value["asset_group_name"]
  if (
    (action !== "add" && action !== "remove" && action !== "set") ||
    typeof kind !== "string" ||
    !(kind in GROUP_CHANGE_LABELS) ||
    typeof item !== "string" ||
    typeof name !== "string" ||
    typeof outcome !== "string" ||
    !(outcome in GROUP_OUTCOME_LABELS)
  )
    return null
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    action,
    assetGroupName: name,
    before: text("before"),
    campaignName: text("campaign_name"),
    errorCode: text("error_code"),
    item,
    kind: kind as GroupChangeKind,
    message: text("message"),
    outcome: outcome as GroupOutcome,
  }
}

export function parseUpdateAssetGroupsResult(value: unknown): UpdateAssetGroupsResult | null {
  if (!isRecord(value) || typeof value["account_id"] !== "string") return null
  if (!Array.isArray(value["outcomes"])) return null
  const rows = value["outcomes"].map(parseRow)
  if (rows.some((row) => row === null)) return null
  return { accountId: value["account_id"], rows: rows.filter((row) => row !== null) }
}

export function groupOutcomeSummary(rows: readonly GroupOutcomeRow[]): string {
  return countsText(
    OUTCOMES.map((outcome) => [
      rows.filter((row) => row.outcome === outcome).length,
      GROUP_OUTCOME_LABELS[outcome].toLowerCase(),
    ])
  )
}

export const GROUP_OUTCOME_TABS = outcomeTabs(GROUP_OUTCOME_LABELS, OUTCOMES)
