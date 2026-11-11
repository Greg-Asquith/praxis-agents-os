// apps/web/src/integrations/google_ads/lib/upload-media-result.ts

import type { DataTableTab } from "@/components/ui/data-table"
import type { ImageFieldType } from "@/integrations/google_ads/lib/upload-media"
import { FIELD_TYPE_LABELS } from "@/integrations/google_ads/lib/upload-media"
import { isNonEmptyString, isNonNegativeInteger, isOneOf, isRecord } from "@/lib/guards"

export type MediaOutcome = "uploaded" | "linked" | "failed" | "unverified"

export type MediaUploadRow = {
  kind: "image" | "youtube_video"
  name: string
  outcome: MediaOutcome
  recovered: boolean
  assetId: string | null
  fileId: string | null
  revisionId: string | null
  sizeBytes: number | null
  fits: ImageFieldType[]
  videoId: string | null
  errorCode: string | null
  message: string | null
}

export type UploadMediaResult = { accountId: string; uploads: MediaUploadRow[] }

export const MEDIA_OUTCOME_LABELS: Record<MediaOutcome, string> = {
  uploaded: "Uploaded",
  linked: "Linked",
  failed: "Failed",
  unverified: "Unconfirmed",
}

export const MEDIA_OUTCOME_BADGES = {
  uploaded: "success",
  linked: "success",
  failed: "destructive",
  unverified: "warning",
} as const

const OUTCOMES: ReadonlySet<MediaOutcome> = new Set(["uploaded", "linked", "failed", "unverified"])
const FIELD_TYPES: ReadonlySet<ImageFieldType> = new Set(
  Object.keys(FIELD_TYPE_LABELS) as ImageFieldType[]
)

function text(value: unknown): string | null {
  return isNonEmptyString(value) ? value : null
}

function parseUpload(value: unknown): MediaUploadRow | null {
  if (
    !isRecord(value) ||
    (value["kind"] !== "image" && value["kind"] !== "youtube_video") ||
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

function tab(id: MediaOutcome | "all"): DataTableTab {
  return {
    hideWhenEmpty: id !== "all",
    id,
    label: id === "all" ? "All" : MEDIA_OUTCOME_LABELS[id],
    match: (row) => id === "all" || row["token"] === id,
  }
}

// Result tables put each row's outcome in `token`.
export const MEDIA_OUTCOME_TABS: DataTableTab[] = [
  tab("all"),
  tab("uploaded"),
  tab("linked"),
  tab("failed"),
  tab("unverified"),
]
