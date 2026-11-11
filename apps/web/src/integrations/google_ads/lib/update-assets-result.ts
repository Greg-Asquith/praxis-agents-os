// apps/web/src/integrations/google_ads/lib/update-assets-result.ts

import {
  countsText,
  EDIT_OUTCOME_LABELS,
  outcomeTabs,
} from "@/integrations/google_ads/lib/edit-outcomes"
import type { AssetType } from "@/integrations/google_ads/lib/new-assets"
import type { AssetTargetKind } from "@/integrations/google_ads/lib/update-assets"
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

export type AssetOutcome = (typeof OUTCOMES)[number]

export type AssetOutcomeRow = {
  action: "add" | "remove" | "change"
  assetLabel: string
  assetType: AssetType
  errorCode: string | null
  message: string | null
  outcome: AssetOutcome
  targetKind: AssetTargetKind | null
  targetName: string | null
}

export type UpdateAssetsResult = { accountId: string; rows: AssetOutcomeRow[] }

const ASSET_OUTCOME_LABELS: Record<AssetOutcome, string> = {
  added: "Added",
  already_set: "Already Linked",
  changed: "Changed",
  failed: "Failed",
  not_found: "Not There",
  removed: "Removed",
  unverified: "Unconfirmed",
}

export const ASSET_OUTCOME_BADGES = {
  added: "success",
  already_set: "secondary",
  changed: "success",
  failed: "destructive",
  not_found: "secondary",
  removed: "success",
  unverified: "warning",
} as const

function parseRow(value: unknown): AssetOutcomeRow | null {
  if (!isRecord(value)) return null
  const { action, asset_label: label, asset_type: type, outcome, target_kind: kind } = value
  if (
    (action !== "add" && action !== "remove" && action !== "change") ||
    (type !== "SITELINK" && type !== "CALLOUT") ||
    typeof label !== "string" ||
    typeof outcome !== "string" ||
    !(outcome in ASSET_OUTCOME_LABELS) ||
    (kind != null && kind !== "campaign" && kind !== "ad_group")
  )
    return null
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    action,
    assetLabel: label,
    assetType: type,
    errorCode: text("error_code"),
    message: text("message"),
    outcome: outcome as AssetOutcome,
    targetKind: kind ?? null,
    targetName: text("target_name"),
  }
}

export function parseUpdateAssetsResult(value: unknown): UpdateAssetsResult | null {
  if (!isRecord(value) || typeof value["account_id"] !== "string") return null
  if (!Array.isArray(value["outcomes"])) return null
  const rows = value["outcomes"].map(parseRow)
  if (rows.some((row) => row === null)) return null
  return { accountId: value["account_id"], rows: rows.filter((row) => row !== null) }
}

/** The label of a row's outcome; a content change that's already in place isn't a link. */
export function assetOutcomeLabel(row: AssetOutcomeRow): string {
  return row.action === "change" && row.outcome === "already_set"
    ? EDIT_OUTCOME_LABELS.already_set
    : ASSET_OUTCOME_LABELS[row.outcome]
}

export function assetOutcomeSummary(rows: readonly AssetOutcomeRow[]): string {
  return countsText(
    OUTCOMES.map((outcome) => [
      rows.filter((row) => row.outcome === outcome).length,
      ASSET_OUTCOME_LABELS[outcome].toLowerCase(),
    ])
  )
}

export const ASSET_OUTCOME_TABS = outcomeTabs(ASSET_OUTCOME_LABELS, OUTCOMES)
