// apps/web/src/integrations/meta_ads/components/media-frame.tsx

import { ImageIcon, VideoIcon } from "lucide-react"

import { WorkspaceFileThumbnail } from "@/components/tool-ui/workspace-file-thumbnail"
import { Skeleton } from "@/components/ui/skeleton"
import type { PreviewMedia } from "@/integrations/meta_ads/lib/create-ads-args"
import { useMetaPicture } from "@/integrations/meta_ads/lib/meta-pictures"
import { cn } from "@/lib/utils"

// Feed shows media between 1.91:1 and 4:5, cropping anything outside that.
const FEED_RATIO = { widest: 1.91, tallest: 0.8 }

type Shape = "feed" | "square" | "fill"

/** Shows media as the ad would: a workspace File's revision, or the picture Meta holds. */
export function MediaFrame({
  media,
  shape,
  className,
}: {
  media: PreviewMedia | null
  shape: Shape
  className?: string
}) {
  const ratio = aspectRatio(media, shape)
  return (
    <div
      className={cn("bg-muted relative w-full overflow-hidden", className)}
      style={ratio ? { aspectRatio: ratio } : undefined}
    >
      {media?.fileId ? (
        <WorkspaceFileThumbnail
          className="size-full rounded-none border-0"
          // A File chosen on the card has no pinned revision, so it shows its current one.
          current
          fileId={media.fileId}
          kind={media.mediaType}
          label={media.label}
          revisionId={media.revisionId}
        />
      ) : media ? (
        <LibraryPicture media={media} />
      ) : (
        <MediaTile label="No media" mediaType="image" />
      )}
    </div>
  )
}

function LibraryPicture({ media }: { media: PreviewMedia }) {
  // Library media is keyed image:HASH or video:ID; the preview route takes image_HASH or video_ID.
  const groups = /^(?<type>image|video):(?<id>[A-Za-z0-9]+)$/.exec(media.key)?.groups
  const { loading, src: content } = useMetaPicture(
    groups ? `${String(groups["type"])}_${String(groups["id"])}` : null
  )
  if (loading) {
    return <Skeleton aria-label={`Loading ${media.label}`} className="size-full rounded-none" />
  }
  if (!content) {
    return <MediaTile label={media.label} mediaType={media.mediaType} />
  }
  return (
    <>
      <img alt={media.label} className="size-full object-cover" src={content} />
      {media.mediaType === "video" ? (
        <span className="absolute inset-0 flex items-center justify-center">
          <span className="flex size-9 items-center justify-center rounded-full bg-black/55 text-white">
            <VideoIcon aria-hidden="true" className="size-4" />
          </span>
        </span>
      ) : null}
    </>
  )
}

function MediaTile({ label, mediaType }: { label: string; mediaType: "image" | "video" }) {
  const Icon = mediaType === "video" ? VideoIcon : ImageIcon
  return (
    <div className="text-muted-foreground flex size-full flex-col items-center justify-center gap-1 p-2 text-center">
      <Icon aria-hidden="true" className="size-5" />
      <span className="line-clamp-2 max-w-full text-xs wrap-anywhere">{label}</span>
    </div>
  )
}

function aspectRatio(media: PreviewMedia | null, shape: Shape): string | undefined {
  if (shape === "fill") return undefined
  if (shape === "square" || !media?.width || !media.height) return "1 / 1"
  const ratio = Math.min(
    FEED_RATIO.widest,
    Math.max(FEED_RATIO.tallest, media.width / media.height)
  )
  return String(ratio)
}
