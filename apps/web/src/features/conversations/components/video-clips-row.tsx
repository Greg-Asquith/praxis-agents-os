// apps/web/src/features/conversations/components/video-clips-row.tsx

import { Fragment, useState } from "react"
import { Link } from "@tanstack/react-router"
import { PlayIcon, ScissorsIcon, TriangleAlertIcon, VideoIcon } from "lucide-react"

import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { VideoFileCard } from "@/features/conversations/components/video-file-card"
import { useVideoPreview } from "@/features/conversations/hooks/use-video-preview"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  type CutVideoClipsResult,
  cutVideoClipsPlan,
  cutVideoClipsResult,
  type VideoClip,
  type VideoClipShapes,
} from "@/features/conversations/native-tools/video-tools"
import { formatDuration, pluralize } from "@/lib/format"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

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
  const result = cutVideoClipsResult(activity.result, activity.args)
  if (!result) {
    return null
  }
  const total = result.clips.length
  const shapes = result.clips[0]?.shapes.length ?? 1
  const files = total * shapes
  const clips =
    result.saved === files
      ? `${String(total)} ${pluralize(total, "Clip")}${shapes > 1 ? ` in ${String(shapes)} Shapes` : ""}`
      : `${String(result.saved)} of ${String(files)} ${shapes > 1 ? "Videos" : "Clips"} Saved`
  return (
    <ToolResultCard
      ariaLabel="Cut video clips"
      defaultOpen={defaultOpen}
      details={[
        { label: "Clips", value: clips },
        ...settingDetails(activity.args),
        ...finishingDetails(result, activity.args),
      ]}
      summary={clips}
      heading={<ToolHeading icon={ScissorsIcon}>Cut Video Clips</ToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <ol aria-label="Clips" className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3">
        {result.clips.map((clip) => (
          <li className="min-w-0" key={clip.index}>
            <ClipTile clip={clip} />
          </li>
        ))}
      </ol>
      {result.folders.length > 0 ? <ClipFolders folders={result.folders} /> : null}
      {result.musicNotice ? (
        <p className="text-muted-foreground pt-2 text-xs">{result.musicNotice}</p>
      ) : null}
    </ToolResultCard>
  )
}

// The settings the call asked for, as card details.
function settingDetails(args: unknown): ToolResultDetail[] {
  const settings = isRecord(args) ? args : {}
  const shapes = Array.isArray(settings["aspect_ratios"])
    ? [...new Set(settings["aspect_ratios"].filter((shape) => typeof shape === "string"))]
    : []
  // Framing only matters when the shape changes; the tool defaults to auto.
  const framing = shapes.some((shape) => shape !== "original")
    ? FRAMING_LABELS[typeof settings["framing"] === "string" ? settings["framing"] : "auto"]
    : undefined
  const captions =
    typeof settings["captions"] === "string" ? CAPTION_LABELS[settings["captions"]] : undefined
  return [
    ...(shapes.length > 0
      ? [
          {
            label: pluralize(shapes.length, "Shape"),
            value: shapes.map((shape) => shapeLabel(shape)).join(", "),
          },
        ]
      : []),
    ...(framing ? [{ label: "Framing", value: framing }] : []),
    ...(captions ? [{ label: "Captions", value: captions }] : []),
    ...(settings["remove_silences"] === true ? [{ label: "Pauses", value: "Removed" }] : []),
  ]
}

// What the call applied to every clip; a clip's own differences show under it.
function finishingDetails(result: CutVideoClipsResult, args: unknown): ToolResultDetail[] {
  const sound = [
    ...(result.soundLevelled ? ["Levelled"] : []),
    ...(result.voiceCleanedUp ? ["Voice Cleaned Up"] : []),
  ]
  const plan = cutVideoClipsPlan(args)
  return [
    ...(sound.length > 0 ? [{ label: "Sound", value: sound.join(", ") }] : []),
    ...(plan?.music ? [{ label: "Music", value: plan.music }] : []),
    ...(plan?.logo ? [{ label: "Logo", value: plan.logo }] : []),
    ...(result.punchIns ? [{ label: "Punch-In Zooms", value: "On" }] : []),
  ]
}

function ClipFolders({ folders }: { folders: CutVideoClipsResult["folders"] }) {
  return (
    <p className="text-muted-foreground pt-3 text-xs">
      Saved in {folders.length === 1 ? "the folder" : "the folders"}{" "}
      {folders.map((folder, index) => (
        <Fragment key={folder.id}>
          {index > 0 ? ", " : null}
          <Link
            className="text-foreground font-medium underline-offset-4 hover:underline"
            search={{ folder: folder.id }}
            to="/files"
          >
            {folder.name}
          </Link>
        </Fragment>
      ))}
      .
    </p>
  )
}

