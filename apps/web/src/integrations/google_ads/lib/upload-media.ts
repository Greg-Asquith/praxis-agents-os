// apps/web/src/integrations/google_ads/lib/upload-media.ts

import { parseApprovalAccounts } from "@/integrations/google_ads/lib/accounts"
import { formatBytes, pluralize } from "@/lib/format"
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
type FileCheck = {
  kind: "image" | "video"
  revisionId: string
  name: string
  sizeBytes: number
  width: number | null
  height: number | null
  fits: ImageFieldType[]
  tooSmall: ImageFieldType[]
  // A video's length when the media renderer measured it, and its title before any edit.
  durationMs: number | null
  defaultTitle: string | null
  // Why Google won't take it, which blocks approval.
  problem: string | null
  // The check as the server sent it, kept so a cancelled row survives a review.
  raw: Record<string, unknown>
}

export type FileRow = {
  id: string
  label: string
  check: FileCheck | null
  cancelled: boolean
  // The reference as sent, so edits keep it whole.
  raw: Record<string, unknown>
}

// A video File's YouTube title and description, as edited on the card.
export type VideoText = { title: string; description: string }

export type UploadMediaArgs = {
  files: FileRow[]
  videos: string[]
  // Edited titles and descriptions by File ID; a video without one uses its default title.
  videoText: ReadonlyMap<string, VideoText>
  // Earlier uploads that were still processing, to finish now.
  uploads: string[]
  // The Files Google is told were made or changed with AI.
  madeWithAi: ReadonlySet<string>
  accountName: string | null
  // True when the File list differs from the one the server last checked.
  needsReview: boolean
}

export const MAX_FILES = 20
export const MAX_VIDEOS = 20
export const MAX_UPLOADS = 20
export const MAX_TITLE = 100
export const MAX_DESCRIPTION = 5000
const UPLOAD_ID = /^(?:customers\/\d+\/youTubeVideoUploads\/)?\d{1,32}$/

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

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}

export function parseUploadMediaArgs(value: unknown, retained?: unknown): UploadMediaArgs | null {
  if (!isRecord(value)) return null
  const references = value["files"] ?? []
  const videos = value["youtube_videos"] ?? []
  const uploads = value["video_uploads"] ?? []
  const madeWithAi = value["made_with_ai"] ?? []
  if (
    !Array.isArray(references) ||
    !isStringList(videos) ||
    !isStringList(uploads) ||
    !isStringList(madeWithAi)
  )
    return null
  const videoText = parseVideoText(value["video_details"])
  if (videoText === null) return null
  const checks = parseChecks(value["_files"])
  const files: FileRow[] = []
  for (const item of references) {
    const id = referenceId(item)
    if (id === null || !isRecord(item)) return null
    files.push({
      id,
      label: isNonEmptyString(item["label"]) ? item["label"] : "Workspace File",
      check: checks?.get(id) ?? null,
      cancelled: false,
      raw: item,
    })
  }
  const live = new Set(files.map((file) => file.id))
  const cancelled = parseCancelled(retained).filter((file) => !live.has(file.id))
  const checkedIds = checks ? [...checks.keys()] : []
  const [account] = parseApprovalAccounts(value["_accounts"]).values()
  return {
    files: [...files, ...cancelled],
    videos,
    videoText,
    uploads,
    madeWithAi: new Set(madeWithAi),
    accountName: account?.label ?? null,
    needsReview:
      checkedIds.length !== files.length ||
      files.some((file, index) => checkedIds[index] !== file.id),
  }
}

function parseVideoText(value: unknown): Map<string, VideoText> | null {
  const text = new Map<string, VideoText>()
  if (value === undefined || value === null) return text
  if (!Array.isArray(value)) return null
  for (const item of value) {
    if (!isRecord(item) || !isNonEmptyString(item["file_id"]) || typeof item["title"] !== "string")
      return null
    const description = typeof item["description"] === "string" ? item["description"] : ""
    text.set(item["file_id"], { title: item["title"], description })
  }
  return text
}

/** A video File's title and description: the edited ones, or its default title. */
export function videoTextFor(args: UploadMediaArgs, file: FileRow): VideoText {
  return (
    args.videoText.get(file.id) ?? {
      title: file.check?.defaultTitle ?? file.label.slice(0, MAX_TITLE),
      description: "",
    }
  )
}

