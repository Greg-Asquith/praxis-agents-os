// apps/web/src/features/conversations/native-tools/video-tools.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isVideoAttachmentMediaType } from "@/features/conversations/attachments"
import { videoSummary } from "@/features/files/format"
import { isFileProcessing } from "@/features/files/processing"
import type { WorkspaceFile } from "@/features/files/types"
import { formatBytes, titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export type VideoFileReference = {
  fileId: string
  name: string | null
}

// Video Files a tool result names, either at the top level or in a list such as `clips`.
export function videoFileReferences(value: unknown): VideoFileReference[] | null {
  if (!isRecord(value)) {
    return null
  }
  const single = videoFileReference(value)
  if (single) {
    return [single]
  }
  const references = Object.values(value)
    .filter((item) => Array.isArray(item))
    .flatMap((items: unknown[]) => items.map(videoFileReference))
    .filter((reference) => reference !== null)
  return references.length > 0 ? references : null
}

function videoFileReference(value: unknown): VideoFileReference | null {
  if (
    !isRecord(value) ||
    typeof value["file_id"] !== "string" ||
    typeof value["media_type"] !== "string" ||
    !isVideoAttachmentMediaType(value["media_type"])
  ) {
    return null
  }
  return {
    fileId: value["file_id"],
    name: typeof value["name"] === "string" ? value["name"] : null,
  }
}

// The chip and card label for a video: preparing, failed, or its measurement.
export function videoFileStatus(file: WorkspaceFile | undefined) {
  if (!file || isFileProcessing(file.processing_status)) {
    return { kind: "preparing" as const, label: "Preparing video" }
  }
  if (file.processing_status === "error") {
    return { kind: "error" as const, label: file.processing_error ?? "Couldn't prepare video" }
  }
  return {
    kind: "ready" as const,
    label: file.video ? videoSummary(file.video) : formatBytes(file.size_bytes),
  }
}

export const FIND_VIDEO_MOMENTS_TOOL_NAME = "find_video_moments"
export const ASK_VIDEO_TOOL_NAME = "ask_video"

export type VideoMoment = {
  // M:SS labels the server formats from the snapped times.
  start: string
  end: string
  startMs: number
  endMs: number
  score: number
  shotCount: number
  title: string
  hook: string
  reason: string
  excerpt: string
}

export type FindVideoMomentsResult = {
  video: VideoFileReference
  moments: VideoMoment[]
  note: string | null
}

export type AskVideoResult = {
  video: VideoFileReference
  // The watched range to play; null plays the whole video.
  range: { startMs: number; endMs: number } | null
  start: string
  end: string
  answer: string
}

export function findVideoMomentsResult(value: unknown): FindVideoMomentsResult | null {
  if (!isRecord(value) || !Array.isArray(value["moments"])) {
    return null
  }
  const video = sourceVideo(value)
  const moments = value["moments"].map(videoMoment)
  if (!video || moments.some((moment) => moment === null)) {
    return null
  }
  const note = nodeText(value["note"])
  return { video, moments: moments as VideoMoment[], note: note?.trim() ? note : null }
}

export function askVideoResult(value: unknown): AskVideoResult | null {
  if (!isRecord(value)) {
    return null
  }
  const video = sourceVideo(value)
  const answer = nodeText(value["answer"])
  if (
    !video ||
    answer === null ||
    typeof value["start"] !== "string" ||
    typeof value["end"] !== "string"
  ) {
    return null
  }
  const { start_ms: startMs, end_ms: endMs } = value
  return {
    video,
    range:
      typeof startMs === "number" && typeof endMs === "number" && endMs > startMs
        ? { startMs, endMs }
        : null,
    start: value["start"],
    end: value["end"],
    answer,
  }
}

function sourceVideo(value: Record<string, unknown>): VideoFileReference | null {
  if (typeof value["file_id"] !== "string") {
    return null
  }
  return {
    fileId: value["file_id"],
    name: typeof value["name"] === "string" ? value["name"] : null,
  }
}

function videoMoment(value: unknown): VideoMoment | null {
  if (!isRecord(value)) {
    return null
  }
  const { start_ms: startMs, end_ms: endMs, score, shot_count: shotCount } = value
  const title = nodeText(value["title"])
  if (
    typeof startMs !== "number" ||
    typeof endMs !== "number" ||
    endMs <= startMs ||
    typeof score !== "number" ||
    typeof shotCount !== "number" ||
    typeof value["start"] !== "string" ||
    typeof value["end"] !== "string" ||
    title === null
  ) {
    return null
  }
  return {
    start: value["start"],
    end: value["end"],
    startMs,
    endMs,
    score,
    shotCount,
    title,
    hook: nodeText(value["hook"]) ?? "",
    reason: nodeText(value["reason"]) ?? "",
    excerpt: nodeText(value["transcript_excerpt"]) ?? "",
  }
}

export const CUT_VIDEO_CLIPS_TOOL_NAME = "cut_video_clips"

export type VideoClip = {
  index: number
  name: string
  // The saved File, or null when this clip failed.
  video: VideoFileReference | null
  durationMs: number | null
  ranges: string[]
  // Fades and transitions in the order they play, such as "Fade In 0.5 s".
  effects: string[]
  warnings: string[]
  error: string | null
}

type ClipFolder = { id: string; name: string }

export type CutVideoClipsResult = {
  clips: VideoClip[]
  // Where the saved clips went, in order of first use.
  folders: ClipFolder[]
  saved: number
}

export function cutVideoClipsResult(value: unknown): CutVideoClipsResult | null {
  if (!isRecord(value) || !Array.isArray(value["clips"]) || typeof value["saved"] !== "number") {
    return null
  }
  const clips = value["clips"].map(videoClip)
  if (clips.some((clip) => clip === null)) {
    return null
  }
  const folders = new Map<string, ClipFolder>()
  for (const clip of value["clips"]) {
    const folder = isRecord(clip) ? clip["folder"] : null
    if (
      isRecord(folder) &&
      typeof folder["id"] === "string" &&
      typeof folder["name"] === "string"
    ) {
      folders.set(folder["id"], { id: folder["id"], name: folder["name"] })
    }
  }
  return { clips: clips as VideoClip[], folders: [...folders.values()], saved: value["saved"] }
}

function videoClip(value: unknown): VideoClip | null {
  if (
    !isRecord(value) ||
    typeof value["index"] !== "number" ||
    typeof value["name"] !== "string" ||
    !Array.isArray(value["segments"])
  ) {
    return null
  }
  const saved = value["status"] === "saved"
  const video = saved ? videoFileReference(value) : null
  if (saved && !video) {
    return null
  }
  const segments = value["segments"].filter(isRecord)
  return {
    index: value["index"],
    name: value["name"],
    video,
    durationMs: typeof value["duration_ms"] === "number" ? value["duration_ms"] : null,
    ranges: segments.map((segment) => `${String(segment["start"])}–${String(segment["end"])}`),
    effects: clipEffects(value, segments),
    warnings: Array.isArray(value["warnings"])
      ? value["warnings"].filter((warning) => typeof warning === "string")
      : [],
    error: saved ? null : typeof value["error"] === "string" ? value["error"] : "Couldn't cut.",
  }
}

function clipEffects(clip: Record<string, unknown>, segments: Record<string, unknown>[]) {
  const effects: string[] = []
  const fade = (key: string, label: string) => {
    const value = clip[key]
    if (typeof value === "number" && value > 0) {
      effects.push(`${label} ${seconds(value)}`)
    }
  }
  fade("fade_in_ms", "Fade In")
  for (const segment of segments) {
    const transition = segment["transition_in"]
    if (
      isRecord(transition) &&
      typeof transition["style"] === "string" &&
      typeof transition["duration_ms"] === "number"
    ) {
      effects.push(`${transitionLabel(transition["style"])} ${seconds(transition["duration_ms"])}`)
    }
  }
  fade("fade_out_ms", "Fade Out")
  return effects
}

// ffmpeg's xfade names run words together, such as "wipeleft" for Wipe Left.
function transitionLabel(style: string) {
  const spaced = style.replace(
    /(left|right|up|down|black|white|grays|fast|slow|open|close|crop|in)$/,
    " $1"
  )
  return titleCaseToken(spaced, style)
}

function seconds(milliseconds: number) {
  return `${String(milliseconds / 1000)} s`
}

// The turn "Cut These" sends. Moment titles and reasons come from a model watching untrusted
// video, so only the File name and the server's times go into the person's own message.
export function cutMomentsInstruction(videoName: string, moments: VideoMoment[]) {
  return [
    `Cut these moments from ${videoName} into separate clips:`,
    ...moments.map(
      (moment) =>
        `- ${moment.start} to ${moment.end} (${String(moment.startMs)}–${String(moment.endMs)} ms)`
    ),
  ].join("\n")
}
