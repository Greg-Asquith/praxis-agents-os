// apps/web/src/integrations/google_ads/lib/update-assets-result.ts

import type { DataTableTab } from "@/components/ui/data-table"
import type { AssetTargetKind, AssetType } from "@/integrations/google_ads/lib/update-assets"
import { isRecord } from "@/lib/guards"

export type AssetOutcome =
  "added" | "removed" | "changed" | "already_set" | "not_found" | "failed" | "unverified"

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

export const ASSET_OUTCOME_LABELS: Record<AssetOutcome, string> = {
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

export function assetOutcomeSummary(rows: readonly AssetOutcomeRow[]): string {
  const totals = new Map<AssetOutcome, number>()
  for (const row of rows) totals.set(row.outcome, (totals.get(row.outcome) ?? 0) + 1)
  return [...totals]
    .map(
      ([outcome, total]) =>
        `${total.toLocaleString("en-GB")} ${ASSET_OUTCOME_LABELS[outcome].toLowerCase()}`
    )
    .join(" · ")
}

function tab(id: AssetOutcome | "all", hideWhenEmpty = true): DataTableTab {
  return {
    hideWhenEmpty,
    id,
    label: id === "all" ? "All" : ASSET_OUTCOME_LABELS[id],
    match: (row) => id === "all" || row["token"] === id,
  }
}

// Result tables put each row's outcome in `token`.
export const ASSET_OUTCOME_TABS: DataTableTab[] = [
  tab("all", false),
  tab("added"),
  tab("removed"),
  tab("changed"),
  tab("already_set"),
  tab("not_found"),
  tab("failed"),
  tab("unverified"),
]
