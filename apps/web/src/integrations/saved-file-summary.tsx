// apps/web/src/integrations/saved-file-summary.tsx

import type { SavedFile } from "@/integrations/saved-file"
import { formatBytes } from "@/lib/format"

export function SavedFileSummary({ file }: { file: SavedFile }) {
  return (
    <div className="grid min-w-0 gap-1">
      <p className="text-muted-foreground text-xs">Saved in Files</p>
      <p className="text-sm font-medium wrap-break-word">{file.name}</p>
      <p className="text-muted-foreground text-xs wrap-break-word">
        {file.contentType} · {formatBytes(file.sizeBytes)}
      </p>
      <a
        className="text-link hover:text-primary text-xs underline underline-offset-2"
        href={file.fileHref}
      >
        Open in Files
      </a>
    </div>
  )
}
