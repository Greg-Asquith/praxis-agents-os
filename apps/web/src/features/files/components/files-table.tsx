// apps/web/src/features/files/components/files-table.tsx

import { useState, type KeyboardEvent, type ReactNode } from "react"
import type { OnChangeFn, PaginationState, SortingState } from "@tanstack/react-table"
import {
  DownloadIcon,
  ExternalLinkIcon,
  FileTextIcon,
  MoreHorizontalIcon,
  PencilIcon,
  Trash2Icon,
} from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import {
  paginationStateFromServer,
  paginationStateToServer,
  sortingStateFromServer,
  sortingStateToServer,
} from "@/components/data-table/server-state"
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

const SORT_FIELDS = new Set<FileSortField>([
  "name",
  "extension",
  "size_bytes",
  "processing_status",
  "created_at",
  "updated_at",
])

const columnHelper = createAppColumnHelper<WorkspaceFile>()

const columns = columnHelper.columns([
  columnHelper.accessor("name", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => (
      <div className="flex min-w-56 items-center gap-3">
        <FileThumbnail file={row.original} />
        <div className="min-w-0">
          <p className="truncate font-medium">{row.original.name}</p>
          {row.original.description ? (
            <p className="text-muted-foreground truncate text-xs">{row.original.description}</p>
          ) : null}
        </div>
      </div>
    ),
    enableSorting: true,
    meta: { label: SORT_LABELS.name },
    sortDescFirst: false,
  }),
  columnHelper.accessor("extension", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => <Badge variant="outline">{fileTypeLabel(row.original)}</Badge>,
    enableSorting: true,
    meta: { label: SORT_LABELS.extension },
    sortDescFirst: false,
  }),
  columnHelper.accessor("size_bytes", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatBytes(getValue()),
    enableSorting: true,
    meta: { label: SORT_LABELS.size_bytes },
    sortDescFirst: true,
  }),
  columnHelper.accessor("processing_status", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <FileStatusBadge status={getValue()} />,
    enableSorting: true,
    meta: { label: SORT_LABELS.processing_status },
    sortDescFirst: false,
  }),
  columnHelper.accessor("created_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => (
      <span title={formatDateTime(getValue())}>{formatCompactDate(getValue())}</span>
    ),
    enableSorting: true,
    meta: { label: SORT_LABELS.created_at },
    sortDescFirst: true,
  }),
  columnHelper.accessor("updated_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => (
      <span title={formatDateTime(getValue())}>{formatCompactDate(getValue())}</span>
    ),
    enableSorting: true,
    meta: { label: SORT_LABELS.updated_at },
    sortDescFirst: true,
  }),
  columnHelper.display({
    id: "actions",
    header: ({ header }) => <header.ColumnHeader />,
    cell: () => null,
    meta: { label: "Actions", labelClassName: "sr-only" },
  }),
])

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
  const pagination = paginationStateFromServer({ limit, offset }, total)
  const sorting = sortingStateFromServer({ sort_by: sortBy, sort_direction: sortDirection })

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

  const table = useAppTable({
    columns,
    data: files,
    enableSortingRemoval: false,
    manualPagination: true,
    manualSorting: true,
    onPaginationChange: ((updater) => {
      const nextPagination = resolveUpdater(updater, pagination)
      onPageChange(paginationStateToServer(nextPagination).offset)
    }) satisfies OnChangeFn<PaginationState>,
    onSortingChange: ((updater) => {
      const nextSorting = resolveUpdater(updater, sorting)
      const nextParams = sortingStateToServer(nextSorting, SORT_FIELDS, {
        sort_by: sortBy,
        sort_direction: sortDirection,
      })
      onSortChange(nextParams.sort_by, nextParams.sort_direction)
    }) satisfies OnChangeFn<SortingState>,
    rowCount: total,
    state: { pagination, sorting },
  })

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
    <table.AppTable>
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
        <table.SortMenu className="md:hidden" disabled={isChangingView} />
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
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <table.AppHeader header={header} key={header.id}>
                      {() => <FileHeaderCell />}
                    </table.AppHeader>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody className={isChangingView ? "opacity-60" : undefined}>
              {table.getRowModel().rows.map((row) => (
                <TableRow
                  aria-label={`Open Details for ${row.original.name}`}
                  className="hover:bg-muted/50 focus-visible:ring-ring cursor-pointer focus-visible:ring-2 focus-visible:outline-none"
                  key={row.id}
                  onClick={() => {
                    onOpenFile(row.original.id)
                  }}
                  onKeyDown={(event) => {
                    handleOpenFileKeyDown(event, row.original.id)
                  }}
                  tabIndex={0}
                >
                  {row.getVisibleCells().map((cell) => (
                    <table.AppCell cell={cell} key={cell.id}>
                      {() => (
                        <FileBodyCell
                          isDeleting={deleteMutation.isPending}
                          onDelete={handleDelete}
                          onOpen={handleOpen}
                          onRename={setFileToRename}
                        />
                      )}
                    </table.AppCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <table.Pagination disabled={isChangingView} total={total} />
      </div>
    </table.AppTable>
  )
}

function FileHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function FileBodyCell({
  isDeleting,
  onDelete,
  onOpen,
  onRename,
}: {
  isDeleting: boolean
  onDelete: (file: WorkspaceFile) => void
  onOpen: (file: WorkspaceFile, forceDownload: boolean) => Promise<void>
  onRename: (file: WorkspaceFile) => void
}) {
  const cell = useCellContext()
  const row = useTableContext<WorkspaceFile>().getRow(cell.row.id)
  const isActions = cell.column.id === "actions"
  return (
    <TableCell
      className={isActions ? "text-right" : undefined}
      onClick={
        isActions
          ? (event) => {
              event.stopPropagation()
            }
          : undefined
      }
    >
      {isActions ? (
        <FileActions
          file={row.original}
          isDeleting={isDeleting}
          onDelete={onDelete}
          onOpen={onOpen}
          onRename={onRename}
        />
      ) : (
        <cell.FlexRender />
      )}
    </TableCell>
  )
}

function resolveUpdater<T>(updater: T | ((previous: T) => T), previous: T): T {
  return typeof updater === "function" ? (updater as (value: T) => T)(previous) : updater
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
      <DropdownMenuContent align="end">
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
