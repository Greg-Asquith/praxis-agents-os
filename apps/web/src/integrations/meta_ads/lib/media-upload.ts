// apps/web/src/integrations/meta_ads/lib/media-upload.ts

import { pluralize } from "@/lib/format"
import { isNonEmptyString, isNonNegativeInteger, isOneOf, isRecord } from "@/lib/guards"

export type MediaType = "image" | "video"

type ReviewedFile = {
  revisionId: string
  name: string
  mediaType: MediaType
  sizeBytes: number
}

type UploadFile = {
  id: string
  label: string
  // The server's check and pin of this File; null until the edited list is checked.
  reviewed: ReviewedFile | null
}

export type MediaUploadArgs = {
  files: UploadFile[]
  accountName: string | null
  // True when the File list differs from the one the server last checked and pinned.
  needsReview: boolean
}

type MediaUploadOutcome = "uploaded" | "processing" | "failed" | "unverified"

type MediaUpload = {
  fileId: string
  revisionId: string
  name: string
  mediaType: MediaType
  outcome: MediaUploadOutcome
  recovered: boolean
  // Image hash or video ID Meta returned; null when the upload wasn't proved.
  mediaId: string | null
  errorCode: string | null
  message: string | null
}

export type MediaUploadResult = {
  accountId: string
  uploads: MediaUpload[]
}

const MEDIA_TYPES: ReadonlySet<MediaType> = new Set(["image", "video"])
const OUTCOMES: ReadonlySet<MediaUploadOutcome> = new Set([
  "uploaded",
  "processing",
  "failed",
  "unverified",
])

export function parseMediaUploadArgs(value: unknown): MediaUploadArgs | null {
  if (!isRecord(value) || !Array.isArray(value["files"]) || value["files"].length === 0) return null
  const reviewed = reviewedFiles(value["_files"])
  const files: UploadFile[] = []
  for (const item of value["files"]) {
    if (!isRecord(item) || !isNonEmptyString(item["entity_id"])) return null
    if (item["entity_kind"] !== undefined && item["entity_kind"] !== "file") return null
    const id = item["entity_id"]
    files.push({
      id,
      label: isNonEmptyString(item["label"]) ? item["label"] : "Workspace File",
      reviewed: reviewed?.get(id) ?? null,
    })
  }
  return {
    files,
    accountName: isNonEmptyString(value["_account_name"]) ? value["_account_name"] : null,
    needsReview: !matchesPinned(files, reviewed),
  }
}

// True only for the pinned Files in the pinned order.
function matchesPinned(files: UploadFile[], reviewed: Map<string, ReviewedFile> | null): boolean {
  const reviewedIds = reviewed ? [...reviewed.keys()] : []
  return (
    reviewedIds.length === files.length &&
    files.every((file, index) => reviewedIds[index] === file.id)
  )
}

function reviewedFiles(value: unknown): Map<string, ReviewedFile> | null {
  if (!Array.isArray(value)) return null
  const files = new Map<string, ReviewedFile>()
  for (const item of value) {
    if (
      !isRecord(item) ||
      !isNonEmptyString(item["file_id"]) ||
      !isNonEmptyString(item["revision_id"]) ||
      !isNonEmptyString(item["content_hash"]) ||
      !isNonEmptyString(item["name"]) ||
      !isOneOf(MEDIA_TYPES, item["media_type"]) ||
      !isNonNegativeInteger(item["size_bytes"])
    )
      return null
    files.set(item["file_id"], {
      revisionId: item["revision_id"],
      name: item["name"],
      mediaType: item["media_type"],
      sizeBytes: item["size_bytes"],
    })
  }
  return files
}

export function parseMediaUploadResult(value: unknown): MediaUploadResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !Array.isArray(value["uploads"])
  )
    return null
  const uploads: MediaUpload[] = []
  for (const item of value["uploads"]) {
    const upload = parseUpload(item)
    if (!upload) return null
    uploads.push(upload)
  }
  return { accountId: value["account_id"], uploads }
}

function parseUpload(value: unknown): MediaUpload | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["file_id"]) ||
    !isNonEmptyString(value["revision_id"]) ||
    !isNonEmptyString(value["name"]) ||
    !isOneOf(MEDIA_TYPES, value["media_type"]) ||
    !isOneOf(OUTCOMES, value["outcome"]) ||
    typeof value["recovered"] !== "boolean"
  )
    return null
  return {
    fileId: value["file_id"],
    revisionId: value["revision_id"],
    name: value["name"],
    mediaType: value["media_type"],
    outcome: value["outcome"],
    recovered: value["recovered"],
    mediaId: mediaId(value["media"], value["media_type"]),
    errorCode: isNonEmptyString(value["error_code"]) ? value["error_code"] : null,
    message: isNonEmptyString(value["message"]) ? value["message"] : null,
  }
}

export function uploadCountLine(files: readonly { mediaType: MediaType }[]): string {
  const images = files.filter((file) => file.mediaType === "image").length
  const videos = files.length - images
  return [
    images ? `${String(images)} ${pluralize(images, "image")}` : null,
    videos ? `${String(videos)} ${pluralize(videos, "video")}` : null,
  ]
    .filter(Boolean)
    .join(" and ")
}

function mediaId(value: unknown, mediaType: MediaType): string | null {
  if (!isRecord(value) || value["media_type"] !== mediaType) return null
  const id = mediaType === "image" ? value["image_hash"] : value["video_id"]
  return isNonEmptyString(id) ? id : null
}
