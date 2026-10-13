// apps/web/src/features/conversations/native-tools/video-tools.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isVideoAttachmentMediaType } from "@/features/conversations/attachments"
import { videoSummary } from "@/features/files/format"
import { isFileProcessing } from "@/features/files/processing"
import type { WorkspaceFile } from "@/features/files/types"
import { formatBytes } from "@/lib/format"
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
  warnings: string[]
  error: string | null
}

export type CutVideoClipsResult = {
  clips: VideoClip[]
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
  return { clips: clips as VideoClip[], saved: value["saved"] }
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
  return {
    index: value["index"],
    name: value["name"],
    video,
    durationMs: typeof value["duration_ms"] === "number" ? value["duration_ms"] : null,
    ranges: value["segments"]
      .filter(isRecord)
      .map((segment) => `${String(segment["start"])}–${String(segment["end"])}`),
    warnings: Array.isArray(value["warnings"])
      ? value["warnings"].filter((warning) => typeof warning === "string")
      : [],
    error: saved ? null : typeof value["error"] === "string" ? value["error"] : "Couldn't cut.",
  }
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
