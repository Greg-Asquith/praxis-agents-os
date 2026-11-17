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

export type VideoRange = { startMs: number; endMs: number }

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
    typeof value["media_type"] !== "string" ||
    !isVideoAttachmentMediaType(value["media_type"])
  ) {
    return null
  }
  return fileReference(value)
}

function fileReference(value: Record<string, unknown>): VideoFileReference | null {
  if (typeof value["file_id"] !== "string") {
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
  range: VideoRange | null
  start: string
  end: string
  answer: string
}

export function findVideoMomentsResult(value: unknown): FindVideoMomentsResult | null {
  if (!isRecord(value) || !Array.isArray(value["moments"])) {
    return null
  }
  const video = fileReference(value)
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
  const video = fileReference(value)
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
  // Black bars removed, then fades, transitions, speed changes, and zooms in the order they
  // play, such as "Fade In 0.5 s", then the clip's music and logo where they differ from the
  // call's.
  effects: string[]
  overlays: ClipOverlay[]
  warnings: string[]
  error: string | null
}

// Text burned into a clip, with M:SS times on the clip the server formats.
type ClipOverlay = { text: string; start: string; end: string }

type ClipFolder = { id: string; name: string }

type ClipMusic = { fileId: string; volume: number; duck: boolean }

type ClipLogo = {
  fileId: string
  position: string
  sizePercent: number
  opacity: number
  safeZone: boolean
}

const LOGO_POSITION_LABELS: Record<string, string> = {
  top_left: "Top Left",
  top_center: "Top Centre",
  top_right: "Top Right",
  middle_center: "Middle",
  bottom_left: "Bottom Left",
  bottom_center: "Bottom Centre",
  bottom_right: "Bottom Right",
}

export type CutVideoClipsResult = {
  clips: VideoClip[]
  // Where the saved clips went, in order of first use.
  folders: ClipFolder[]
  // Who is responsible for the music's rights, when any clip has music.
  musicNotice: string | null
  saved: number
  // What the call applied to every clip, shown once on the card.
  soundLevelled: boolean
  voiceCleanedUp: boolean
  punchIns: boolean
}

// Reads a result; the call's arguments say which music and logo every clip shares.
export function cutVideoClipsResult(value: unknown, args?: unknown): CutVideoClipsResult | null {
  if (!isRecord(value) || !Array.isArray(value["clips"]) || typeof value["saved"] !== "number") {
    return null
  }
  const callMusic = isRecord(args) ? musicArgument(args["music"]) : null
  const callLogo = isRecord(args) ? logoArgument(args["logo"]) : null
  const clips = value["clips"].map((clip) => videoClip(clip, callMusic, callLogo))
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
  const raw = value["clips"].filter(isRecord)
  return {
    clips: clips as VideoClip[],
    folders: [...folders.values()],
    musicNotice: typeof value["music_notice"] === "string" ? value["music_notice"] : null,
    saved: value["saved"],
    soundLevelled: raw.some((clip) => typeof clip["loudness_lufs"] === "number"),
    voiceCleanedUp: raw.some((clip) => clip["enhance_voice"] === true),
    punchIns: raw.some((clip) => clip["punch_ins"] === true),
  }
}

function videoClip(
  value: unknown,
  callMusic: ClipMusic | null,
  callLogo: ClipLogo | null
): VideoClip | null {
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
  const music = musicEffect(clipMusic(value["music"]), callMusic)
  const logo = logoEffect(clipLogo(value["logo"]), callLogo)
  return {
    index: value["index"],
    name: value["name"],
    video,
    durationMs: typeof value["duration_ms"] === "number" ? value["duration_ms"] : null,
    ranges: segments.map((segment) => `${String(segment["start"])}–${String(segment["end"])}`),
    effects: [...clipEffects(value, segments), ...(music ? [music] : []), ...(logo ? [logo] : [])],
    overlays: Array.isArray(value["text_overlays"])
      ? value["text_overlays"]
          .filter(isRecord)
          .flatMap((overlay) =>
            typeof overlay["text"] === "string" &&
            typeof overlay["start"] === "string" &&
            typeof overlay["end"] === "string"
              ? [{ text: overlay["text"], start: overlay["start"], end: overlay["end"] }]
              : []
          )
      : [],
    warnings: Array.isArray(value["warnings"])
      ? value["warnings"].filter((warning) => typeof warning === "string")
      : [],
    error: saved ? null : typeof value["error"] === "string" ? value["error"] : "Couldn't cut.",
  }
}

// A clip planned for approval, read from the call's arguments.
type PlannedVideoClip = {
  index: number
  name: string | null
  ranges: string[]
  effects: string[]
  overlays: string[]
}

export type CutVideoClipsPlan = {
  clips: PlannedVideoClip[]
  sound: string
  music: string | null
  logo: string | null
  pausesRemoved: boolean
  punchIns: boolean
  // Set only when the call says; otherwise bars come off when a video's shape changes.
  blackBars: "Removed" | "Kept" | null
}

// Every finishing option a cut_video_clips call applies, so an approver sees all of them.
export function cutVideoClipsPlan(args: unknown): CutVideoClipsPlan | null {
  if (!isRecord(args) || !Array.isArray(args["clips"])) {
    return null
  }
  const callMusic = musicArgument(args["music"])
  const callLogo = logoArgument(args["logo"])
  const audio = isRecord(args["audio"]) ? args["audio"] : {}
  const sound = [
    audio["normalize"] === false ? "Not Levelled" : "Levelled",
    ...(audio["enhance_voice"] === true ? ["Voice Cleaned Up"] : []),
  ]
  const clips = args["clips"].filter(isRecord).map((clip, position) => {
    const segments = Array.isArray(clip["segments"]) ? clip["segments"].filter(isRecord) : []
    const join = clip["transition"] ?? args["transition"]
    const planned = segments.map((segment, index) => ({
      ...segment,
      transition_in: index > 0 ? (segment["transition_in"] ?? join) : null,
    }))
    const own = clip["music"]
    const music =
      own === "none"
        ? callMusic
          ? "No Music"
          : null
        : musicEffect(musicArgument(own) ?? callMusic, callMusic)
    const ownLogo = clip["logo"]
    const logo =
      ownLogo === "none"
        ? callLogo
          ? "No Logo"
          : null
        : logoEffect(logoArgument(ownLogo) ?? callLogo, callLogo)
    const overlays = Array.isArray(clip["text_overlays"]) ? clip["text_overlays"] : []
    return {
      index: position + 1,
      name: typeof clip["name"] === "string" && clip["name"].trim() ? clip["name"] : null,
      ranges: segments.map(plannedRange),
      effects: [...clipEffects(clip, planned), ...(music ? [music] : []), ...(logo ? [logo] : [])],
      overlays: overlays
        .filter(isRecord)
        .flatMap((overlay) => (typeof overlay["text"] === "string" ? [overlay["text"]] : [])),
    }
  })
  return {
    clips,
    sound: sound.join(", "),
    music: callMusic ? musicSummary(callMusic, args["music"]) : null,
    logo: callLogo ? logoSummary(callLogo, args["logo"]) : null,
    pausesRemoved: args["remove_silences"] === true,
    punchIns: args["punch_ins"] === "auto",
    blackBars:
      args["remove_black_bars"] === true
        ? "Removed"
        : args["remove_black_bars"] === false
          ? "Kept"
          : null,
  }
}

function plannedRange(segment: Record<string, unknown>) {
  const file = isRecord(segment["file_id"]) ? segment["file_id"] : {}
  const name = typeof file["label"] === "string" ? `${file["label"]} ` : ""
  const { start_ms: startMs, end_ms: endMs } = segment
  if (typeof startMs !== "number" && typeof endMs !== "number") {
    return `${name}(Whole Video)`
  }
  const start = typeof startMs === "number" ? clock(startMs) : "Start"
  const end = typeof endMs === "number" ? clock(endMs) : "End"
  return `${name}${start}–${end}`
}

// M:SS, or H:MM:SS from an hour.
function clock(milliseconds: number) {
  const total = Math.floor(milliseconds / 1000)
  const [hours, minutes, secs] = [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60]
  const pad = (value: number) => String(value).padStart(2, "0")
  return hours ? `${String(hours)}:${pad(minutes)}:${pad(secs)}` : `${String(minutes)}:${pad(secs)}`
}

// The music a call or clip asks for; volume and duck follow the tool's defaults when omitted.
function musicArgument(value: unknown): ClipMusic | null {
  if (!isRecord(value) || !isRecord(value["file_id"])) {
    return null
  }
  const fileId = value["file_id"]["entity_id"]
  if (typeof fileId !== "string") {
    return null
  }
  return {
    fileId,
    volume: typeof value["volume"] === "number" ? value["volume"] : 25,
    duck: value["duck"] !== false,
  }
}

function clipMusic(value: unknown): ClipMusic | null {
  if (
    !isRecord(value) ||
    typeof value["file_id"] !== "string" ||
    typeof value["volume"] !== "number"
  ) {
    return null
  }
  return { fileId: value["file_id"], volume: value["volume"], duck: value["duck"] !== false }
}

function musicSummary(music: ClipMusic, value: unknown) {
  const file = isRecord(value) && isRecord(value["file_id"]) ? value["file_id"] : {}
  const name = typeof file["label"] === "string" ? file["label"] : "Music"
  return `${name}, ${String(music.volume)}% ${music.duck ? "Under Speech" : "Throughout"}`
}

// A clip's music only needs saying where it differs from the music every clip shares.
function musicEffect(own: ClipMusic | null, shared: ClipMusic | null) {
  if (!own) {
    return shared ? "No Music" : null
  }
  if (!shared) {
    return own.duck ? "Music Under Speech" : "Music Added"
  }
  const same =
    own.fileId === shared.fileId && own.volume === shared.volume && own.duck === shared.duck
  return same ? null : "Different Music"
}

// The logo a call or clip asks for; placement follows the tool's defaults when omitted.
function logoArgument(value: unknown): ClipLogo | null {
  if (!isRecord(value) || !isRecord(value["file_id"])) {
    return null
  }
  const fileId = value["file_id"]["entity_id"]
  if (typeof fileId !== "string") {
    return null
  }
  return {
    fileId,
    position: typeof value["position"] === "string" ? value["position"] : "top_right",
    sizePercent: typeof value["size_percent"] === "number" ? value["size_percent"] : 15,
    opacity: typeof value["opacity"] === "number" ? value["opacity"] : 100,
    safeZone: value["safe_zone"] !== false,
  }
}

function clipLogo(value: unknown): ClipLogo | null {
  if (
    !isRecord(value) ||
    typeof value["file_id"] !== "string" ||
    typeof value["position"] !== "string" ||
    typeof value["size_percent"] !== "number" ||
    typeof value["opacity"] !== "number"
  ) {
    return null
  }
  return {
    fileId: value["file_id"],
    position: value["position"],
    sizePercent: value["size_percent"],
    opacity: value["opacity"],
    safeZone: value["safe_zone"] !== false,
  }
}

// Such as "Logo.png, Top Centre, Safe Zone Off, 70% Opacity".
function logoSummary(logo: ClipLogo, value: unknown) {
  const file = isRecord(value) && isRecord(value["file_id"]) ? value["file_id"] : {}
  const name = typeof file["label"] === "string" ? file["label"] : "Logo"
  const position = LOGO_POSITION_LABELS[logo.position] ?? titleCaseToken(logo.position, "Top Right")
  return [
    name,
    position,
    ...(logo.safeZone ? [] : ["Safe Zone Off"]),
    ...(logo.opacity < 100 ? [`${String(logo.opacity)}% Opacity`] : []),
  ].join(", ")
}

// A clip's logo only needs saying where it differs from the logo every clip shares.
function logoEffect(own: ClipLogo | null, shared: ClipLogo | null) {
  if (!own) {
    return shared ? "No Logo" : null
  }
  if (!shared) {
    return "Logo Added"
  }
  const same =
    own.fileId === shared.fileId &&
    own.position === shared.position &&
    own.safeZone === shared.safeZone &&
    own.sizePercent === shared.sizePercent &&
    own.opacity === shared.opacity
  return same ? null : "Different Logo"
}

function clipEffects(clip: Record<string, unknown>, segments: Record<string, unknown>[]) {
  const effects = clip["black_bars_removed"] === true ? ["Black Bars Removed"] : []
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
      transition["style"] !== "none"
    ) {
      const length = transition["duration_ms"]
      const label = transitionLabel(transition["style"])
      effects.push(typeof length === "number" ? `${label} ${seconds(length)}` : label)
    }
    const speed = segment["speed"]
    if (typeof speed === "number" && speed !== 1) {
      effects.push(`${String(speed)}× Speed`)
    }
    const freeze = segment["freeze_end_ms"]
    if (typeof freeze === "number" && freeze > 0) {
      effects.push(`Freeze Frame ${seconds(freeze)}`)
    }
    const zoom = segment["zoom"]
    if (isRecord(zoom) && typeof zoom["to_percent"] === "number") {
      const from = typeof zoom["from_percent"] === "number" ? zoom["from_percent"] : 100
      const to = zoom["to_percent"]
      effects.push(
        to !== from ? `Zoom ${String(from)}% to ${String(to)}%` : `Zoom ${String(from)}%`
      )
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

// Titles and reasons are model-written from untrusted video, so only the name and times go in.
export function cutMomentsInstruction(videoName: string, moments: VideoMoment[]) {
  return [
    `Cut these moments from ${videoName} into separate clips:`,
    ...moments.map(
      (moment) =>
        `- ${moment.start} to ${moment.end} (${String(moment.startMs)}–${String(moment.endMs)} ms)`
    ),
  ].join("\n")
}
