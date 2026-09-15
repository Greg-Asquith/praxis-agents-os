// apps/web/src/integrations/sharepoint/components/file-content.tsx

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { Badge } from "@/components/ui/badge"
import type { SharePointFileContent } from "@/integrations/sharepoint/lib/file-content"
import { formatBytes } from "@/lib/format"

export function SharePointFileView({ file }: { file: SharePointFileContent }) {
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium wrap-break-word">{file.name}</p>
          <p className="text-muted-foreground mt-0.5 text-xs wrap-break-word">
            {file.contentType} · {formatBytes(file.sizeBytes)}
          </p>
          {file.webUrl ? (
            <a
              className="text-link hover:text-primary text-xs underline underline-offset-2"
              href={file.webUrl}
              rel="noopener noreferrer"
              target="_blank"
            >
              Open in SharePoint
            </a>
          ) : null}
        </div>
        {file.truncated ? <Badge variant="warning">64 KiB limit reached</Badge> : null}
      </div>
      <div className="border-border bg-muted/20 max-h-96 overflow-auto rounded-lg border p-3">
        <MarkdownContent content={file.markdown} />
      </div>
    </div>
  )
}
