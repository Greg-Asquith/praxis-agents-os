// apps/web/src/integrations/meta_ads/lib/create-ads-args.ts

import {
  AD_FORMATS,
  parseAutomaticChanges,
  type AdFormat,
  type AutomaticChange,
} from "@/integrations/meta_ads/lib/automatic-changes"
import { parseButtonLists, type ButtonLists } from "@/integrations/meta_ads/lib/call-to-action"
import { pluralize } from "@/lib/format"
import {
  isNonEmptyString,
  isNonNegativeInteger,
  isOneOf,
  isRecord,
  isStringArray,
  stringValue,
} from "@/lib/guards"

export type AdStatus = "paused" | "active"

export type PreviewMedia = {
  key: string
  mediaType: "image" | "video"
  label: string
  width: number | null
  height: number | null
  // False for a library video Meta is still processing.
  ready: boolean
  // Set for workspace Files; the revision is null for a File chosen on the card.
  fileId: string | null
  revisionId: string | null
}

// A media reference as the ads argument holds it: a workspace File or library media.
export type MediaValue = Record<string, unknown>
export type MediaSlot = "media" | "vertical_media"

export type Card = {
  media: PreviewMedia
  headline: string
  description: string | null
  link: string | null
  callToAction: string | null
}

export type AdDraft = {
  index: number
  name: string
  format: AdFormat
  adSetIds: string[]
  primaryText: string
  headline: string | null
  description: string | null
  media: PreviewMedia | null
  verticalMedia: PreviewMedia | null
  cards: Card[]
  disclaimer: { type: string; text: string; url: string | null } | null
  // Values this ad sets for itself; null uses the shared value.
  overrides: {
    link: string | null
    callToAction: string | null
    urlTags: string | null
    status: AdStatus | null
  }
}

export type AdSetInfo = {
  id: string
  name: string
  status: string | null
  effectiveStatus: string | null
  objective: string | null
  budget: {
    kind: "daily" | "lifetime" | "campaign"
    amount: string | null
    period: string | null
  } | null
}

export type CreateAdsArgs = {
  // The ad account's ID as the conversation's context names it, for media previews.
  accountId: string | null
  accountName: string | null
  currency: string | null
  pageName: string
  pageId: string | null
  instagramName: string | null
  shared: {
    link: string | null
    callToAction: string | null
    urlTags: string | null
    status: AdStatus
  }
  ads: AdDraft[]
  adSets: Map<string, AdSetInfo>
  enabledChanges: string[]
  catalogue: AutomaticChange[]
  buttons: ButtonLists
  // The ads argument as sent, so edits keep every field the card doesn't change.
  rawAds: Record<string, unknown>[]
}

export const FORMAT_LABELS = { image: "Image", video: "Video", carousel: "Carousel" } as const

// Meta's recommended lengths; longer text is cut off with "See more".
export const RECOMMENDED_LENGTHS = {
  primaryText: 125,
  headline: 40,
  description: 30,
  cardHeadline: 35,
  cardDescription: 30,
} as const
export const MIN_CARDS = 2
export const MAX_CARDS = 10
export const STATUSES: ReadonlySet<AdStatus> = new Set(["paused", "active"])
const BUDGET_KINDS: ReadonlySet<"daily" | "lifetime" | "campaign"> = new Set([
  "daily",
  "lifetime",
  "campaign",
])

