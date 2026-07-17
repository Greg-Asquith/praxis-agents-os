// apps/web/src/features/files/components/file-thumbnail.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { FileIcon, FileTextIcon, HeadphonesIcon, ImageIcon, VideoIcon } from "lucide-react"

import { filePreviewQueryOptions } from "@/features/files/api/preview-file"
import type { FileContractCategory, FileProcessingStatus } from "@/features/files/types"
import { cn } from "@/lib/utils"

type FileThumbnailProps = {
  file: {
    id: string
    category?: FileContractCategory
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

  return (
    <FileIconTile className={className} {...(file.category ? { category: file.category } : {})} />
  )
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
    return <FileIconTile category={file.category} className={className} />
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
  category,
  className,
}: {
  category?: FileContractCategory
  className: string
}) {
  return (
    <span
      className={cn(
        "bg-muted text-muted-foreground flex shrink-0 items-center justify-center rounded-md border",
        className
      )}
    >
      {iconForCategory(category)}
    </span>
  )
}

function iconForCategory(category?: FileContractCategory) {
  switch (category) {
    case "editable_text":
    case "ingestible_document":
      return <FileTextIcon className="size-4" />
    case "image":
      return <ImageIcon className="size-4" />
    case "video":
      return <VideoIcon className="size-4" />
    case "audio":
      return <HeadphonesIcon className="size-4" />
    case "html":
      return <FileIcon className="size-4" />
    case undefined:
      return <FileIcon className="size-4" />
    default:
      return <FileIcon className="size-4" />
  }
}
