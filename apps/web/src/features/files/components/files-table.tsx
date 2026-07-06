// apps/web/src/features/files/components/files-table.ts

import { useState, type KeyboardEvent } from "react"
import {
  DownloadIcon,
  ExternalLinkIcon,
  FileIcon,
  FileTextIcon,
  HeadphonesIcon,
  ImageIcon,
  MoreHorizontalIcon,
  Trash2Icon,
  VideoIcon,
} from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { EmptyState } from "@/components/ui/empty-state"
import {
  ResponsiveList,
  ResponsiveListItem,
  ResponsiveListMeta,
} from "@/components/ui/responsive-list"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useDeleteFileMutation } from "@/features/files/api/delete-file"
import { FileStatusBadge } from "@/features/files/components/file-status-badge"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { fileCategoryLabel, relativeDateTime } from "@/features/files/format"
import type { FileContractCategory, WorkspaceFile } from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes } from "@/lib/format"

export function FilesTable({
  files,
  onOpenFile,
}: {
  files: WorkspaceFile[]
  onOpenFile: (fileId: string) => void
}) {
  const deleteMutation = useDeleteFileMutation()
  const [error, setError] = useState<string | null>(null)
  const [fileToDelete, setFileToDelete] = useState<WorkspaceFile | null>(null)

  async function handleOpen(file: WorkspaceFile, forceDownload: boolean) {
    setError(null)
    try {
      await openWorkspaceFile({ fileId: file.id, name: file.name }, { forceDownload })
    } catch (downloadError) {
      setError(getErrorMessage(downloadError))
    }
  }

  function handleDelete(file: WorkspaceFile) {
    setError(null)
    setFileToDelete(file)
  }

  async function confirmDeleteFile() {
    if (!fileToDelete) {
      return
    }

    try {
      await deleteMutation.mutateAsync({ fileId: fileToDelete.id })
      setFileToDelete(null)
    } catch (deleteError) {
      setError(getErrorMessage(deleteError))
      setFileToDelete(null)
    }
  }

  function handleOpenFileKeyDown(event: KeyboardEvent<HTMLTableRowElement>, fileId: string) {
    if (event.target !== event.currentTarget) {
      return
    }
    if (event.key !== "Enter" && event.key !== " ") {
      return
    }

    event.preventDefault()
    onOpenFile(fileId)
  }

  if (files.length === 0) {
    return (
      <EmptyState
        description="Upload files agents and teammates can read, revise, and reuse in this workspace."
        icon={<FileTextIcon className="size-5" />}
        size="compact"
        title="No files yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Delete file"
        confirmPendingLabel="Deleting"
        description={
          fileToDelete ? `This deletes ${fileToDelete.name}.` : "This deletes the selected file."
        }
        isPending={deleteMutation.isPending}
        onConfirm={confirmDeleteFile}
        onOpenChange={(open) => {
          if (!open) {
            setFileToDelete(null)
          }
        }}
        open={fileToDelete !== null}
        title="Delete file?"
      />
      <ResponsiveList>
        {files.map((file) => (
          <FileMobileRow
            file={file}
            isDeleting={deleteMutation.isPending}
            key={file.id}
            onDelete={handleDelete}
            onOpen={handleOpen}
            onOpenFile={onOpenFile}
          />
        ))}
      </ResponsiveList>

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Size</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {files.map((file) => (
              <TableRow
                aria-label={`Open details for ${file.name}`}
                className="hover:bg-muted/50 focus-visible:ring-ring cursor-pointer focus-visible:ring-2 focus-visible:outline-none"
                key={file.id}
                onClick={() => {
                  onOpenFile(file.id)
                }}
                onKeyDown={(event) => {
                  handleOpenFileKeyDown(event, file.id)
                }}
                tabIndex={0}
              >
                <TableCell>
                  <div className="flex min-w-56 items-center gap-3">
                    <FileCategoryIcon category={file.category} />
                    <div className="min-w-0">
                      <p className="truncate font-medium">{file.name}</p>
                      {file.description ? (
                        <p className="text-muted-foreground truncate text-xs">{file.description}</p>
                      ) : null}
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <Badge variant="outline">{fileCategoryLabel(file.category)}</Badge>
                    <span className="text-muted-foreground text-xs">{file.content_type}</span>
                  </div>
                </TableCell>
                <TableCell>{formatBytes(file.size_bytes)}</TableCell>
                <TableCell>
                  <FileStatusBadge status={file.processing_status} />
                </TableCell>
                <TableCell>{relativeDateTime(file.updated_at)}</TableCell>
                <TableCell
                  className="text-right"
                  onClick={(event) => {
                    event.stopPropagation()
                  }}
                >
                  <FileActions
                    file={file}
                    isDeleting={deleteMutation.isPending}
                    onDelete={handleDelete}
                    onOpen={handleOpen}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function FileMobileRow({
  file,
  isDeleting,
  onDelete,
  onOpen,
  onOpenFile,
}: {
  file: WorkspaceFile
  isDeleting: boolean
  onDelete: (file: WorkspaceFile) => void
  onOpen: (file: WorkspaceFile, forceDownload: boolean) => Promise<void>
  onOpenFile: (fileId: string) => void
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <FileCategoryIcon category={file.category} />
            <div className="min-w-0">
              <p className="truncate font-medium">{file.name}</p>
              <p className="text-muted-foreground truncate text-xs">{file.content_type}</p>
            </div>
          </div>
          <FileStatusBadge status={file.processing_status} />
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Type">
            <Badge variant="outline">{fileCategoryLabel(file.category)}</Badge>
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Size">{formatBytes(file.size_bytes)}</ResponsiveListMeta>
          <ResponsiveListMeta label="Updated">
            {relativeDateTime(file.updated_at)}
          </ResponsiveListMeta>
        </dl>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Button
            onClick={() => {
              onOpenFile(file.id)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Details
          </Button>
          <Button
            onClick={() => {
              void onOpen(file, false)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            <ExternalLinkIcon data-icon="inline-start" />
            Open
          </Button>
          <Button
            onClick={() => {
              void onOpen(file, true)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            <DownloadIcon data-icon="inline-start" />
            Download
          </Button>
          <Button
            disabled={isDeleting}
            onClick={() => {
              onDelete(file)
            }}
            size="sm"
            type="button"
            variant="destructive"
          >
            <Trash2Icon data-icon="inline-start" />
            Delete
          </Button>
        </div>
      </div>
    </ResponsiveListItem>
  )
}

function FileActions({
  file,
  isDeleting,
  onDelete,
  onOpen,
}: {
  file: WorkspaceFile
  isDeleting: boolean
  onDelete: (file: WorkspaceFile) => void
  onOpen: (file: WorkspaceFile, forceDownload: boolean) => Promise<void>
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button aria-label={`Actions for ${file.name}`} size="icon-sm" variant="ghost" />}
      >
        <MoreHorizontalIcon />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuItem
          onClick={() => {
            void onOpen(file, false)
          }}
        >
          <ExternalLinkIcon data-icon="inline-start" />
          Open
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => {
            void onOpen(file, true)
          }}
        >
          <DownloadIcon data-icon="inline-start" />
          Download
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={isDeleting}
          onClick={() => {
            onDelete(file)
          }}
          variant="destructive"
        >
          <Trash2Icon data-icon="inline-start" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function FileCategoryIcon({ category }: { category: FileContractCategory }) {
  return (
    <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-md border">
      {iconForCategory(category)}
    </span>
  )
}

function iconForCategory(category: FileContractCategory) {
  switch (category) {
    case "editable_text":
    case "ingestible_document":
      return <FileTextIcon className="size-4" />
    case "image":
      return <ImageIcon className="size-4" />
    case "video":
      return <VideoIcon className="size-4" />
    case "audio":
      return <HeadphonesIcon className="size-4" />
    default:
      return <FileIcon className="size-4" />
  }
}