export function parseCreateAdsArgs(value: unknown): CreateAdsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["ads"]) || value["ads"].length === 0) return null
  const catalogue = parseAutomaticChanges(value["_automatic_change_catalogue"])
  const buttons = parseButtonLists(value["_buttons"])
  const page = value["page"]
  if (!catalogue || !buttons || !isRecord(page) || !isNonEmptyString(page["label"])) return null
  const media = mediaLookup(value["_media"], value["_files"])
  const rawAds: Record<string, unknown>[] = []
  const ads: AdDraft[] = []
  for (const [index, item] of value["ads"].entries()) {
    const ad = isRecord(item) ? parseAd(item, index, media) : null
    if (!ad || !isRecord(item)) return null
    rawAds.push(item)
    ads.push(ad)
  }
  const instagram = value["instagram_account"]
  const status = value["status"] ?? "paused"
  if (!isOneOf(STATUSES, status)) return null
  const account = value["_account"]
  return {
    accountId: isRecord(account) ? stringValue(account["account_id"]) : null,
    accountName: stringValue(value["_account_name"]),
    currency: stringValue(value["_currency"]),
    pageName: page["label"],
    pageId: stringValue(page["page_id"]),
    instagramName: isRecord(instagram) ? stringValue(instagram["label"]) : null,
    shared: {
      link: stringValue(value["link"]),
      callToAction: stringValue(value["call_to_action"]),
      urlTags: stringValue(value["url_tags"]),
      status,
    },
    ads,
    adSets: adSetLookup(value["_ad_sets"]),
    enabledChanges: isStringArray(value["automatic_changes"]) ? value["automatic_changes"] : [],
    catalogue,
    buttons,
    rawAds,
  }
}

function parseAd(
  item: Record<string, unknown>,
  index: number,
  media: Map<string, PreviewMedia>
): AdDraft | null {
  const format = item["format"]
  const adSets = item["ad_sets"]
  if (
    !isOneOf(AD_FORMATS, format) ||
    typeof item["name"] !== "string" ||
    typeof item["primary_text"] !== "string" ||
    !Array.isArray(adSets)
  )
    return null
  const adSetIds = adSets.flatMap((adSet) =>
    isRecord(adSet) && isNonEmptyString(adSet["adset_id"]) ? [adSet["adset_id"]] : []
  )
  if (adSetIds.length !== adSets.length || adSetIds.length === 0) return null
  const cards: Card[] = []
  for (const card of Array.isArray(item["cards"]) ? item["cards"] : []) {
    const cardMedia = isRecord(card) ? previewMedia(card["media"], media) : null
    if (!isRecord(card) || !cardMedia || typeof card["headline"] !== "string") return null
    cards.push({
      media: cardMedia,
      headline: card["headline"],
      description: stringValue(card["description"]),
      link: stringValue(card["link"]),
      callToAction: stringValue(card["call_to_action"]),
    })
  }
  const status = item["status"]
  const disclaimer = item["disclaimer"]
  return {
    index,
    name: item["name"],
    format,
    adSetIds,
    primaryText: item["primary_text"],
    headline: stringValue(item["headline"]),
    description: stringValue(item["description"]),
    media: previewMedia(item["media"], media),
    verticalMedia: previewMedia(item["vertical_media"], media),
    cards,
    disclaimer:
      isRecord(disclaimer) &&
      isNonEmptyString(disclaimer["type"]) &&
      isNonEmptyString(disclaimer["text"])
        ? {
            type: disclaimer["type"],
            text: disclaimer["text"],
            url: stringValue(disclaimer["url"]),
          }
        : null,
    overrides: {
      link: stringValue(item["link"]),
      callToAction: stringValue(item["call_to_action"]),
      urlTags: stringValue(item["url_tags"]),
      status: isOneOf(STATUSES, status) ? status : null,
    },
  }
}

// Builds the same keys the server uses: file:ID, image:HASH, or video:ID.
function mediaKey(value: Record<string, unknown>): string | null {
  if (value["entity_kind"] === "file") {
    return isNonEmptyString(value["entity_id"]) ? `file:${value["entity_id"]}` : null
  }
  if (isNonEmptyString(value["image_hash"])) return `image:${value["image_hash"]}`
  return isNonEmptyString(value["video_id"]) ? `video:${value["video_id"]}` : null
}

/** Builds a media input's preview, from what the card hydrated when it's known. */
export function previewMedia(
  value: unknown,
  media: ReadonlyMap<string, PreviewMedia> = new Map()
): PreviewMedia | null {
  if (!isRecord(value)) return null
  const key = mediaKey(value)
  if (!key) return null
  const known = media.get(key)
  if (known) return known
  const isFile = value["entity_kind"] === "file"
  return {
    key,
    mediaType: isFile || key.startsWith("image:") ? "image" : "video",
    label: stringValue(value["label"]) ?? "Media",
    width: dimension(value["width"]),
    height: dimension(value["height"]),
    ready: isReady(value["media_status"]),
    fileId: isFile ? stringValue(value["entity_id"]) : null,
    revisionId: null,
  }
}

