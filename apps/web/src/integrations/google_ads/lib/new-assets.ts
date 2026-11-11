// apps/web/src/integrations/google_ads/lib/new-assets.ts

import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  ASSET_TYPE_LABELS,
  fieldProblem,
  newAssetKey,
  type AssetType,
} from "@/integrations/google_ads/lib/update-assets"
import { isRecord } from "@/lib/guards"

// Google's limit for one campaign or ad group, as the tool takes it.
const MAX_NEW_ASSETS = 20
// Google shows sitelinks in pairs or more.
const SITELINKS_TO_SHOW = 2

/** A new sitelink or callout in the tool's own shape, `{type: "sitelink", link_text, …}`. */
export type DraftAsset = Record<string, unknown>

/** Google's rejection of a new asset, named by its content. */
export type AssetProblem = { key: string; message: string }

export function draftAssetType(asset: DraftAsset): AssetType {
  return asset["type"] === "sitelink" ? "SITELINK" : "CALLOUT"
}

export function parseNewAsset(value: unknown): DraftAsset | null {
  return isRecord(value) && (value["type"] === "sitelink" || value["type"] === "callout")
    ? value
    : null
}

export function blankAsset(type: AssetType): DraftAsset {
  return type === "SITELINK"
    ? { type: "sitelink", link_text: "", description1: "", description2: "", final_url: "" }
    : { type: "callout", text: "" }
}

function blankIsNull(value: unknown): unknown {
  return typeof value === "string" && !value.trim() ? null : value
}

/** The `assets` value for the drafts; blank optional fields are null. */
export function serializeNewAssets(assets: readonly DraftAsset[]): Record<string, unknown>[] {
  return assets.map((asset) => {
    const dates = {
      start_date: blankIsNull(asset["start_date"] ?? null),
      end_date: blankIsNull(asset["end_date"] ?? null),
    }
    return asset["type"] === "sitelink"
      ? {
          type: "sitelink",
          link_text: asset["link_text"] ?? "",
          description1: blankIsNull(asset["description1"] ?? null),
          description2: blankIsNull(asset["description2"] ?? null),
          final_url: asset["final_url"] ?? "",
          ...dates,
        }
      : { type: "callout", text: asset["text"] ?? "", ...dates }
  })
}

/** Names each asset as the card does: "Sitelink 2", counted within its type. */
export function assetLabels(assets: readonly DraftAsset[]): string[] {
  const seen: Record<AssetType, number> = { CALLOUT: 0, SITELINK: 0 }
  return assets.map((asset) => {
    const type = draftAssetType(asset)
    seen[type] += 1
    return `${ASSET_TYPE_LABELS[type]} ${String(seen[type])}`
  })
}

/** What the card can find without asking Google: field limits, repeats, and the count. */
export function newAssetProblems(assets: readonly DraftAsset[]): string[] {
  const labels = assetLabels(assets)
  const problems = assets.flatMap((asset, index) => {
    const problem = fieldProblem(asset)
    return problem ? [`${String(labels[index])}: ${problem}`] : []
  })
  if (assets.length > MAX_NEW_ASSETS)
    problems.push(`Sitelinks and callouts: add at most ${String(MAX_NEW_ASSETS)} here.`)
  if (new Set(assets.map(newAssetKey)).size !== assets.length)
    problems.push("Sitelinks and callouts: list each one once.")
  return problems
}

/** Google's rejections from the last check, while the asset it rejected is still here. */
export function googleAssetProblems(
  assets: readonly DraftAsset[],
  problems: readonly AssetProblem[]
): string[] {
  const labels = new Map(
    assetLabels(assets).map((label, index) => [newAssetKey(assets[index] ?? {}), label])
  )
  return problems.flatMap((problem) => {
    const label = labels.get(problem.key)
    return label ? [`${label}: ${problem.message}`] : []
  })
}

/** True for a problem `newAssetProblems` or `googleAssetProblems` gave, to colour its row. */
export function isAssetProblem(problem: string): boolean {
  return /^(Sitelink \d|Callout \d|Sitelinks and callouts:)/.test(problem)
}

export function assetSummary(assets: readonly DraftAsset[]): string {
  const sitelinks = assets.filter((asset) => draftAssetType(asset) === "SITELINK").length
  const callouts = assets.length - sitelinks
  if (assets.length === 0) return "No sitelinks or callouts"
  return [
    sitelinks ? approvalCountLine(sitelinks, "sitelink") : null,
    callouts ? approvalCountLine(callouts, "callout") : null,
  ]
    .filter(Boolean)
    .join(", ")
}

/** Advice that doesn't block approval: one sitelink alone doesn't show. */
export function sitelinkAdvice(assets: readonly DraftAsset[]): string | null {
  const sitelinks = assets.filter((asset) => draftAssetType(asset) === "SITELINK").length
  return sitelinks > 0 && sitelinks < SITELINKS_TO_SHOW
    ? `Google shows sitelinks in pairs or more, so add at least ${String(SITELINKS_TO_SHOW)}.`
    : null
}
