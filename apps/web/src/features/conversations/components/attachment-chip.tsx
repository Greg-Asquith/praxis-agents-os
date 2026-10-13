// apps/web/src/features/conversations/components/attachment-chip.tsx

import { useQuery } from "@tanstack/react-query"
import { Loader2Icon, PaperclipIcon, XIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { isVideoAttachmentMediaType } from "@/features/conversations/attachments"
import { videoFileStatus } from "@/features/conversations/native-tools/video-tools"
import { fileQueryOptions } from "@/features/files/api/get-file"
import type { ComposerAttachment } from "./conversation-composer"
import { formatBytes } from "@/lib/format"
import { cn } from "@/lib/utils"

export function AttachmentChip({
  attachment,
  onRemove,
}: {
  attachment: ComposerAttachment
  onRemove: () => void
}) {
  const uploading = attachment.status === "uploading"
  const videoFileId =
    !uploading && isVideoAttachmentMediaType(attachment.mediaType) ? attachment.fileId : null
  return (
    <div className="bg-muted/60 flex max-w-full items-center gap-2 rounded-lg border-0 px-2 py-1 text-xs">
      {uploading ? (
        <Loader2Icon className="text-muted-foreground size-3.5 animate-spin" />
      ) : (
        <PaperclipIcon className="text-muted-foreground size-3.5" />
      )}
      <span className="min-w-0 truncate font-medium">{attachment.name}</span>
      {attachment.scope === "platform" ? <Badge variant="secondary">Platform</Badge> : null}
      {videoFileId ? (
        <VideoChipStatus fileId={videoFileId} />
      ) : (
        <span className="text-muted-foreground shrink-0">
          {uploading && attachment.uploadPercent !== undefined
            ? `${String(attachment.uploadPercent)}%`
            : formatBytes(attachment.sizeBytes)}
        </span>
      )}
      <Button
        aria-label={`Remove ${attachment.name}`}
        disabled={uploading}
        onClick={onRemove}
        size="icon-sm"
        type="button"
        variant="ghost"
      >
        <XIcon />
      </Button>
    </div>
  )
}

function VideoChipStatus({ fileId }: { fileId: string }) {
  const status = videoFileStatus(useQuery(fileQueryOptions(fileId)).data)
  return (
    <span
      className={cn(
        "flex shrink-0 items-center gap-1",
        status.kind === "error" ? "text-destructive" : "text-muted-foreground"
      )}
    >
      {status.kind === "preparing" ? (
        <Loader2Icon className="size-3 animate-spin motion-reduce:animate-none" />
      ) : null}
      {status.label}
    </span>
  )
}
