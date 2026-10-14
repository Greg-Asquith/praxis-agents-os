// apps/web/src/integrations/meta_ads/lib/assets.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { formatAudienceRange } from "@/integrations/meta_ads/lib/targeting"
import { urlDomain } from "@/lib/format"
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
  { kind: "posts", title: "Posts", noun: "posts", detail: "Text" },
  { kind: "pixels", title: "Pixels", noun: "pixels", detail: null },
  { kind: "apps", title: "Apps", noun: "apps", detail: "Stores" },
  { kind: "audiences", title: "Audiences", noun: "audiences", detail: "Size" },
] as const

export type AssetSectionConfig = (typeof ASSET_SECTIONS)[number]

type AssetKind = AssetSectionConfig["kind"]
type ReadKind = AssetKind | "dsa_suggestions"

type MetaAdsAsset = {
  id: string
  label: string
  detail: string | null
}

export type MetaAdsAssets = Record<AssetKind, MetaAdsAsset[]> & {
  dsaSuggestions: string[]
  truncated: ReadKind[]
  notes: string[]
}

const KINDS: readonly AssetKind[] = ASSET_SECTIONS.map((section) => section.kind)
const KIND_SET: ReadonlySet<ReadKind> = new Set([...KINDS, "dsa_suggestions"])
// Posts and targeting assets are listed only when asked for.
const DEFAULT_KINDS: readonly AssetKind[] = ["pages", "instagram_accounts", "images", "videos"]
const DSA_NOUN = { kind: "dsa_suggestions", noun: "suggested EU advertiser names" } as const
const NOUN_LIST = new Intl.ListFormat("en", { type: "disjunction" })
const STATUS_LABELS: Record<string, string> = {
  ready: "Ready",
  processing: "Processing",
  failed: "Couldn't process",
}
const STORES: Record<string, string> = {
  "apps.apple.com": "App Store",
  "itunes.apple.com": "App Store",
  "play.google.com": "Google Play",
}

export function parseMetaAdsAssets(value: unknown): MetaAdsAssets | null {
  if (
    !isRecord(value) ||
    !isStringArray(value["notes"]) ||
    !isStringArray(value["truncated"]) ||
    !isStringArray(value["dsa_suggestions"])
  )
    return null
  const truncated = value["truncated"].filter((kind) => isOneOf(KIND_SET, kind))
  const result: MetaAdsAssets = {
    pages: [],
    instagram_accounts: [],
    images: [],
    videos: [],
    posts: [],
    pixels: [],
    apps: [],
    audiences: [],
    dsaSuggestions: value["dsa_suggestions"],
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
    isRecord(args) && isStringArray(args["kinds"]) ? args["kinds"] : DEFAULT_KINDS
  const names = [...ASSET_SECTIONS, DSA_NOUN].filter((section) => requested.includes(section.kind))
  if (names.length === 0) return "Meta Ads returned nothing for this ad account."
  return `No ${NOUN_LIST.format(names.map((section) => section.noun))} found in this ad account.`
}

function parseAsset(value: unknown, kind: AssetKind): MetaAdsAsset | null {
  if (kind === "posts") return isRecord(value) ? parsePost(value) : null
  if (!isRecord(value) || !isNonEmptyString(value["label"])) return null
  const id = {
    pages: value["page_id"],
    instagram_accounts: value["instagram_user_id"],
    images: value["image_hash"],
    videos: value["video_id"],
    pixels: value["pixel_id"],
    apps: value["application_id"],
    audiences: value["audience_id"],
  }[kind]
  if (!isNonEmptyString(id)) return null
  return { id, label: value["label"], detail: assetDetail(value, kind) }
}

// A post's text is untrusted: it renders as plain text, like every other table cell.
function parsePost(value: Record<string, unknown>): MetaAdsAsset | null {
  const post = value["post"]
  if (!isRecord(post) || !isNonEmptyString(post["label"]) || !isNonEmptyString(post["post_id"]))
    return null
  const label =
    post["boostable"] === false ? `${post["label"]} (can't run as an ad)` : post["label"]
  return { id: post["post_id"], label, detail: nodeText(value["text"]) }
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
  if (kind === "apps") return appStores(value["store_urls"])
  if (kind === "audiences") return audienceSize(value)
  return null
}

function appStores(value: unknown): string {
  const stores = new Set(
    (isStringArray(value) ? value : []).flatMap((url) => {
      const store = STORES[urlDomain(url) ?? ""]
      return store ? [store] : []
    })
  )
  return stores.size > 0 ? [...stores].join(", ") : "No store page"
}

function audienceSize(value: Record<string, unknown>): string {
  const kind = typeof value["description"] === "string" ? `${value["description"]}, ` : ""
  const range = formatAudienceRange(value["size_lower_bound"], value["size_upper_bound"])
  return `${kind}${range ?? "size unknown"}`
}