/** Sets one video's title or description; returns `video_details` for live video Files. */
export function editVideoText(
  args: UploadMediaArgs,
  fileId: string,
  change: Partial<VideoText>
): Record<string, unknown>[] {
  return liveVideos(args).map((file) => {
    const text = { ...videoTextFor(args, file), ...(file.id === fileId ? change : {}) }
    return {
      file_id: file.id,
      title: text.title,
      ...(text.description ? { description: text.description } : {}),
    }
  })
}

/** `video_details` for the videos still in `rows`, so a cancelled video's title goes too. */
export function keptVideoText(
  args: UploadMediaArgs,
  rows: readonly FileRow[]
): Record<string, unknown>[] {
  const live = new Set(rows.filter((row) => !row.cancelled).map((row) => row.id))
  return [...args.videoText]
    .filter(([fileId]) => live.has(fileId))
    .map(([fileId, text]) => ({
      file_id: fileId,
      title: text.title,
      ...(text.description ? { description: text.description } : {}),
    }))
}

/** `made_with_ai` for the Files still in `rows`, with `toggled` marked or cleared. */
export function madeWithAiIds(
  args: UploadMediaArgs,
  rows: readonly FileRow[],
  toggled?: string
): string[] {
  return rows
    .filter((row) => !row.cancelled && args.madeWithAi.has(row.id) !== (row.id === toggled))
    .map((row) => row.id)
}

/** Why a title or description can't go to YouTube, or null. */
export function videoTextProblem(text: VideoText): string | null {
  if (!text.title.trim()) return "Enter a title."
  if (text.title.length > MAX_TITLE) return `Titles take up to ${String(MAX_TITLE)} characters.`
  if (text.description.length > MAX_DESCRIPTION)
    return `Descriptions take up to ${MAX_DESCRIPTION.toLocaleString("en-GB")} characters.`
  if (/[<>]/.test(text.title + text.description))
    return "Titles and descriptions can't contain < or >."
  return null
}

