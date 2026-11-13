// apps/web/src/integrations/google_ads/lib/upload-media-result.ts

import { outcomeTabs } from "@/integrations/google_ads/lib/edit-outcomes"
import { FIELD_TYPES, type ImageFieldType } from "@/integrations/google_ads/lib/upload-media"
import { isNonEmptyString, isNonNegativeInteger, isOneOf, isRecord } from "@/lib/guards"

export type MediaOutcome = "uploaded" | "linked" | "processing" | "failed" | "unverified"

// A `video` is a video File uploaded to YouTube, or an earlier upload finished.
export type MediaKind = "image" | "youtube_video" | "video"

export type MediaUploadRow = {
  kind: MediaKind
  name: string
  outcome: MediaOutcome
  recovered: boolean
  assetId: string | null
  fileId: string | null
  revisionId: string | null
  sizeBytes: number | null
  fits: ImageFieldType[]
  videoId: string | null
  // A video upload's ID, which finishes it later while Google processes it.
  uploadId: string | null
  // Whether Google was told the File was made or changed with AI; null when no File was sent.
  madeWithAi: boolean | null
  // What Google's own check says about the asset, when it says anything.
  googleMadeWithAi: boolean | null
  errorCode: string | null
  message: string | null
}

export type UploadMediaResult = { accountId: string; uploads: MediaUploadRow[] }

export const MEDIA_OUTCOME_LABELS: Record<MediaOutcome, string> = {
  uploaded: "Uploaded",
  linked: "Linked",
  processing: "Processing",
  failed: "Failed",
  unverified: "Unconfirmed",
}

export const MEDIA_OUTCOME_BADGES = {
  uploaded: "success",
  linked: "success",
  processing: "secondary",
  failed: "destructive",
  unverified: "warning",
} as const

const OUTCOMES: ReadonlySet<MediaOutcome> = new Set([
  "uploaded",
  "linked",
  "processing",
  "failed",
  "unverified",
])
const KINDS: ReadonlySet<MediaKind> = new Set(["image", "youtube_video", "video"])

function text(value: unknown): string | null {
  return isNonEmptyString(value) ? value : null
}

function parseUpload(value: unknown): MediaUploadRow | null {
  if (
    !isRecord(value) ||
    !isOneOf(KINDS, value["kind"]) ||
    !isNonEmptyString(value["name"]) ||
    !isOneOf(OUTCOMES, value["outcome"]) ||
    typeof value["recovered"] !== "boolean"
  )
    return null
  const asset = value["asset"]
  const fits = Array.isArray(value["fits"]) ? value["fits"] : []
  return {
    kind: value["kind"],
    name: value["name"],
    outcome: value["outcome"],
    recovered: value["recovered"],
    assetId: isRecord(asset) ? text(asset["asset_id"]) : null,
    fileId: text(value["file_id"]),
    revisionId: text(value["revision_id"]),
    sizeBytes: isNonNegativeInteger(value["size_bytes"]) ? value["size_bytes"] : null,
    fits: fits.filter((item) => isOneOf(FIELD_TYPES, item)),
    videoId: text(value["video_id"]),
    uploadId: text(value["upload_id"]),
    madeWithAi: typeof value["made_with_ai"] === "boolean" ? value["made_with_ai"] : null,
    googleMadeWithAi:
      typeof value["google_made_with_ai"] === "boolean" ? value["google_made_with_ai"] : null,
    errorCode: text(value["error_code"]),
    message: text(value["message"]),
  }
}

export function parseUploadMediaResult(value: unknown): UploadMediaResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["account_id"])) return null
  if (!Array.isArray(value["uploads"])) return null
  const uploads = value["uploads"].map(parseUpload)
  if (uploads.some((upload) => upload === null)) return null
  return {
    accountId: value["account_id"],
    uploads: uploads.filter((upload) => upload !== null),
  }
}

/** What Google was told about AI, and its own answer where that differs. */
export function aiDisclosureText(upload: MediaUploadRow): string {
  const told = upload.madeWithAi === null ? null : upload.madeWithAi ? "Made With AI" : "Not Marked"
  const google =
    upload.googleMadeWithAi === null || upload.googleMadeWithAi === (upload.madeWithAi ?? false)
      ? null
      : upload.googleMadeWithAi
        ? "Google marked it as made with AI"
        : "Google's check didn't find AI"
  return [told, google].filter(Boolean).join(" · ") || "—"
}

export function mediaOutcomeSummary(uploads: readonly MediaUploadRow[]): string {
  const totals = new Map<MediaOutcome, number>()
  for (const upload of uploads) totals.set(upload.outcome, (totals.get(upload.outcome) ?? 0) + 1)
  return [...totals]
    .map(
      ([outcome, total]) =>
        `${total.toLocaleString("en-GB")} ${MEDIA_OUTCOME_LABELS[outcome].toLowerCase()}`
    )
    .join(" · ")
}

export const MEDIA_OUTCOME_TABS = outcomeTabs(MEDIA_OUTCOME_LABELS, [
  "uploaded",
  "linked",
  "processing",
  "failed",
  "unverified",
])
