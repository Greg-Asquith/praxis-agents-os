// apps/web/src/features/files/components/files-table.ts

import { useState, type KeyboardEvent, type ReactNode } from "react"
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  CheckIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FileTextIcon,
  MoreHorizontalIcon,
  PencilIcon,
  Trash2Icon,
} from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { EmptyState } from "@/components/ui/empty-state"
import { PaginationControls } from "@/components/ui/pagination-controls"
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
import { FileThumbnail } from "@/features/files/components/file-thumbnail"
import { RenameFileDialog } from "@/features/files/components/rename-file-dialog"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { fileTypeLabel } from "@/features/files/format"
import type { FileSortDirection, FileSortField, WorkspaceFile } from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes, formatCompactDate, formatDateTime, relativeDateTime } from "@/lib/format"

const SORT_LABELS: Record<FileSortField, string> = {
  created_at: "Created",
  extension: "Type",
  name: "Name",
  processing_status: "Status",
  size_bytes: "Size",
  updated_at: "Updated",
}

const SORT_FIELDS: FileSortField[] = [
  "name",
  "extension",
  "size_bytes",
  "processing_status",
  "created_at",
  "updated_at",
]

export function FilesTable({
  emptyAction,
  files,
  isChangingView,
  limit,
  offset,
  onPageChange,
  onOpenFile,
  onSortChange,
  sortBy,
  sortDirection,
  total,
}: {
  emptyAction?: ReactNode
  files: WorkspaceFile[]
  isChangingView: boolean
  limit: number
  offset: number
  onPageChange: (offset: number) => void
  onOpenFile: (fileId: string) => void
  onSortChange: (sortBy: FileSortField, direction: FileSortDirection) => void
  sortBy: FileSortField
  sortDirection: FileSortDirection
  total: number
}) {
  const deleteMutation = useDeleteFileMutation()
  const [error, setError] = useState<string | null>(null)
  const [fileToDelete, setFileToDelete] = useState<WorkspaceFile | null>(null)
  const [fileToRename, setFileToRename] = useState<WorkspaceFile | null>(null)

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

  if (files.length === 0 && total === 0) {
    return (
      <EmptyState
        action={emptyAction}
        description="Upload files agents and teammates can read, revise, and reuse in this workspace."
        icon={<FileTextIcon className="size-5" />}
        size="compact"
        title="No files yet"
      />
    )
  }

  return (
    <div aria-busy={isChangingView} className="flex flex-col gap-3">
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Delete File"
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
      <RenameFileDialog
        file={fileToRename}
        onOpenChange={(open) => {
          if (!open) {
            setFileToRename(null)
          }
        }}
      />
      <MobileSortMenu
        disabled={isChangingView}
        onSortChange={onSortChange}
        sortBy={sortBy}
        sortDirection={sortDirection}
      />
      <ResponsiveList className={isChangingView ? "opacity-60" : undefined}>
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
              <SortableTableHead
                direction={sortDirection}
                field="name"
                onSortChange={onSortChange}
                sortBy={sortBy}
              />
              <SortableTableHead
                direction={sortDirection}
                field="extension"
                onSortChange={onSortChange}
                sortBy={sortBy}
              />
              <SortableTableHead
                direction={sortDirection}
                field="size_bytes"
                onSortChange={onSortChange}
                sortBy={sortBy}
              />
              <SortableTableHead
                direction={sortDirection}
                field="processing_status"
                onSortChange={onSortChange}
                sortBy={sortBy}
              />
              <SortableTableHead
                direction={sortDirection}
                field="created_at"
                onSortChange={onSortChange}
                sortBy={sortBy}
              />
              <SortableTableHead
                direction={sortDirection}
                field="updated_at"
                onSortChange={onSortChange}
                sortBy={sortBy}
              />
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className={isChangingView ? "opacity-60" : undefined}>
            {files.map((file) => (
              <TableRow
                aria-label={`Open Details for ${file.name}`}
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
                    <FileThumbnail file={file} />
                    <div className="min-w-0">
                      <p className="truncate font-medium">{file.name}</p>
                      {file.description ? (
                        <p className="text-muted-foreground truncate text-xs">{file.description}</p>
                      ) : null}
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant="outline">{fileTypeLabel(file)}</Badge>
                </TableCell>
                <TableCell>{formatBytes(file.size_bytes)}</TableCell>
                <TableCell>
                  <FileStatusBadge status={file.processing_status} />
                </TableCell>
                <TableCell title={formatDateTime(file.created_at)}>
                  {formatCompactDate(file.created_at)}
                </TableCell>
                <TableCell title={formatDateTime(file.updated_at)}>
                  {formatCompactDate(file.updated_at)}
                </TableCell>
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
                    onRename={setFileToRename}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <PaginationControls
        disabled={isChangingView}
        limit={limit}
        offset={offset}
        onPageChange={onPageChange}
        total={total}
      />
    </div>
  )
}

function SortableTableHead({
  direction,
  field,
  onSortChange,
  sortBy,
}: {
  direction: FileSortDirection
  field: FileSortField
  onSortChange: (field: FileSortField, direction: FileSortDirection) => void
  sortBy: FileSortField
}) {
  const isActive = sortBy === field
  const ariaSort = isActive ? (direction === "asc" ? "ascending" : "descending") : "none"
  const SortIcon = isActive ? (direction === "asc" ? ArrowUpIcon : ArrowDownIcon) : ArrowUpDownIcon

  return (
    <TableHead aria-sort={ariaSort}>
      <Button
        className="-ml-2"
        onClick={() => {
          onSortChange(
            field,
            isActive ? (direction === "asc" ? "desc" : "asc") : defaultDirection(field)
          )
        }}
        size="sm"
        type="button"
        variant="ghost"
      >
        {SORT_LABELS[field]}
        <SortIcon data-icon="inline-end" />
      </Button>
    </TableHead>
  )
}

function MobileSortMenu({
  disabled,
  onSortChange,
  sortBy,
  sortDirection,
}: {
  disabled: boolean
  onSortChange: (field: FileSortField, direction: FileSortDirection) => void
  sortBy: FileSortField
  sortDirection: FileSortDirection
}) {
  return (
    <div className="flex justify-end md:hidden">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button disabled={disabled} size="sm" type="button" variant="outline">
              <ArrowUpDownIcon data-icon="inline-start" />
              Sort: {SORT_LABELS[sortBy]}
            </Button>
          }
        />
        <DropdownMenuContent align="end">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Sort by</DropdownMenuLabel>
            {SORT_FIELDS.map((field) => (
              <DropdownMenuItem
                key={field}
                onClick={() => {
                  onSortChange(field, field === sortBy ? sortDirection : defaultDirection(field))
                }}
              >
                {SORT_LABELS[field]}
                {sortBy === field ? <CheckIcon className="ml-auto" /> : null}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Direction</DropdownMenuLabel>
            <DropdownMenuItem
              onClick={() => {
                onSortChange(sortBy, "asc")
              }}
            >
              Ascending
              {sortDirection === "asc" ? <CheckIcon className="ml-auto" /> : null}
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => {
                onSortChange(sortBy, "desc")
              }}
            >
              Descending
              {sortDirection === "desc" ? <CheckIcon className="ml-auto" /> : null}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function defaultDirection(field: FileSortField): FileSortDirection {
  return field === "name" || field === "extension" || field === "processing_status" ? "asc" : "desc"
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
            <FileThumbnail file={file} size="sm" />
            <div className="min-w-0">
              <p className="truncate font-medium">{file.name}</p>
            </div>
          </div>
          <FileStatusBadge status={file.processing_status} />
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Type">
            <Badge variant="outline">{fileTypeLabel(file)}</Badge>
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Size">{formatBytes(file.size_bytes)}</ResponsiveListMeta>
          <ResponsiveListMeta label="Created">
            {relativeDateTime(file.created_at)}
          </ResponsiveListMeta>
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
  onRename,
}: {
  file: WorkspaceFile
  isDeleting: boolean
  onDelete: (file: WorkspaceFile) => void
  onOpen: (file: WorkspaceFile, forceDownload: boolean) => Promise<void>
  onRename: (file: WorkspaceFile) => void
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
          onClick={() => {
            onRename(file)
          }}
        >
          <PencilIcon data-icon="inline-start" />
          Rename
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
