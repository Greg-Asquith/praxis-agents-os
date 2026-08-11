// apps/web/src/features/conversations/components/media-input-preview.tsx

import { useQuery } from "@tanstack/react-query"
import { ImageIcon, Loader2Icon, VideoIcon } from "lucide-react"

import { filePreviewQueryOptions } from "@/features/files/api/preview-file"
import { getErrorMessage } from "@/lib/api/errors"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

type MediaKind = "image" | "video"

type MediaReference = {
  id: string
  label: string
}

export function MediaInputPreview({ args, kind }: { args: unknown; kind: MediaKind }) {
  const references = mediaReferences(args, kind)
  if (references.length === 0) {
    return null
  }

  return (
    <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-3" role="list">
      {references.map((reference) => (
        <MediaPreviewCard key={reference.id} kind={kind} reference={reference} />
      ))}
    </div>
  )
}

function MediaPreviewCard({ kind, reference }: { kind: MediaKind; reference: MediaReference }) {
  const previewQuery = useQuery(filePreviewQueryOptions(reference.id))
  const previewUrl = previewQuery.data?.preview.url
  const Icon = kind === "image" ? ImageIcon : VideoIcon

  return (
    <figure
      className={cn(
        "bg-muted/30 relative min-w-0 overflow-hidden rounded-t-md border",
        kind === "video" && "col-span-2 sm:col-span-3"
      )}
      role="listitem"
    >
      <div
        className={cn(
          "flex items-center justify-center overflow-hidden",
          kind === "image" ? "aspect-square" : "aspect-video"
        )}
      >
        {previewQuery.isPending ? (
          <Loader2Icon
            aria-label={`Loading preview for ${reference.label}`}
            className="text-muted-foreground size-5 animate-spin motion-reduce:animate-none"
          />
        ) : previewUrl ? (
          kind === "image" ? (
            <img
              alt={reference.label}
              className="size-full object-cover"
              loading="lazy"
              src={previewUrl}
            />
          ) : (
            <video
              aria-label={`Preview of ${reference.label}`}
              className="size-full object-cover"
              muted
              playsInline
              preload="metadata"
              src={previewUrl}
            />
          )
        ) : (
          <div className="text-muted-foreground flex flex-col items-center gap-1.5 px-3 text-center text-xs">
            <Icon className="size-5" />
            <span>
              {previewQuery.isError ? getErrorMessage(previewQuery.error) : "Preview unavailable"}
            </span>
          </div>
        )}
      </div>
      <figcaption className="bg-background/90 absolute inset-x-0 bottom-0 truncate border-t px-2 py-1.5 text-xs font-medium backdrop-blur-sm">
        {reference.label}
      </figcaption>
    </figure>
  )
}

function mediaReferences(args: unknown, kind: MediaKind): MediaReference[] {
  if (!isRecord(args)) {
    return []
  }
  const values = kind === "image" ? args["file_ids"] : [args["file_id"]]
  if (!Array.isArray(values)) {
    return []
  }
  return values.flatMap((value) => {
    if (!isRecord(value) || typeof value["entity_id"] !== "string") {
      return []
    }
    return [
      {
        id: value["entity_id"],
        label:
          typeof value["label"] === "string" && value["label"].trim()
            ? value["label"]
            : kind === "image"
              ? "Source image"
              : "Source video",
      },
    ]
  })
}
