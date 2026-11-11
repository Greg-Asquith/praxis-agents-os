// apps/web/src/integrations/google_ads/lib/upload-media.ts

import { parseApprovalAccounts } from "@/integrations/google_ads/lib/accounts"
import { pluralize } from "@/lib/format"
import { isNonEmptyString, isNonNegativeInteger, isOneOf, isRecord } from "@/lib/guards"

export type ImageFieldType =
  | "MARKETING_IMAGE"
  | "SQUARE_MARKETING_IMAGE"
  | "PORTRAIT_MARKETING_IMAGE"
  | "LOGO"
  | "LANDSCAPE_LOGO"

const FIELD_TYPE_LABELS: Record<ImageFieldType, string> = {
  MARKETING_IMAGE: "Landscape",
  SQUARE_MARKETING_IMAGE: "Square",
  PORTRAIT_MARKETING_IMAGE: "Portrait",
  LOGO: "Logo",
  LANDSCAPE_LOGO: "Landscape Logo",
}

export const FIELD_TYPES: ReadonlySet<ImageFieldType> = new Set(
  Object.keys(FIELD_TYPE_LABELS) as ImageFieldType[]
)

// The server's check of one File; null until an edited list is checked.
type ImageCheck = {
  revisionId: string
  name: string
  sizeBytes: number
  width: number | null
  height: number | null
  fits: ImageFieldType[]
  tooSmall: ImageFieldType[]
  // Why Google won't take it, which blocks approval.
  problem: string | null
  // The check as the server sent it, kept so a cancelled row survives a review.
  raw: Record<string, unknown>
}

export type ImageRow = {
  id: string
  label: string
  check: ImageCheck | null
  cancelled: boolean
  // The reference as sent, so edits keep it whole.
  raw: Record<string, unknown>
}

export type UploadMediaArgs = {
  images: ImageRow[]
  videos: string[]
  accountName: string | null
  // True when the File list differs from the one the server last checked.
  needsReview: boolean
}

export const MAX_IMAGES = 20
export const MAX_VIDEOS = 20

const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/
const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
])
const YOUTUBE_PATHS = new Set(["shorts", "embed", "live", "v"])

/** The video ID in a YouTube link or bare ID, matching the server's reading; null otherwise. */
export function youtubeVideoId(value: string): string | null {
  const text = value.trim()
  if (YOUTUBE_ID.test(text)) return text
  let url: URL
  try {
    url = new URL(text.includes("://") ? text : `https://${text}`)
  } catch {
    return null
  }
  const host = url.hostname.toLowerCase()
  const parts = url.pathname.split("/").filter(Boolean)
  let candidate = ""
  if (host === "youtu.be") candidate = parts[0] ?? ""
  else if (YOUTUBE_HOSTS.has(host) && url.pathname === "/watch")
    candidate = url.searchParams.get("v") ?? ""
  else if (YOUTUBE_HOSTS.has(host) && parts.length >= 2 && YOUTUBE_PATHS.has(parts[0] ?? ""))
    candidate = parts[1] ?? ""
  return YOUTUBE_ID.test(candidate) ? candidate : null
}

export function parseUploadMediaArgs(value: unknown, retained?: unknown): UploadMediaArgs | null {
  if (!isRecord(value)) return null
  const files = value["files"] ?? []
  const videos = value["youtube_videos"] ?? []
  if (!Array.isArray(files) || !Array.isArray(videos)) return null
  if (!videos.every((video) => typeof video === "string")) return null
  const checks = parseChecks(value["_files"])
  const images: ImageRow[] = []
  for (const item of files) {
    const id = referenceId(item)
    if (id === null || !isRecord(item)) return null
    images.push({
      id,
      label: isNonEmptyString(item["label"]) ? item["label"] : "Workspace File",
      check: checks?.get(id) ?? null,
      cancelled: false,
      raw: item,
    })
  }
  const live = new Set(images.map((image) => image.id))
  const cancelled = parseCancelled(retained).filter((image) => !live.has(image.id))
  const checkedIds = checks ? [...checks.keys()] : []
  const [account] = parseApprovalAccounts(value["_accounts"]).values()
  return {
    images: [...images, ...cancelled],
    videos,
    accountName: account?.label ?? null,
    needsReview:
      checkedIds.length !== images.length ||
      images.some((image, index) => checkedIds[index] !== image.id),
  }
}

function referenceId(value: unknown): string | null {
  if (!isRecord(value) || !isNonEmptyString(value["entity_id"])) return null
  if (value["entity_kind"] !== undefined && value["entity_kind"] !== "file") return null
  return value["entity_id"]
}

function fieldTypes(value: unknown): ImageFieldType[] {
  return Array.isArray(value) ? value.filter((item) => isOneOf(FIELD_TYPES, item)) : []
}

function dimension(value: unknown): number | null {
  return isNonNegativeInteger(value) && value > 0 ? value : null
}

