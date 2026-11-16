// apps/web/src/components/tool-ui/workspace-file-media.tsx

import { useQuery } from "@tanstack/react-query"
import { Loader2Icon } from "lucide-react"

import {
  workspaceFilePreviewQueryOptions,
  workspaceFilePreviewUrl,
  type WorkspaceMediaKind,
} from "@/components/tool-ui/workspace-file-preview"

/** Plays a workspace File's current image, video, or audio in place. */
export function WorkspaceFileMedia({
  fileId,
  kind,
  name,
}: {
  fileId: string
  kind: WorkspaceMediaKind
  name: string
}) {
  // A refetch swaps the signed URL and restarts playback, so keep the first one.
  const query = useQuery({
    ...workspaceFilePreviewQueryOptions(fileId, null),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  })
  const url = workspaceFilePreviewUrl(query.data)
  if (!url) {
    return (
      <div className="bg-muted/40 text-muted-foreground flex min-h-16 items-center justify-center gap-2 rounded-md border px-3 text-xs">
        {query.isPending ? (
          <>
            <Loader2Icon className="size-3.5 animate-spin motion-reduce:animate-none" />
            Loading preview
          </>
        ) : (
          "Preview unavailable. Open it in Files."
        )}
      </div>
    )
  }
  if (kind === "image") {
    return (
      <div className="bg-muted/40 flex items-center justify-center overflow-hidden rounded-md border">
        <img alt={name} className="max-h-80 w-full object-contain" loading="lazy" src={url} />
      </div>
    )
  }
  if (kind === "video") {
    return (
      <video
        aria-label={name}
        className="bg-media max-h-112 w-full rounded-md border object-contain"
        controls
        playsInline
        preload="metadata"
        src={url}
      >
        <track kind="captions" />
      </video>
    )
  }
  return (
    <audio aria-label={`Play ${name}`} className="w-full" controls preload="metadata" src={url}>
      <track kind="captions" />
    </audio>
  )
}
