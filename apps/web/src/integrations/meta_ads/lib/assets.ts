// apps/web/src/integrations/meta_ads/lib/assets.ts

import { isNonEmptyString, isOneOf, isRecord, isStringArray } from "@/lib/guards"

export const ASSET_SECTIONS = [
  { kind: "pages", title: "Facebook Pages", noun: "Facebook Pages", detail: null },
  {
    kind: "instagram_accounts",
    title: "Instagram Accounts",
    noun: "Instagram accounts",
    detail: null,
  },
  { kind: "images", title: "Images", noun: "images", detail: "Size" },
  { kind: "videos", title: "Videos", noun: "videos", detail: "Status" },
] as const

export type AssetSectionConfig = (typeof ASSET_SECTIONS)[number]

type AssetKind = AssetSectionConfig["kind"]

type MetaAdsAsset = {
  id: string
  label: string
  detail: string | null
}

export type MetaAdsAssets = Record<AssetKind, MetaAdsAsset[]> & {
  truncated: AssetKind[]
  notes: string[]
}

const KINDS: readonly AssetKind[] = ASSET_SECTIONS.map((section) => section.kind)
const KIND_SET: ReadonlySet<AssetKind> = new Set(KINDS)
const NOUN_LIST = new Intl.ListFormat("en", { type: "disjunction" })
const STATUS_LABELS: Record<string, string> = {
  ready: "Ready",
  processing: "Processing",
  failed: "Couldn't process",
}

export function parseMetaAdsAssets(value: unknown): MetaAdsAssets | null {
  if (!isRecord(value) || !isStringArray(value["notes"]) || !isStringArray(value["truncated"]))
    return null
  const truncated = value["truncated"].filter((kind) => isOneOf(KIND_SET, kind))
  const result: MetaAdsAssets = {
    pages: [],
    instagram_accounts: [],
    images: [],
    videos: [],
    truncated,
    notes: value["notes"],
  }
  for (const kind of KINDS) {
    const items = value[kind]
    if (!Array.isArray(items)) return null
    for (const item of items) {
      const asset = parseAsset(item, kind)
      if (!asset) return null
      result[kind].push(asset)
    }
  }
  return result
}

/** States what an empty read found without implying kinds that weren't requested or read. */
export function emptyAssetsMessage(result: MetaAdsAssets, args: unknown): string {
  if (result.notes.length > 0) return "Meta Ads returned nothing else for this ad account."
  const requested: readonly string[] =
    isRecord(args) && isStringArray(args["kinds"]) ? args["kinds"] : KINDS
  const names = ASSET_SECTIONS.filter((section) => requested.includes(section.kind))
  if (names.length === 0) return "Meta Ads returned nothing for this ad account."
  return `No ${NOUN_LIST.format(names.map((section) => section.noun))} found in this ad account.`
}

function parseAsset(value: unknown, kind: AssetKind): MetaAdsAsset | null {
  if (!isRecord(value) || !isNonEmptyString(value["label"])) return null
  const id = {
    pages: value["page_id"],
    instagram_accounts: value["instagram_user_id"],
    images: value["image_hash"],
    videos: value["video_id"],
  }[kind]
  if (!isNonEmptyString(id)) return null
  return { id, label: value["label"], detail: assetDetail(value, kind) }
}

function assetDetail(value: Record<string, unknown>, kind: AssetKind): string | null {
  if (kind === "images") {
    const { width, height } = value
    return typeof width === "number" && typeof height === "number"
      ? `${String(width)} × ${String(height)}`
      : null
  }
  if (kind === "videos") {
    const status = value["media_status"]
    const label = typeof status === "string" ? STATUS_LABELS[status] : undefined
    return label ?? "Status unknown"
  }
  return null
}
