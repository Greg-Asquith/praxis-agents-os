// apps/web/src/integrations/sharepoint/components/file-content.tsx

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { Badge } from "@/components/ui/badge"
import { SharePointFileHeading } from "@/integrations/sharepoint/components/file-heading"
import type { SharePointFileContent } from "@/integrations/sharepoint/lib/file-content"
import { formatBytes } from "@/lib/format"

export function SharePointFileView({ file }: { file: SharePointFileContent }) {
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 flex-wrap items-start gap-2">
        <SharePointFileHeading name={file.name} webUrl={file.webUrl}>
          <p className="text-muted-foreground mt-0.5 text-xs wrap-break-word">
            {file.contentType} · {formatBytes(file.sizeBytes)}
          </p>
        </SharePointFileHeading>
        {file.truncated ? <Badge variant="secondary">More content available</Badge> : null}
        {file.limitReached ? <Badge variant="warning">File size limit reached</Badge> : null}
      </div>
      {file.offset > 0 || file.endOffset < file.totalBytes ? (
        <p className="text-muted-foreground text-xs">
          {file.offset === 0
            ? `Showing the first ${formatBytes(file.endOffset)} of ${formatBytes(file.totalBytes)}`
            : `Showing ${formatBytes(file.endOffset - file.offset)} starting ${formatBytes(file.offset)} into the file`}
        </p>
      ) : null}
      <div className="border-border bg-muted/20 max-h-96 overflow-auto rounded-lg border p-3">
        <MarkdownContent content={file.markdown} />
      </div>
    </div>
  )
}
