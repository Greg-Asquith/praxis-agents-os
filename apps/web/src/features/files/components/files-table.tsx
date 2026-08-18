// apps/web/src/features/files/components/files-table.tsx

import { useEffect, useReducer, useState, type KeyboardEvent, type ReactNode } from "react"
import type { OnChangeFn, PaginationState, SortingState } from "@tanstack/react-table"
import {
  DownloadIcon,
  ExternalLinkIcon,
  FileTextIcon,
  FolderInputIcon,
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
import { Checkbox } from "@/components/ui/checkbox"
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useDeleteFileMutation } from "@/features/files/api/delete-file"
import { FileStatusBadge } from "@/features/files/components/file-status-badge"
import { FileThumbnail } from "@/features/files/components/file-thumbnail"
import { RenameFileDialog } from "@/features/files/components/rename-file-dialog"
import { MoveFilesDialog } from "@/features/files/components/move-files-dialog"
import {
  fileSelectionReducer,
  initialFileSelectionState,
} from "@/features/files/components/file-selection"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { fileTypeLabel } from "@/features/files/format"
import type {
  FileFolder,
  FileSortDirection,
  FileSortField,
  WorkspaceFile,
} from "@/features/files/types"
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

const EMPTY_FOLDERS: FileFolder[] = []

const columnHelper = createAppColumnHelper<WorkspaceFile>()

const columns = columnHelper.columns([
  columnHelper.accessor("name", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => (
      <div className="flex max-w-full min-w-0 items-center gap-3">
        <FileThumbnail file={row.original} />
        <div className="min-w-0 flex-1">
          <FileNameTooltip name={row.original.name} />
          {row.original.description ? (
            <p className="text-muted-foreground truncate text-xs">{row.original.description}</p>
          ) : null}
        </div>
      </div>
    ),
    enableSorting: true,
    meta: { headClassName: "w-auto max-w-0", label: SORT_LABELS.name },
    sortDescFirst: false,
  }),
  columnHelper.accessor("extension", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => <Badge variant="outline">{fileTypeLabel(row.original)}</Badge>,
    enableSorting: true,
    meta: { headClassName: "w-24", label: SORT_LABELS.extension },
    sortDescFirst: false,
  }),
  columnHelper.accessor("size_bytes", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatBytes(getValue()),
    enableSorting: true,
    meta: { headClassName: "w-24", label: SORT_LABELS.size_bytes },
    sortDescFirst: true,
  }),
  columnHelper.accessor("processing_status", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <FileStatusBadge status={getValue()} />,
    enableSorting: true,
    meta: { headClassName: "w-28", label: SORT_LABELS.processing_status },
    sortDescFirst: false,
  }),
  columnHelper.accessor("created_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => (
      <span title={formatDateTime(getValue())}>{formatCompactDate(getValue())}</span>
    ),
    enableSorting: true,
    meta: { headClassName: "w-28", label: SORT_LABELS.created_at },
    sortDescFirst: true,
  }),
  columnHelper.accessor("updated_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => (
      <span title={formatDateTime(getValue())}>{formatCompactDate(getValue())}</span>
    ),
    enableSorting: true,
    meta: { headClassName: "w-28", label: SORT_LABELS.updated_at },
    sortDescFirst: true,
  }),
  columnHelper.display({
    id: "actions",
    header: ({ header }) => <header.ColumnHeader />,
    cell: () => null,
    meta: { headClassName: "w-12", label: "Actions", labelClassName: "sr-only" },
  }),
])

