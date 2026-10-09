// apps/web/src/components/tool-ui/workspace-file-thumbnail.tsx

import { useState } from "react"
import { queryOptions, useQuery } from "@tanstack/react-query"
import { ImageIcon, Loader2Icon, VideoIcon } from "lucide-react"

import { apiRequest } from "@/lib/api/client"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const fileQueryKeys = createWorkspaceScopedQueryKeys("files")
// Preview grants last 10 minutes; refetch well before one expires.
const PREVIEW_STALE_MS = 4 * 60 * 1000

// Keyed by revision, so a replaced File never shows its newer bytes in place of these.
function revisionPreviewQueryOptions(fileId: string, revisionId: string | null) {
  return queryOptions({
    queryKey: [...fileQueryKeys.detail(fileId), "preview", revisionId ?? "current"],
    queryFn: () =>
      apiRequest<unknown>(
        revisionId
          ? `/files/${fileId}/preview?revision_id=${encodeURIComponent(revisionId)}`
          : `/files/${fileId}/preview`,
        { method: "POST" }
      ),
    staleTime: PREVIEW_STALE_MS,
    retry: 1,
  })
}

function previewUrl(grant: unknown): string | null {
  const preview = isRecord(grant) ? grant["preview"] : null
  const url = isRecord(preview) ? preview["url"] : null
  return typeof url === "string" && url ? url : null
}

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
    ...revisionPreviewQueryOptions(fileId, revisionId),
    enabled,
  })
  // Recorded by URL, so a new grant or revision tries again.
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  // A grant can expire before a lazy image loads, so a failed load fetches one new grant.
  const [renewed, setRenewed] = useState(false)
  const grantUrl = previewUrl(query.data)
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
