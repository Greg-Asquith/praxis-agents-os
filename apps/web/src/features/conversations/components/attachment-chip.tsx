// apps/web/src/features/conversations/components/attachment-chip.tsx

import { Loader2Icon, PaperclipIcon, XIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { ComposerAttachment } from "./conversation-composer"
import { formatBytes } from "@/lib/format"

export function AttachmentChip({
  attachment,
  onRemove,
}: {
  attachment: ComposerAttachment
  onRemove: () => void
}) {
  return (
    <div className="bg-muted/50 flex max-w-full items-center gap-2 rounded-md border px-2 py-1 text-xs">
      {attachment.status === "uploading" ? (
        <Loader2Icon className="text-muted-foreground size-3.5 animate-spin" />
      ) : (
        <PaperclipIcon className="text-muted-foreground size-3.5" />
      )}
      <span className="min-w-0 truncate font-medium">{attachment.name}</span>
      <span className="text-muted-foreground shrink-0">{formatBytes(attachment.sizeBytes)}</span>
      <Button
        aria-label={`Remove ${attachment.name}`}
        disabled={attachment.status === "uploading"}
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
