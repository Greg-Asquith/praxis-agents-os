// apps/web/src/components/tool-ui/workspace-file-thumbnail.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ImageIcon, Loader2Icon, VideoIcon } from "lucide-react"

import {
  workspaceFilePreviewQueryOptions,
  workspaceFilePreviewUrl,
} from "@/components/tool-ui/workspace-file-preview"
import { cn } from "@/lib/utils"

/** Shows one revision of a workspace File, or an unavailable tile when it has none to show. */
export function WorkspaceFileThumbnail({
  className,
  current = false,
  fileId,
  kind,
  label,
  revisionId,
}: {
  className?: string
  // Shows the File's current revision when no revision is pinned yet.
  current?: boolean
  fileId: string
  kind: "image" | "video"
  label: string
  revisionId: string | null
}) {
  const enabled = revisionId !== null || current
  const query = useQuery({
    ...workspaceFilePreviewQueryOptions(fileId, revisionId),
    enabled,
  })
  // Recorded by URL, so a new grant or revision tries again.
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  // A grant can expire before a lazy image loads, so a failed load fetches one new grant.
  const [renewed, setRenewed] = useState(false)
  const grantUrl = workspaceFilePreviewUrl(query.data)
  const handleLoadError = (failed: string) => {
    setFailedUrl(failed)
    if (renewed) return
    setRenewed(true)
    void query.refetch()
  }
  return (
    <div
      className={cn(
        "bg-muted/40 flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-md border",
        className
      )}
    >
      <ThumbnailContent
        kind={kind}
        label={label}
        loading={enabled && query.isPending}
        onLoadError={handleLoadError}
        url={grantUrl === failedUrl ? null : grantUrl}
      />
    </div>
  )
}

function ThumbnailContent({
  kind,
  label,
  loading,
  onLoadError,
  url,
}: {
  kind: "image" | "video"
  label: string
  loading: boolean
  onLoadError: (url: string) => void
  url: string | null
}) {
  if (loading) {
    return (
      <Loader2Icon
        aria-label={`Loading preview for ${label}`}
        className="text-muted-foreground size-4 animate-spin motion-reduce:animate-none"
      />
    )
  }
  if (!url) {
    const Icon = kind === "image" ? ImageIcon : VideoIcon
    return <Icon aria-label={`No preview for ${label}`} className="text-muted-foreground size-4" />
  }
  const onError = () => {
    onLoadError(url)
  }
  if (kind === "image") {
    return (
      <img
        alt={label}
        className="size-full object-cover"
        loading="lazy"
        onError={onError}
        src={url}
      />
    )
  }
  return (
    <video
      aria-label={`Preview of ${label}`}
      className="size-full object-cover"
      muted
      onError={onError}
      playsInline
      preload="metadata"
      src={url}
    />
  )
}
