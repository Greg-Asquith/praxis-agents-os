// apps/web/src/features/files/components/file-card.ts

import { useState } from "react"
import { DownloadIcon, ExternalLinkIcon, FileIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { fileCategoryLabel } from "@/features/files/format"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes } from "@/lib/format"

export type FileCardFile = {
  category?: string
  contentType?: string
  fileId: string
  name: string
  sizeBytes?: number
}

export function FileCard({ file }: { file: FileCardFile }) {
  const [error, setError] = useState<string | null>(null)

  async function handleOpen(forceDownload: boolean) {
    setError(null)
    try {
      await openWorkspaceFile(file, { forceDownload })
    } catch (downloadError) {
      setError(getErrorMessage(downloadError))
    }
  }

  return (
    <div className="bg-muted/40 flex min-w-0 items-center justify-between gap-3 rounded-md border p-3">
      <div className="flex min-w-0 items-center gap-3">
        <div className="bg-background text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-md border">
          <FileIcon className="size-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{file.name}</p>
          <p className="text-muted-foreground truncate text-xs">
            {file.category ? fileCategoryLabel(file.category) : "Workspace file"}
            {file.contentType ? ` · ${file.contentType}` : ""}
            {typeof file.sizeBytes === "number" ? ` · ${formatBytes(file.sizeBytes)}` : ""}
          </p>
          {error ? <p className="text-destructive mt-1 text-xs">{error}</p> : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          aria-label={`Open ${file.name}`}
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
          aria-label={`Download ${file.name}`}
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
  )
}
