// apps/web/src/features/files/components/file-thumbnail.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { filePreviewQueryOptions } from "@/features/files/api/preview-file"
import { FileTypeIcon } from "@/features/files/components/file-type-icon"
import type { FileContractCategory, FileProcessingStatus } from "@/features/files/types"
import { cn } from "@/lib/utils"

type FileThumbnailProps = {
  file: {
    id: string
    category?: FileContractCategory
    content_type?: string
    extension?: string
    name?: string
    processing_status?: FileProcessingStatus
  }
  size?: "sm" | "md"
}

export function FileThumbnail({ file, size = "md" }: FileThumbnailProps) {
  const className = size === "sm" ? "size-9" : "size-10"

  if (file.category === "image" && file.processing_status === "ready") {
    return (
      <ImageThumbnail
        className={className}
        file={{ id: file.id, category: "image", processing_status: "ready" }}
      />
    )
  }

  return <FileIconTile className={className} file={file} />
}

function ImageThumbnail({
  className,
  file,
}: {
  className: string
  file: { id: string; category: "image"; processing_status: "ready" }
}) {
  const previewQuery = useQuery(filePreviewQueryOptions(file.id))
  const [imageFailed, setImageFailed] = useState(false)

  if (previewQuery.isPending || previewQuery.isError || imageFailed) {
    return <FileIconTile className={className} file={file} />
  }

  return (
    <img
      alt=""
      className={cn("shrink-0 rounded-md border object-cover", className)}
      loading="lazy"
      onError={() => {
        setImageFailed(true)
      }}
      src={previewQuery.data.preview.url}
    />
  )
}

function FileIconTile({
  className,
  file,
}: {
  className: string
  file: FileThumbnailProps["file"]
}) {
  return (
    <span
      className={cn(
        "bg-muted text-muted-foreground flex shrink-0 items-center justify-center rounded-md border",
        className
      )}
    >
      <FileTypeIcon
        className="size-6"
        file={{
          ...(file.category ? { category: file.category } : {}),
          ...(file.content_type ? { contentType: file.content_type } : {}),
          ...(file.extension ? { extension: file.extension } : {}),
          ...(file.name ? { name: file.name } : {}),
        }}
      />
    </span>
  )
}
