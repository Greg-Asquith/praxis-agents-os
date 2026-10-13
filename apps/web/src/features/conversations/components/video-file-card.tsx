// apps/web/src/features/conversations/components/video-file-card.tsx

import { useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { DownloadIcon, InfoIcon, Loader2Icon, TriangleAlertIcon, VideoIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  type VideoFileReference,
  videoFileStatus,
} from "@/features/conversations/native-tools/video-tools"
import { fileQueryOptions } from "@/features/files/api/get-file"
import { filePreviewQueryOptions } from "@/features/files/api/preview-file"
import { FileDetailModal } from "@/features/files/components/file-detail-modal"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { getErrorMessage } from "@/lib/api/errors"
import { cn } from "@/lib/utils"

export type VideoRange = { startMs: number; endMs: number }

export function VideoFileCard({
  video,
  range,
  autoPlay = false,
  className,
}: {
  video: VideoFileReference
  range?: VideoRange
  autoPlay?: boolean
  className?: string
}) {
  const detailButtonRef = useRef<HTMLButtonElement>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const fileQuery = useQuery(fileQueryOptions(video.fileId))
  const status = fileQuery.isError
    ? { kind: "error" as const, label: getErrorMessage(fileQuery.error) }
    : videoFileStatus(fileQuery.data)
  const displayName = fileQuery.data?.name ?? video.name ?? "Video"

  async function handleDownload() {
    setActionError(null)
    try {
      await openWorkspaceFile({ fileId: video.fileId, name: displayName }, { forceDownload: true })
    } catch (downloadError) {
      setActionError(getErrorMessage(downloadError))
    }
  }

  function handleDetailOpenChange(open: boolean) {
    setDetailOpen(open)
    if (!open) {
      detailButtonRef.current?.focus()
    }
  }

  return (
    <>
      <div
        className={cn(
          "bg-background/80 mx-auto w-full max-w-md overflow-hidden rounded-md border",
          className
        )}
      >
        {status.kind === "ready" ? (
          <VideoPlayer autoPlay={autoPlay} fileId={video.fileId} name={displayName} range={range} />
        ) : (
          <div className="bg-muted/40 text-muted-foreground flex min-h-36 flex-col items-center justify-center gap-2 px-4 text-center text-xs">
            {status.kind === "preparing" ? (
              <Loader2Icon className="size-5 animate-spin motion-reduce:animate-none" />
            ) : (
              <TriangleAlertIcon className="text-destructive size-5" />
            )}
            <span>{status.label}</span>
          </div>
        )}
        <div className="flex min-w-0 items-center justify-between gap-3 px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <VideoIcon className="text-muted-foreground size-3.5 shrink-0" />
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{displayName}</p>
              {status.kind === "ready" ? (
                <p className="text-muted-foreground truncate text-xs">{status.label}</p>
              ) : null}
              {actionError ? <p className="text-destructive mt-1 text-xs">{actionError}</p> : null}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              aria-label={`View details for ${displayName}`}
              onClick={() => {
                setDetailOpen(true)
              }}
              ref={detailButtonRef}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <InfoIcon />
            </Button>
            <Button
              aria-label={`Download ${displayName}`}
              onClick={() => {
                void handleDownload()
              }}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <DownloadIcon />
            </Button>
          </div>
        </div>
      </div>
      <FileDetailModal
        fileId={video.fileId}
        onOpenChange={handleDetailOpenChange}
        open={detailOpen}
      />
    </>
  )
}

function VideoPlayer({
  autoPlay,
  fileId,
  name,
  range,
}: {
  autoPlay: boolean
  fileId: string
  name: string
  range: VideoRange | undefined
}) {
  // A refetch swaps the signed URL and restarts playback, so keep the first one.
  const previewQuery = useQuery({
    ...filePreviewQueryOptions(fileId),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  })
  const previewUrl = previewQuery.data?.preview.url
  if (previewUrl) {
    return (
      // Workspace video has no separate caption track; captions are burned into cut clips.
      // eslint-disable-next-line jsx-a11y/media-has-caption
      <video
        aria-label={name}
        autoPlay={autoPlay}
        className="max-h-112 w-full bg-black object-contain"
        controls
        playsInline
        preload="metadata"
        // A media fragment plays just the range, from its start to its end.
        src={
          range
            ? `${previewUrl}#t=${String(range.startMs / 1000)},${String(range.endMs / 1000)}`
            : previewUrl
        }
      />
    )
  }
  return (
    <div className="bg-muted/40 text-muted-foreground flex min-h-36 flex-col items-center justify-center gap-2 px-4 text-center text-xs">
      {previewQuery.isError ? (
        <>
          <VideoIcon className="size-5" />
          <span>{getErrorMessage(previewQuery.error)}</span>
        </>
      ) : (
        <Loader2Icon
          aria-label={`Loading ${name}`}
          className="size-5 animate-spin motion-reduce:animate-none"
        />
      )}
    </div>
  )
}