function liveVideos(args: UploadMediaArgs): FileRow[] {
  return args.files.filter((file) => !file.cancelled && file.check?.kind === "video")
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

function parseCheck(item: unknown): FileCheck | null {
  if (
    !isRecord(item) ||
    !isNonEmptyString(item["revision_id"]) ||
    !isNonEmptyString(item["name"]) ||
    !isNonNegativeInteger(item["size_bytes"])
  )
    return null
  return {
    kind: item["kind"] === "video" ? "video" : "image",
    revisionId: item["revision_id"],
    name: item["name"],
    sizeBytes: item["size_bytes"],
    width: dimension(item["width"]),
    height: dimension(item["height"]),
    fits: fieldTypes(item["fits"]),
    tooSmall: fieldTypes(item["too_small"]),
    durationMs: isNonNegativeInteger(item["duration_ms"]) ? item["duration_ms"] : null,
    defaultTitle: isNonEmptyString(item["default_title"]) ? item["default_title"] : null,
    problem: isNonEmptyString(item["problem"]) ? item["problem"] : null,
    raw: item,
  }
}

function parseChecks(value: unknown): Map<string, FileCheck> | null {
  if (!Array.isArray(value)) return null
  const checks = new Map<string, FileCheck>()
  for (const item of value) {
    const check = parseCheck(item)
    if (!check || !isRecord(item) || !isNonEmptyString(item["file_id"])) return null
    checks.set(item["file_id"], check)
  }
  return checks
}

function parseCancelled(value: unknown): FileRow[] {
  if (!isRecord(value) || !Array.isArray(value["files"])) return []
  return value["files"].flatMap((item: unknown) => {
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

/** What the card keeps across a review: each cancelled File with its last check. */
export function serializeCancelled(files: readonly FileRow[]): Record<string, unknown> {
  return {
    files: files
      .filter((file) => file.cancelled)
      .map((file) => ({ ref: file.raw, check: file.check?.raw ?? null })),
  }
}

/** Cancels or restores Files; returns the File list to send and the rows to keep. */
export function editFiles(
  files: readonly FileRow[],
  ids: ReadonlySet<string>,
  cancelled: boolean
): { files: Record<string, unknown>[]; rows: FileRow[] } {
  const rows = files.map((file) => (ids.has(file.id) ? { ...file, cancelled } : file))
  return { files: rows.filter((row) => !row.cancelled).map((row) => row.raw), rows }
}

export type UploadCounts = {
  images: number
  videoFiles: number
  links: number
  uploads: number
  madeWithAi: number
  problems: number
  badTitles: number
  badVideos: number
  badUploads: number
  repeatedVideos: boolean
}

export function uploadCounts(args: UploadMediaArgs): UploadCounts {
  const live = args.files.filter((file) => !file.cancelled)
  const videoFiles = liveVideos(args)
  const ids = args.videos.map(youtubeVideoId)
  const valid = ids.filter((id): id is string => id !== null)
  return {
    images: live.length - videoFiles.length,
    videoFiles: videoFiles.length,
    links: valid.length,
    uploads: args.uploads.length,
    madeWithAi: live.filter((file) => args.madeWithAi.has(file.id)).length,
    problems: live.filter((file) => file.check?.problem).length,
    badTitles: videoFiles.filter((file) => videoTextProblem(videoTextFor(args, file))).length,
    badVideos: ids.length - valid.length,
    badUploads: args.uploads.filter((value) => !UPLOAD_ID.test(value.trim())).length,
    repeatedVideos: new Set(valid).size !== valid.length,
  }
}

/** Why the request can't be approved yet, or null. */
export function uploadBlock(args: UploadMediaArgs | null): string | null {
  if (args === null) return null
  const counts = uploadCounts(args)
  if (counts.images + counts.videoFiles + counts.links + counts.badVideos + counts.uploads === 0)
    return "Every upload is cancelled. Decline this request, or undo one."
  if (args.needsReview) return "Click Check Files so the changed Files are checked, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${String(counts.problems)} ${pluralize(counts.problems, "File")} to continue.`
  if (counts.badTitles > 0)
    return `Fix the title of ${String(counts.badTitles)} ${pluralize(counts.badTitles, "video")} to continue.`
  if (counts.badVideos > 0) return "Enter a YouTube link or video ID for each video."
  if (counts.repeatedVideos) return "List each YouTube video once."
  if (counts.badUploads > 0) return "Enter the upload ID of each earlier upload."
  return null
}

function countPhrase(count: number, noun: string): string {
  return `${count.toLocaleString("en-GB")} ${pluralize(count, noun)}`
}

function joinPhrases(parts: readonly (string | null)[]): string {
  const kept = parts.filter((part): part is string => part !== null)
  if (kept.length <= 1) return kept[0] ?? ""
  return `${kept.slice(0, -1).join(", ")} and ${kept.at(-1) ?? ""}`
}

export function uploadApproveLabel(args: UploadMediaArgs): string {
  const counts = uploadCounts(args)
  const files = counts.images + counts.videoFiles
  return (
    joinPhrases([
      files ? `Upload ${countPhrase(files, counts.videoFiles ? "File" : "Image")}` : null,
      counts.links ? `Link ${countPhrase(counts.links, "Video")}` : null,
      counts.uploads ? `Finish ${countPhrase(counts.uploads, "Video")}` : null,
    ]) || "Upload"
  )
}

export function uploadPrompt(args: UploadMediaArgs): string {
  const counts = uploadCounts(args)
  const what = joinPhrases([
    counts.images ? `upload ${countPhrase(counts.images, "image")}` : null,
    counts.videoFiles ? `upload ${countPhrase(counts.videoFiles, "video")} to YouTube` : null,
    counts.links ? `link ${countPhrase(counts.links, "YouTube video")}` : null,
    counts.uploads ? `finish ${countPhrase(counts.uploads, "earlier video upload")}` : null,
  ])
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

/** Images in KB, matching Google's limit; videos in the largest unit that reads well. */
export function fileSize(kind: "image" | "video", bytes: number): string {
  return kind === "video"
    ? formatBytes(bytes)
    : `${Math.ceil(bytes / 1024).toLocaleString("en-GB")} KB`
}
