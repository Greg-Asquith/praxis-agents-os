// apps/web/src/features/conversations/components/message-attachment-card.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { DownloadIcon, ExternalLinkIcon, ImageIcon, Loader2Icon, PaperclipIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  isImageAttachmentMediaType,
  type MessageAttachment,
} from "@/features/conversations/attachments"
import { filePreviewQueryOptions } from "@/features/files/api/preview-file"
import { FileCard } from "@/features/files/components/file-card"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes } from "@/lib/format"

export function MessageAttachmentCard({ attachment }: { attachment: MessageAttachment }) {
  if (isImageAttachmentMediaType(attachment.mediaType)) {
    return <ImageAttachmentCard attachment={attachment} />
  }

  return <FileCard file={fileCardFromAttachment(attachment)} />
}

function ImageAttachmentCard({ attachment }: { attachment: MessageAttachment }) {
  const [actionError, setActionError] = useState<string | null>(null)
  const previewQuery = useQuery(filePreviewQueryOptions(attachment.fileId))
  const displayName = attachment.name ?? "Image attachment"
  const previewUrl = previewQuery.data?.preview.url
  const previewError = previewQuery.isError ? getErrorMessage(previewQuery.error) : null

  async function handleOpen(forceDownload: boolean) {
    setActionError(null)
    try {
      await openWorkspaceFile(fileCardFromAttachment(attachment), { forceDownload })
    } catch (downloadError) {
      setActionError(getErrorMessage(downloadError))
    }
  }

  return (
    <div className="bg-background/80 w-full max-w-sm overflow-hidden rounded-md border">
      <div className="bg-muted/40 flex min-h-36 items-center justify-center overflow-hidden">
        {previewQuery.isLoading ? (
          <div className="text-muted-foreground flex items-center gap-2 text-xs">
            <Loader2Icon className="size-3.5 animate-spin" />
            Loading preview
          </div>
        ) : previewUrl ? (
          <img
            alt={displayName}
            className="max-h-80 w-full object-contain"
            loading="lazy"
            src={previewUrl}
          />
        ) : (
          <div className="text-muted-foreground flex flex-col items-center gap-2 px-4 py-8 text-center text-xs">
            <ImageIcon className="size-5" />
            <span>{previewError ?? "Preview unavailable"}</span>
          </div>
        )}
      </div>
      <div className="flex min-w-0 items-center justify-between gap-3 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <PaperclipIcon className="text-muted-foreground size-3.5 shrink-0" />
          <div className="min-w-0">
            <p className="truncate text-xs font-medium">{displayName}</p>
            <p className="text-muted-foreground truncate text-xs">
              {attachment.mediaType}
              {typeof attachment.sizeBytes === "number"
                ? ` · ${formatBytes(attachment.sizeBytes)}`
                : ""}
            </p>
            {actionError ? <p className="text-destructive mt-1 text-xs">{actionError}</p> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            aria-label={`Open ${displayName}`}
            onClick={() => {
              void handleOpen(false)
            }}
            size="icon-sm"
            type="button"
            variant="ghost"
          >
            <ExternalLinkIcon />
          </Button>
          <Button
            aria-label={`Download ${displayName}`}
            onClick={() => {
              void handleOpen(true)
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
  )
}

function fileCardFromAttachment(attachment: MessageAttachment) {
  return {
    contentType: attachment.mediaType,
    fileId: attachment.fileId,
    name: attachment.name ?? attachment.mediaType,
    ...(typeof attachment.sizeBytes === "number" ? { sizeBytes: attachment.sizeBytes } : {}),
  }
}
