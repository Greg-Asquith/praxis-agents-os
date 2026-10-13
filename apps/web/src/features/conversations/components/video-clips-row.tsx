// apps/web/src/features/conversations/components/video-clips-row.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { PlayIcon, ScissorsIcon, TriangleAlertIcon, VideoIcon } from "lucide-react"

import { ToolResultCard } from "@/components/tool-ui/result-card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { VideoFileCard } from "@/features/conversations/components/video-file-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  cutVideoClipsResult,
  type VideoClip,
} from "@/features/conversations/native-tools/video-tools"
import { filePreviewQueryOptions } from "@/features/files/api/preview-file"
import { formatDuration, pluralize } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const FRAMING_LABELS: Record<string, string> = {
  auto: "Follow Speaker",
  center: "Centre Crop",
  fit: "Fit Over Blur",
}

const CAPTION_LABELS: Record<string, string> = {
  bold: "Bold",
  clean: "Clean",
  highlight: "Word Highlight",
}

export function CutVideoClipsRow({
  activity,
  defaultOpen,
}: {
  activity: ToolActivity
  defaultOpen: boolean
}) {
  const result = cutVideoClipsResult(activity.result)
  if (!result) {
    return null
  }
  const total = result.clips.length
  const args = isRecord(activity.args) ? activity.args : {}
  const shape = args["aspect_ratio"]
  // Framing only matters when the shape changes; the tool defaults to auto.
  const framing =
    typeof shape === "string" && shape !== "original"
      ? FRAMING_LABELS[typeof args["framing"] === "string" ? args["framing"] : "auto"]
      : undefined
  const captions =
    typeof args["captions"] === "string" ? CAPTION_LABELS[args["captions"]] : undefined
  const clips =
    result.saved === total
      ? `${String(total)} ${pluralize(total, "Clip")}`
      : `${String(result.saved)} of ${String(total)} Clips Saved`
  return (
    <ToolResultCard
      ariaLabel="Cut video clips"
      defaultOpen={defaultOpen}
      details={[
        { label: "Clips", value: clips },
        ...(typeof shape === "string" ? [{ label: "Shape", value: shape }] : []),
        ...(framing ? [{ label: "Framing", value: framing }] : []),
        ...(captions ? [{ label: "Captions", value: captions }] : []),
        ...(args["remove_silences"] === true ? [{ label: "Pauses", value: "Removed" }] : []),
      ]}
      summary={clips}
      heading={
        <span className="inline-flex min-w-0 items-center gap-2">
          <ScissorsIcon className="text-muted-foreground size-4 shrink-0" />
          <span>Cut Video Clips</span>
        </span>
      }
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <ol aria-label="Clips" className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3">
        {result.clips.map((clip) => (
          <li className="min-w-0" key={clip.index}>
            <ClipTile clip={clip} />
          </li>
        ))}
      </ol>
    </ToolResultCard>
  )
}

function ClipTile({ clip }: { clip: VideoClip }) {
  const [open, setOpen] = useState(false)
  const length = clip.durationMs === null ? null : formatDuration(clip.durationMs, "milliseconds")
  const caption = (
    <div className="grid min-w-0 gap-0.5 pt-1.5">
      <p className="truncate text-xs font-medium" title={clip.name}>
        {clip.name}
      </p>
      <p className="text-muted-foreground truncate text-xs tabular-nums">
        {clip.ranges.join(" + ")}
      </p>
      {clip.warnings.map((warning) => (
        <p className="text-muted-foreground text-xs wrap-break-word" key={warning}>
          {warning}
        </p>
      ))}
    </div>
  )
  if (!clip.video) {
    return (
      <div className="min-w-0">
        <div className="border-destructive/40 bg-destructive/5 flex aspect-video flex-col items-center justify-center gap-1.5 rounded-md border p-3 text-center">
          <TriangleAlertIcon className="text-destructive size-4" />
          <p className="text-destructive line-clamp-3 text-xs">{clip.error}</p>
        </div>
        {caption}
      </div>
    )
  }
  const video = clip.video
  return (
    <div className="min-w-0">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger
          render={
            <button
              aria-label={`Play ${clip.name}`}
              className="group focus-visible:ring-ring/50 relative block aspect-video w-full overflow-hidden rounded-md border bg-black outline-none focus-visible:ring-3"
              type="button"
            />
          }
        >
          <ClipPoster fileId={video.fileId} />
          <span className="absolute inset-0 flex items-center justify-center bg-black/10 transition-colors group-hover:bg-black/30">
            <span className="flex size-9 items-center justify-center rounded-full bg-black/60 text-white">
              <PlayIcon className="size-4 fill-current" />
            </span>
          </span>
          {length ? (
            <span className="absolute right-1.5 bottom-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[11px] text-white tabular-nums">
              {length}
            </span>
          ) : null}
        </DialogTrigger>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="truncate pr-8">{clip.name}</DialogTitle>
          </DialogHeader>
          {open ? <VideoFileCard autoPlay className="max-w-none" video={video} /> : null}
        </DialogContent>
      </Dialog>
      {caption}
    </div>
  )
}

// A still from the clip's signed preview; the player opens in a dialog.
function ClipPoster({ fileId }: { fileId: string }) {
  const previewQuery = useQuery({
    ...filePreviewQueryOptions(fileId),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  })
  const url = previewQuery.data?.preview.url
  if (!url) {
    return (
      <span className="text-muted-foreground absolute inset-0 flex items-center justify-center">
        <VideoIcon className="size-5" />
      </span>
    )
  }
  return (
    <video
      aria-hidden
      className="pointer-events-none size-full object-contain"
      muted
      playsInline
      preload="metadata"
      src={`${url}#t=0.1`}
      tabIndex={-1}
    />
  )
}
