// apps/web/src/integrations/saved-file-summary.tsx

import { WorkspaceFileMedia } from "@/components/tool-ui/workspace-file-media"
import { workspaceMediaKind } from "@/components/tool-ui/workspace-file-preview"
import type { SavedFile } from "@/components/tool-ui/saved-file"
import { formatBytes } from "@/lib/format"

export function SavedFileSummary({ file }: { file: SavedFile }) {
  const media = workspaceMediaKind(file.contentType)
  return (
    <div className="grid min-w-0 gap-2">
      {media ? <WorkspaceFileMedia fileId={file.fileId} kind={media} name={file.name} /> : null}
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
    </div>
  )
}