function parseCheck(item: unknown): ImageCheck | null {
  if (
    !isRecord(item) ||
    !isNonEmptyString(item["revision_id"]) ||
    !isNonEmptyString(item["name"]) ||
    !isNonNegativeInteger(item["size_bytes"])
  )
    return null
  return {
    revisionId: item["revision_id"],
    name: item["name"],
    sizeBytes: item["size_bytes"],
    width: dimension(item["width"]),
    height: dimension(item["height"]),
    fits: fieldTypes(item["fits"]),
    tooSmall: fieldTypes(item["too_small"]),
    problem: isNonEmptyString(item["problem"]) ? item["problem"] : null,
    raw: item,
  }
}

function parseChecks(value: unknown): Map<string, ImageCheck> | null {
  if (!Array.isArray(value)) return null
  const checks = new Map<string, ImageCheck>()
  for (const item of value) {
    const check = parseCheck(item)
    if (!check || !isRecord(item) || !isNonEmptyString(item["file_id"])) return null
    checks.set(item["file_id"], check)
  }
  return checks
}

function parseCancelled(value: unknown): ImageRow[] {
  if (!isRecord(value) || !Array.isArray(value["images"])) return []
  return value["images"].flatMap((item: unknown) => {
    if (!isRecord(item) || !isRecord(item["ref"])) return []
    const id = referenceId(item["ref"])
    if (id === null) return []
    const ref = item["ref"]
    return [
      {
        id,
        label: isNonEmptyString(ref["label"]) ? ref["label"] : "Workspace File",
        check: parseCheck(item["check"]),
        cancelled: true,
        raw: ref,
      },
    ]
  })
}

/** What the card keeps across a review: each cancelled image with its last check. */
export function serializeCancelled(images: readonly ImageRow[]): Record<string, unknown> {
  return {
    images: images
      .filter((image) => image.cancelled)
      .map((image) => ({ ref: image.raw, check: image.check?.raw ?? null })),
  }
}

/** Cancels or restores images; returns the File list to send and the rows to keep. */
export function editImages(
  images: readonly ImageRow[],
  ids: ReadonlySet<string>,
  cancelled: boolean
): { files: Record<string, unknown>[]; rows: ImageRow[] } {
  const rows = images.map((image) => (ids.has(image.id) ? { ...image, cancelled } : image))
  return { files: rows.filter((row) => !row.cancelled).map((row) => row.raw), rows }
}

export type UploadCounts = {
  images: number
  videos: number
  problems: number
  badVideos: number
  repeatedVideos: boolean
}

export function uploadCounts(args: UploadMediaArgs): UploadCounts {
  const live = args.images.filter((image) => !image.cancelled)
  const ids = args.videos.map(youtubeVideoId)
  const valid = ids.filter((id): id is string => id !== null)
  return {
    images: live.length,
    videos: valid.length,
    problems: live.filter((image) => image.check?.problem).length,
    badVideos: ids.length - valid.length,
    repeatedVideos: new Set(valid).size !== valid.length,
  }
}

/** Why the request can't be approved yet, or null. */
export function uploadBlock(args: UploadMediaArgs | null): string | null {
  if (args === null) return null
  const counts = uploadCounts(args)
  if (counts.images + counts.videos + counts.badVideos === 0)
    return "Every upload is cancelled. Decline this request, or undo one."
  if (args.needsReview) return "Click Check Files so the changed Files are checked, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${String(counts.problems)} ${pluralize(counts.problems, "image")} to continue.`
  if (counts.badVideos > 0) return "Enter a YouTube link or video ID for each video."
  if (counts.repeatedVideos) return "List each YouTube video once."
  return null
}

function countPhrase(count: number, noun: string): string {
  return `${count.toLocaleString("en-GB")} ${pluralize(count, noun)}`
}

export function uploadApproveLabel(args: UploadMediaArgs): string {
  const counts = uploadCounts(args)
  const parts = [
    counts.images ? `Upload ${countPhrase(counts.images, "Image")}` : null,
    counts.videos ? `Link ${countPhrase(counts.videos, "Video")}` : null,
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(" and ") : "Upload"
}

export function uploadPrompt(args: UploadMediaArgs): string {
  const counts = uploadCounts(args)
  const what = [
    counts.images ? `upload ${countPhrase(counts.images, "image")}` : null,
    counts.videos ? `link ${countPhrase(counts.videos, "YouTube video")}` : null,
  ]
    .filter(Boolean)
    .join(" and ")
  const sentence = what ? what.charAt(0).toUpperCase() + what.slice(1) : "Upload media"
  return `${sentence} in ${args.accountName ?? "the selected Google Ads account"}. This doesn't add them to campaigns or spend money.`
}

/** Where an image fits, and the shapes it has but is too small for. */
export function fitsText(
  fits: readonly ImageFieldType[],
  tooSmall: readonly ImageFieldType[] = []
) {
  const shapes = fits.map((type) => FIELD_TYPE_LABELS[type]).join(", ") || "No ad shape"
  return tooSmall.length > 0
    ? `${shapes} · too small for ${tooSmall.map((type) => FIELD_TYPE_LABELS[type]).join(", ")}`
    : shapes
}

export function kilobytes(bytes: number): string {
  return `${Math.ceil(bytes / 1024).toLocaleString("en-GB")} KB`
}
