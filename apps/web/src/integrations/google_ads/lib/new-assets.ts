// apps/web/src/integrations/google_ads/lib/new-assets.ts

import { collapseSpaces } from "@/integrations/ads/lib/keyword-notation"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import { isGoogleAdsUrl } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type AssetType = "SITELINK" | "CALLOUT"

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  CALLOUT: "Callout",
  SITELINK: "Sitelink",
}

// Each editable field's argument name, label, and character limit.
const SITELINK_FIELDS = [
  { key: "link_text", label: "Link Text", limit: 25 },
  { key: "description1", label: "Description 1", limit: 35 },
  { key: "description2", label: "Description 2", limit: 35 },
  { key: "final_url", label: "Final URL", limit: 2048 },
] as const
const CALLOUT_FIELDS = [{ key: "text", label: "Text", limit: 25 }] as const
export type AssetField = (typeof SITELINK_FIELDS)[number] | (typeof CALLOUT_FIELDS)[number]

export const ASSET_FIELDS: Record<AssetType, readonly AssetField[]> = {
  CALLOUT: CALLOUT_FIELDS,
  SITELINK: SITELINK_FIELDS,
}

// Google's limit for one campaign or ad group, as the tools take it.
export const MAX_ASSETS_PER_TARGET = 20
// Google shows no sitelinks to a campaign with one, and shows them best with four.
const SITELINKS_ADVISED = 4

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

function text(value: unknown): string {
  return typeof value === "string" ? collapseSpaces(value) : ""
}

/** The server's name for a new asset: its content as plain text, in a fixed order. */
export function newAssetKey(asset: DraftAsset): string {
  // The server names a date by its day, whatever time came with it.
  const dates = [text(asset["start_date"]).slice(0, 10), text(asset["end_date"]).slice(0, 10)]
  const parts =
    asset["type"] === "sitelink"
      ? [
          text(asset["link_text"]),
          text(asset["description1"]),
          text(asset["description2"]),
          typeof asset["final_url"] === "string" ? asset["final_url"].trim() : "",
        ]
      : [text(asset["text"])]
  return ["new", String(asset["type"]), ...parts, ...dates].join("|")
}

/** Why a new or edited asset's fields can't be sent, or null. */
export function fieldProblem(asset: DraftAsset): string | null {
  for (const field of ASSET_FIELDS[draftAssetType(asset)]) {
    const value = text(asset[field.key])
    const length = characterCount(value)
    const optional = field.key === "description1" || field.key === "description2"
    if (length === 0 && !optional) return `${field.label} is required.`
    if (length > field.limit)
      return `${field.label} is ${String(length)} of ${String(field.limit)} characters.`
    if (field.key === "final_url" && !isGoogleAdsUrl(value))
      return "Enter a complete web address, starting with https://."
  }
  if (asset["type"] === "sitelink" && !text(asset["description1"]) !== !text(asset["description2"]))
    return "Add both description lines, or neither."
  return null
}

/** When an asset can show, such as "From 2026-12-01 to 2026-12-24"; null when it has no dates. */
export function assetDatesText(start: unknown, end: unknown): string | null {
  const from = text(start).slice(0, 10)
  const to = text(end).slice(0, 10)
  if (from && to) return `From ${from} to ${to}`
  if (from) return `From ${from}`
  return to ? `Until ${to}` : null
}

export function blankIsNull(value: unknown): unknown {
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

/** The size and repeat rules for one campaign or ad group; each list holds its assets' keys. */
export function assetListProblems(
  subject: string,
  lists: readonly (readonly string[])[]
): string[] {
  const keys = lists.flat()
  return [
    ...(lists.some((list) => list.length > MAX_ASSETS_PER_TARGET)
      ? [`${subject}: at most ${String(MAX_ASSETS_PER_TARGET)} at a time.`]
      : []),
    ...(new Set(keys).size !== keys.length ? [`${subject}: list each one once.`] : []),
  ]
}

/** What the card can find without asking Google: field limits, repeats, and the count. */
export function newAssetProblems(assets: readonly DraftAsset[]): string[] {
  const labels = assetLabels(assets)
  return [
    ...assets.flatMap((asset, index) => {
      const problem = fieldProblem(asset)
      return problem ? [`${String(labels[index])}: ${problem}`] : []
    }),
    ...assetListProblems("Sitelinks and callouts", [assets.map(newAssetKey)]),
  ]
}

/** Google's rejections from the last check, once each, while the asset it rejected is still here. */
export function googleAssetProblems(
  assets: readonly DraftAsset[],
  problems: readonly AssetProblem[]
): string[] {
  const labels = new Map(
    assetLabels(assets).map((label, index) => [newAssetKey(assets[index] ?? {}), label])
  )
  const lines = problems.flatMap((problem) => {
    const label = labels.get(problem.key)
    return label ? [`${label}: ${problem.message}`] : []
  })
  return [...new Set(lines)]
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

/** Advice that doesn't block approval, for a campaign or ad group left with too few sitelinks. */
export function sitelinkAdvice(sitelinks: number): string | null {
  return sitelinks < SITELINKS_ADVISED
    ? `Google shows sitelinks only with 2 or more, and best with ${String(SITELINKS_ADVISED)} or more.`
    : null
}