function isReady(status: unknown): boolean {
  return status === undefined || status === null || status === "ready"
}

function mediaLookup(library: unknown, files: unknown): Map<string, PreviewMedia> {
  const media = new Map<string, PreviewMedia>()
  if (isRecord(library)) {
    for (const [key, item] of Object.entries(library)) {
      if (!isRecord(item)) continue
      media.set(key, {
        key,
        mediaType: item["media_type"] === "video" ? "video" : "image",
        label: stringValue(item["label"]) ?? "Media",
        width: dimension(item["width"]),
        height: dimension(item["height"]),
        ready: isReady(item["media_status"]),
        fileId: null,
        revisionId: null,
      })
    }
  }
  for (const item of Array.isArray(files) ? files : []) {
    if (!isRecord(item) || !isNonEmptyString(item["file_id"])) continue
    const key = `file:${item["file_id"]}`
    media.set(key, {
      key,
      mediaType: "image",
      label: stringValue(item["name"]) ?? "Workspace File",
      width: null,
      height: null,
      ready: true,
      fileId: item["file_id"],
      revisionId: stringValue(item["revision_id"]),
    })
  }
  return media
}

export function adSetName(args: CreateAdsArgs, adSetId: string): string {
  return args.adSets.get(adSetId)?.name ?? `Ad set ${adSetId}`
}

function adSetLookup(value: unknown): Map<string, AdSetInfo> {
  const adSets = new Map<string, AdSetInfo>()
  if (!isRecord(value)) return adSets
  for (const [id, item] of Object.entries(value)) {
    if (!isRecord(item)) continue
    const budget = item["budget"]
    adSets.set(id, {
      id,
      name: stringValue(item["label"]) ?? `Ad set ${id}`,
      status: stringValue(item["status"]),
      effectiveStatus: stringValue(item["effective_status"]),
      objective: stringValue(item["objective"]),
      budget:
        isRecord(budget) && isOneOf(BUDGET_KINDS, budget["kind"])
          ? {
              kind: budget["kind"],
              amount: stringValue(budget["amount"]),
              period: stringValue(budget["period"]),
            }
          : null,
    })
  }
  return adSets
}

function dimension(value: unknown): number | null {
  return isNonNegativeInteger(value) && value > 0 ? value : null
}

export function adCount(args: CreateAdsArgs): number {
  return args.ads.reduce((total, ad) => total + ad.adSetIds.length, 0)
}

export function approvalSummary(args: CreateAdsArgs): string {
  const ads = adCount(args)
  const adSets = new Set(args.ads.flatMap((ad) => ad.adSetIds)).size
  const identity = args.instagramName
    ? `as ${args.pageName} on Facebook and ${args.instagramName} on Instagram`
    : `as ${args.pageName}`
  return `Create ${String(ads)} ${pluralize(ads, "ad")} in ${String(adSets)} ${pluralize(adSets, "ad set")}${args.accountName ? ` in ${args.accountName}` : ""}, ${identity}.`
}

/** Shows where Meta cuts text off: the part that's shown, and whether more is hidden. */
export function cutOff(text: string, limit: number): { shown: string; hidden: boolean } {
  return text.length > limit
    ? { shown: text.slice(0, limit).trimEnd(), hidden: true }
    : { shown: text, hidden: false }
}

/** Keys each card by its media, so a moved card keeps its inputs and focus. */
export function cardKeys(cards: readonly { media: PreviewMedia }[]): string[] {
  const seen = new Map<string, number>()
  return cards.map((card) => {
    const count = seen.get(card.media.key) ?? 0
    seen.set(card.media.key, count + 1)
    return `${card.media.key}#${String(count)}`
  })
}
