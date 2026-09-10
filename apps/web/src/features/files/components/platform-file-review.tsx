// apps/web/src/features/files/components/platform-file-review.tsx

import { useCallback, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { platformFilePreviewQueryOptions } from "@/features/files/api/platform-file-preview"
import { FileContentView } from "@/features/files/components/file-content-view"
import { FileStatusBadge } from "@/features/files/components/file-status-badge"
import type { WorkspaceFile } from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"

export function PlatformFileReview({ file }: { file: WorkspaceFile }) {
  const ready = file.processing_status === "ready"
  const preview = useQuery({ ...platformFilePreviewQueryOptions(file), enabled: ready })
  return (
    <section className="flex min-w-0 flex-col gap-4" aria-label="Platform file status">
      <div className="flex items-center gap-2">
        <Badge variant="secondary">Platform</Badge>
        <FileStatusBadge status={file.processing_status} />
      </div>
      {file.processing_status === "error" ? (
        <p role="alert" className="text-destructive text-sm">
          {file.processing_error ?? "This file could not be prepared. Upload it again to retry."}
        </p>
      ) : (
        <p role="status" className="text-muted-foreground text-sm">
          {file.is_published && file.published_revision_id === file.current_revision_id
            ? "This file is available in every workspace."
            : ready
              ? "This file is not available in other workspaces."
              : "Preparing this file. It is not yet available in other workspaces."}
        </p>
      )}
      {ready && preview.isPending ? <p role="status">Loading preview…</p> : null}
      {preview.error ? (
        <p role="alert" className="text-destructive text-sm">
          {getErrorMessage(preview.error)}
        </p>
      ) : null}
      {preview.data?.content !== null && preview.data?.content !== undefined ? (
        <FileContentView
          content={preview.data.content}
          name={file.name}
          mediaType={preview.data.mediaType}
        />
      ) : null}
      {preview.data?.blob ? (
        <PlatformBinaryPreview
          key={file.current_revision_id}
          blob={preview.data.blob}
          file={file}
        />
      ) : null}
    </section>
  )
}

function PlatformBinaryPreview({ blob, file }: { blob: Blob; file: WorkspaceFile }) {
  const [failed, setFailed] = useState(false)
  const previewRef = useCallback(
    (element: HTMLImageElement | HTMLVideoElement | null) => {
      if (!element) return
      const url = URL.createObjectURL(blob)
      element.src = url
      return () => {
        URL.revokeObjectURL(url)
      }
    },
    [blob]
  )
  if (failed)
    return (
      <p role="alert" className="text-destructive text-sm">
        This file could not be previewed.
      </p>
    )
  if (file.category === "image")
    return (
      <img
        alt={file.name}
        className="max-h-104 max-w-full object-contain"
        ref={previewRef}
        onError={() => {
          setFailed(true)
        }}
      />
    )
  return (
    <video
      controls
      className="max-h-104 w-full"
      ref={previewRef}
      onError={() => {
        setFailed(true)
      }}
    >
      <track kind="captions" />
    </video>
  )
}