export function FilesTable({
  emptyAction,
  emptyDescription = "Upload files agents and teammates can read, revise, and reuse in this workspace.",
  emptyTitle = "No files yet",
  files,
  folders = EMPTY_FOLDERS,
  isChangingView,
  limit,
  offset,
  onPageChange,
  onOpenFile,
  onSortChange,
  selectionScope,
  sortBy,
  sortDirection,
  total,
}: {
  emptyAction?: ReactNode
  emptyDescription?: string
  emptyTitle?: string
  files: WorkspaceFile[]
  folders?: FileFolder[]
  isChangingView: boolean
  limit: number
  offset: number
  onPageChange: (offset: number) => void
  onOpenFile: (fileId: string) => void
  onSortChange: (sortBy: FileSortField, direction: FileSortDirection) => void
  selectionScope: string
  sortBy: FileSortField
  sortDirection: FileSortDirection
  total: number
}) {
  const deleteMutation = useDeleteFileMutation()
  const [error, setError] = useState<string | null>(null)
  const [fileToDelete, setFileToDelete] = useState<WorkspaceFile | null>(null)
  const [fileToRename, setFileToRename] = useState<WorkspaceFile | null>(null)
  const [selection, dispatchSelection] = useReducer(
    fileSelectionReducer,
    selectionScope,
    initialFileSelectionState
  )
  const pagination = paginationStateFromServer({ limit, offset }, total)
  const sorting = sortingStateFromServer({ sort_by: sortBy, sort_direction: sortDirection })
  const selectedFileIds = files
    .filter((file) => selection.selectedIds.has(file.id))
    .map((file) => file.id)

  useEffect(() => {
    dispatchSelection({ scope: selectionScope, type: "scope-change" })
  }, [selectionScope])

  function setFileSelected(fileId: string, selected: boolean) {
    dispatchSelection({ fileId, selected, type: "selection-change" })
  }

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
        description={emptyDescription}
        icon={<FileTextIcon className="size-5" />}
        size="compact"
        title={emptyTitle}
      />
    )
  }

  return (
    <table.AppTable>
      <TooltipProvider>
        <div aria-busy={isChangingView} className="flex max-w-full min-w-0 flex-col gap-3">
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
          <ConfirmDialog
            confirmIcon={<Trash2Icon data-icon="inline-start" />}
            confirmLabel="Delete File"
            confirmPendingLabel="Deleting"
            description={
              fileToDelete
                ? `This deletes ${fileToDelete.name}.`
                : "This deletes the selected file."
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
          <MoveFilesDialog
            fileIds={selection.moveFileIds}
            folders={folders}
            open={selection.moveFileIds.length > 0}
            onOpenChange={(open) => {
              if (!open) dispatchSelection({ type: "move-close" })
            }}
            onMoved={() => {
              dispatchSelection({ type: "move-success" })
            }}
          />
          {selectedFileIds.length > 0 ? (
            <div className="flex items-center justify-end">
              <div className="bg-muted/40 flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                <p className="text-sm">{String(selectedFileIds.length)} selected</p>
                <Button
                  onClick={() => {
                    dispatchSelection({ fileIds: selectedFileIds, type: "move-open" })
                  }}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  <FolderInputIcon data-icon="inline-start" />
                  Move to Folder…
                </Button>
              </div>
            </div>
          ) : null}
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
                onMove={(selected) => {
                  dispatchSelection({ fileIds: [selected.id], type: "move-open" })
                }}
                selected={selection.selectedIds.has(file.id)}
                onSelectedChange={(selected) => {
                  setFileSelected(file.id, selected)
                }}
              />
            ))}
          </ResponsiveList>

          <div className="hidden max-w-full min-w-0 overflow-hidden md:block">
            <Table className="max-w-full table-fixed">
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
                            onMove={(file) => {
                              dispatchSelection({ fileIds: [file.id], type: "move-open" })
                            }}
                            selected={selection.selectedIds.has(row.original.id)}
                            onSelectedChange={(selected) => {
                              setFileSelected(row.original.id, selected)
                            }}
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
      </TooltipProvider>
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
  onMove,
  selected,
  onSelectedChange,
}: {
  isDeleting: boolean
  onDelete: (file: WorkspaceFile) => void
  onOpen: (file: WorkspaceFile, forceDownload: boolean) => Promise<void>
  onRename: (file: WorkspaceFile) => void
  onMove: (file: WorkspaceFile) => void
  selected: boolean
  onSelectedChange: (selected: boolean) => void
}) {
  const cell = useCellContext()
  const row = useTableContext<WorkspaceFile>().getRow(cell.row.id)
  const columnId = cell.column.id
  const isActions = columnId === "actions"
  return (
    <TableCell
      className={`${fileColumnWidthClass(columnId)} ${isActions ? "text-right" : ""}`}
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
          onMove={onMove}
        />
      ) : (
        <div className="flex max-w-full min-w-0 items-center gap-3">
          {cell.column.id === "name" ? (
            <Checkbox
              aria-label={`Select ${row.original.name}`}
              checked={selected}
              onClick={(event) => {
                event.stopPropagation()
              }}
              onCheckedChange={(checked) => {
                onSelectedChange(checked)
              }}
            />
          ) : null}
          <cell.FlexRender />
        </div>
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
  onMove,
  selected,
  onSelectedChange,
}: {
  file: WorkspaceFile
  isDeleting: boolean
  onDelete: (file: WorkspaceFile) => void
  onOpen: (file: WorkspaceFile, forceDownload: boolean) => Promise<void>
  onOpenFile: (fileId: string) => void
  onMove: (file: WorkspaceFile) => void
  selected: boolean
  onSelectedChange: (selected: boolean) => void
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <FileThumbnail file={file} size="sm" />
            <div className="min-w-0 flex-1">
              <FileNameTooltip name={file.name} />
            </div>
          </div>
          <FileStatusBadge status={file.processing_status} />
          <Checkbox
            aria-label={`Select ${file.name}`}
            checked={selected}
            onClick={(event) => {
              event.stopPropagation()
            }}
            onCheckedChange={(checked) => {
              onSelectedChange(checked)
            }}
          />
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

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Button
            onClick={() => {
              onMove(file)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            <FolderInputIcon data-icon="inline-start" />
            Move
          </Button>
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

function FileNameTooltip({ name }: { name: string }) {
  return (
    <Tooltip>
      <TooltipTrigger className="block max-w-full truncate text-left font-medium" render={<span />}>
        {name}
      </TooltipTrigger>
      <TooltipContent className="max-w-sm wrap-break-word">{name}</TooltipContent>
    </Tooltip>
  )
}

function fileColumnWidthClass(columnId: string): string {
  switch (columnId) {
    case "name":
      return "w-auto max-w-0"
    case "processing_status":
      return "w-28"
    case "created_at":
    case "updated_at":
      return "w-28"
    case "actions":
      return "w-12"
    default:
      return "w-24"
  }
}

function FileActions({
  file,
  isDeleting,
  onDelete,
  onOpen,
  onRename,
  onMove,
}: {
  file: WorkspaceFile
  isDeleting: boolean
  onDelete: (file: WorkspaceFile) => void
  onOpen: (file: WorkspaceFile, forceDownload: boolean) => Promise<void>
  onRename: (file: WorkspaceFile) => void
  onMove: (file: WorkspaceFile) => void
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
        <DropdownMenuItem
          onClick={() => {
            onMove(file)
          }}
        >
          <FolderInputIcon data-icon="inline-start" />
          Move to Folder…
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
