// apps/web/src/integrations/outlook_mail/components/attachment.tsx

import { PaperclipIcon } from "lucide-react"

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { Badge } from "@/components/ui/badge"
import type { OutlookAttachmentContent } from "@/integrations/outlook_mail/lib/attachments"
import { formatBytes } from "@/lib/format"

export function OutlookAttachmentView({ attachment }: { attachment: OutlookAttachmentContent }) {
  const facts = [
    attachment.contentType,
    attachment.sizeBytes === null ? null : formatBytes(attachment.sizeBytes),
  ].filter((fact): fact is string => Boolean(fact))
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 items-start gap-2.5">
        <div className="bg-muted text-muted-foreground mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md">
          <PaperclipIcon className="size-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium wrap-break-word">{attachment.name}</p>
          {facts.length > 0 ? (
            <p className="text-muted-foreground mt-0.5 text-xs">{facts.join(" · ")}</p>
          ) : null}
        </div>
        {attachment.truncated ? <Badge variant="warning">64 KiB limit reached</Badge> : null}
      </div>
      <div className="border-border bg-muted/20 max-h-96 overflow-auto rounded-lg border p-3">
        <MarkdownContent content={attachment.markdown} />
      </div>
    </div>
  )
}