function shapeLabel(shape: string | null) {
  return shape === "original" ? "Original" : (shape ?? "")
}

// A clip's tile plays one shape at a time; a clip cut in several shapes switches between them.
function ClipTile({ clip: { shapes } }: { clip: VideoClipShapes }) {
  const [shown, setShown] = useState(0)
  const clip = shapes[shown] ?? shapes[0]
  if (!clip) {
    return null
  }
  return (
    <div className="min-w-0">
      <ClipPlayer clip={clip} />
      {shapes.length > 1 ? (
        <ToggleGroup
          aria-label={`Shapes of clip ${String(clip.index)}`}
          className="mt-1.5"
          onValueChange={(next) => {
            // Pressing the shown shape again would clear it, so only a new choice counts.
            const chosen = shapes.findIndex(
              (_, index) => index !== shown && next.includes(String(index))
            )
            if (chosen >= 0) setShown(chosen)
          }}
          spacing={0.5}
          value={[String(shown)]}
        >
          {shapes.map((shape, index) => (
            <ToggleGroupItem
              className={cn(
                "text-muted-foreground aria-pressed:bg-muted aria-pressed:text-foreground h-6 min-w-10 px-2 text-xs tabular-nums hover:cursor-pointer",
                !shape.video && "text-destructive aria-pressed:text-destructive"
              )}
              key={`${String(index)}-${shape.name}`}
              title={shape.error ?? undefined}
              value={String(index)}
            >
              {shapeLabel(shape.aspectRatio)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      ) : null}
      <ClipCaption clip={clip} />
    </div>
  )
}

function ClipPlayer({ clip }: { clip: VideoClip }) {
  const [open, setOpen] = useState(false)
  const length = clip.durationMs === null ? null : formatDuration(clip.durationMs, "milliseconds")
  if (!clip.video) {
    return (
      <div className="border-destructive/40 bg-destructive/5 flex aspect-video flex-col items-center justify-center gap-1.5 rounded-md border p-3 text-center">
        <TriangleAlertIcon className="text-destructive size-4" />
        <p className="text-destructive line-clamp-3 text-xs">{clip.error}</p>
      </div>
    )
  }
  const video = clip.video
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <button
            aria-label={`Play ${clip.name}`}
            className="group focus-visible:ring-ring/50 bg-media relative block aspect-video w-full overflow-hidden rounded-md border outline-none focus-visible:ring-3"
            type="button"
          />
        }
      >
        <ClipPoster fileId={video.fileId} />
        <span className="bg-media-overlay/10 group-hover:bg-media-overlay/30 absolute inset-0 flex items-center justify-center transition-colors">
          <span className="bg-media-overlay/60 text-media-foreground flex size-9 items-center justify-center rounded-full">
            <PlayIcon className="size-4 fill-current" />
          </span>
        </span>
        {length ? (
          <span className="bg-media-overlay/70 text-media-foreground absolute right-1.5 bottom-1.5 rounded px-1.5 py-0.5 text-[11px] tabular-nums">
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
  )
}

function ClipCaption({ clip }: { clip: VideoClip }) {
  return (
    <div className="grid min-w-0 gap-0.5 pt-1.5">
      <p className="truncate text-xs font-medium" title={clip.name}>
        {clip.name}
      </p>
      <p className="text-muted-foreground truncate text-xs tabular-nums">
        {clip.ranges.join(" + ")}
      </p>
      {clip.effects.length > 0 ? (
        <p className="text-muted-foreground text-xs wrap-break-word">{clip.effects.join(" · ")}</p>
      ) : null}
      {clip.overlays.map((overlay, index) => (
        <p
          className="text-muted-foreground truncate text-xs"
          key={`${String(index)}-${overlay.text}`}
          title={overlay.text}
        >
          <span className="text-foreground">“{overlay.text}”</span>{" "}
          <span className="tabular-nums">
            {overlay.start}–{overlay.end}
          </span>
        </p>
      ))}
      {clip.warnings.map((warning) => (
        <p className="text-muted-foreground text-xs wrap-break-word" key={warning}>
          {warning}
        </p>
      ))}
    </div>
  )
}

// A still from the clip's signed preview; the player opens in a dialog.
function ClipPoster({ fileId }: { fileId: string }) {
  const url = useVideoPreview(fileId).data?.preview.url
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
