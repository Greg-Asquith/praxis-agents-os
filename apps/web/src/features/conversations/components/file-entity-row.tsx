// apps/web/src/features/conversations/components/file-entity-row.tsx

import { useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { DownloadIcon, MoreHorizontalIcon, PencilIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { FileEntitySnapshot } from "@/features/conversations/file-tools"
import { fileQueryOptions } from "@/features/files/api/get-file"
import { FileDetailModal } from "@/features/files/components/file-detail-modal"
import { FileThumbnail } from "@/features/files/components/file-thumbnail"
import { RenameFileDialog } from "@/features/files/components/rename-file-dialog"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { fileCategoryLabel } from "@/features/files/format"
import type { WorkspaceFile } from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes, formatCompactDate } from "@/lib/format"

export function FileEntityRow({ file }: { file: FileEntitySnapshot }) {
  const queryClient = useQueryClient()
  const openButtonRef = useRef<HTMLButtonElement>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [fileToRename, setFileToRename] = useState<WorkspaceFile | null>(null)
  const [pendingAction, setPendingAction] = useState<"download" | "rename" | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleDownload() {
    setError(null)
    setPendingAction("download")
    try {
      await openWorkspaceFile(file, { forceDownload: true })
    } catch (downloadError) {
      setError(getErrorMessage(downloadError))
    } finally {
      setPendingAction(null)
    }
  }

  async function handleRename() {
    setError(null)
    setPendingAction("rename")
    try {
      const currentFile = await queryClient.fetchQuery({
        ...fileQueryOptions(file.fileId),
        staleTime: 0,
      })
      setFileToRename(currentFile)
    } catch (loadError) {
      setError(getErrorMessage(loadError))
    } finally {
      setPendingAction(null)
    }
  }

  function handleDetailOpenChange(open: boolean) {
    setDetailOpen(open)
    if (!open) {
      openButtonRef.current?.focus()
    }
  }

  return (
    <>
      <div className="hover:bg-background/70 focus-within:bg-background/70 min-w-0 rounded-md">
        <div className="flex min-w-0 items-center gap-1">
          <Button
            aria-label={`View details for ${file.name}`}
            className="h-auto min-w-0 flex-1 justify-start gap-2.5 px-1.5 py-2 text-left"
            onClick={() => {
              setDetailOpen(true)
            }}
            ref={openButtonRef}
            type="button"
            variant="ghost"
          >
            <FileThumbnail
              file={{
                id: file.fileId,
                ...(file.category ? { category: file.category } : {}),
                ...(file.processingStatus ? { processing_status: file.processingStatus } : {}),
              }}
              size="sm"
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{file.name}</span>
              <span className="text-muted-foreground block truncate text-xs font-normal">
                {fileEntityMeta(file)}
              </span>
            </span>
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  aria-label={`Actions for ${file.name}`}
                  disabled={pendingAction !== null}
                  size="icon-sm"
                  type="button"
                  variant="ghost"
                />
              }
            >
              <MoreHorizontalIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => {
                  void handleRename()
                }}
              >
                <PencilIcon data-icon="inline-start" />
                Rename
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  void handleDownload()
                }}
              >
                <DownloadIcon data-icon="inline-start" />
                Download
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {error ? (
          <p className="text-destructive px-1.5 pb-2 text-xs" role="alert">
            {error}
          </p>
        ) : null}
      </div>

      <FileDetailModal
        fileId={file.fileId}
        onOpenChange={handleDetailOpenChange}
        open={detailOpen}
      />
      <RenameFileDialog
        file={fileToRename}
        onOpenChange={(open) => {
          if (!open) {
            setFileToRename(null)
          }
        }}
      />
    </>
  )
}

function fileEntityMeta(file: FileEntitySnapshot): string {
  const parts: string[] = []
  if (typeof file.sizeBytes === "number") {
    parts.push(formatBytes(file.sizeBytes))
  } else if (file.category) {
    parts.push(fileCategoryLabel(file.category))
  } else {
    parts.push("Workspace file")
  }
  if (file.updatedAt) {
    parts.push(`Updated ${formatCompactDate(file.updatedAt)}`)
  }
  return parts.join(" · ")
}
