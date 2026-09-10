// apps/web/src/features/files/components/files-table.tsx

import { useEffect, useReducer, useState, type KeyboardEvent, type ReactNode } from "react"
import type { OnChangeFn, PaginationState, SortingState } from "@tanstack/react-table"
import {
  DownloadIcon,
  ExternalLinkIcon,
  FileTextIcon,
  FolderIcon,
  FolderInputIcon,
  MoreHorizontalIcon,
  PencilIcon,
  Trash2Icon,
  XIcon,
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
import { ResponsiveList, ResponsiveListItem } from "@/components/ui/responsive-list"
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
import { FolderActions } from "@/features/files/components/folder-actions"
import { folderFileCountLabel } from "@/features/files/components/folder-copy"
import { RenameFileDialog } from "@/features/files/components/rename-file-dialog"
import { MoveFilesDialog } from "@/features/files/components/move-files-dialog"
import {
  fileSelectionReducer,
  initialFileSelectionState,
} from "@/features/files/components/file-selection"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { fileTypeLabel } from "@/features/files/format"
import type { FileListEntry } from "@/features/files/list-entries"
import { FILE_SORT_FIELDS } from "@/features/files/search"
import type {
  FileFolder,
  FileSortDirection,
  FileSortField,
  WorkspaceFile,
} from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes, formatCompactDate, formatDateTime, relativeDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

const SORT_LABELS = {
  name: "Name",
  size_bytes: "Size",
  updated_at: "Updated",
} as const satisfies Partial<Record<FileSortField, string>>

const EMPTY_FOLDERS: FileFolder[] = []

const ROW_CLASS_NAME =
  "hover:bg-muted/50 focus-visible:ring-ring cursor-pointer focus-visible:ring-2 focus-visible:outline-none"

const columnHelper = createAppColumnHelper<WorkspaceFile>()

// Select, name, and actions cells render from FileBodyCell so they can reach table-level state.
const columns = columnHelper.columns([
  columnHelper.display({
    id: "select",
    header: ({ header }) => <header.ColumnHeader />,
    cell: () => null,
    meta: { headClassName: "w-10", label: "Select", labelClassName: "sr-only" },
  }),
  columnHelper.accessor("name", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: () => null,
    enableSorting: true,
    meta: { headClassName: "w-auto max-w-0", label: SORT_LABELS.name },
    sortDescFirst: false,
  }),
  columnHelper.accessor("size_bytes", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => (
      <span className="text-muted-foreground">{formatBytes(getValue())}</span>
    ),
    enableSorting: true,
    meta: { headClassName: "w-28", label: SORT_LABELS.size_bytes },
    sortDescFirst: true,
  }),
  columnHelper.accessor("updated_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => (
      <span className="text-muted-foreground" title={formatDateTime(getValue())}>
        {formatCompactDate(getValue())}
      </span>
    ),
    enableSorting: true,
    meta: { headClassName: "w-32", label: SORT_LABELS.updated_at },
    sortDescFirst: true,
  }),
  columnHelper.display({
    id: "actions",
    header: ({ header }) => <header.ColumnHeader />,
    cell: () => null,
    meta: { headClassName: "w-14", label: "Actions", labelClassName: "sr-only" },
  }),
])

export function FilesTable({
  canEdit,
  emptyAction,
  emptyClassName,
  emptyDescription = "Drag files here or choose them from your computer. Agents can read, revise, and reuse anything you add.",
  emptyTitle = "Add your first files",
  entries,
  folders = EMPTY_FOLDERS,
  inFolder = false,
  isChangingView,
  limit,
  offset,
  onOpenFile,
  onOpenFolder,
  onPageChange,
  onSortChange,
  selectionScope,
  sortBy,
  sortDirection,
  total,
}: {
  canEdit: boolean
  emptyAction?: ReactNode
  emptyClassName?: string
  emptyDescription?: string
  emptyTitle?: string
  entries: FileListEntry[]
  folders?: FileFolder[]
  inFolder?: boolean
  isChangingView: boolean
  limit: number
  offset: number
  onOpenFile: (fileId: string) => void
  onOpenFolder?: (folderId: string) => void
  onPageChange: (offset: number) => void
  onSortChange: (sortBy: FileSortField, direction: FileSortDirection) => void
  selectionScope: string
  sortBy: FileSortField
  sortDirection: FileSortDirection
  total: number
}) {
  const deleteMutation = useDeleteFileMutation()
  const [error, setError] = useState<string | null>(null)
  const [filesToDelete, setFilesToDelete] = useState<WorkspaceFile[]>([])
  const [fileToRename, setFileToRename] = useState<WorkspaceFile | null>(null)
  const [selection, dispatchSelection] = useReducer(
    fileSelectionReducer,
    selectionScope,
    initialFileSelectionState
  )
  const files = entries.flatMap((entry) => (entry.kind === "file" ? [entry.file] : []))
  const pagination = paginationStateFromServer({ limit, offset }, total)
  const sorting = sortingStateFromServer({ sort_by: sortBy, sort_direction: sortDirection })
  const selectableFileIds = files
    .filter((file) => canEdit && file.scope === "workspace")
    .map((file) => file.id)
  const selectedFiles = files.filter(
    (file) => canEdit && file.scope === "workspace" && selection.selectedIds.has(file.id)
  )
  const selectedFileIds = selectedFiles.map((file) => file.id)
  const allSelected =
    selectableFileIds.length > 0 && selectedFileIds.length === selectableFileIds.length

  useEffect(() => {
    dispatchSelection({ scope: selectionScope, type: "scope-change" })
  }, [selectionScope])

  function setFileSelected(fileId: string, selected: boolean) {
    dispatchSelection({ fileId, selected, type: "selection-change" })
  }

  function setSelection(fileIds: string[]) {
    dispatchSelection({ fileIds, type: "selection-set" })
  }

  function openMove(fileIds: string[]) {
    dispatchSelection({ fileIds, type: "move-open" })
  }

  async function handleOpen(file: WorkspaceFile, forceDownload: boolean) {
    setError(null)
    try {
      await openWorkspaceFile({ fileId: file.id, name: file.name }, { forceDownload })
    } catch (downloadError) {
      setError(getErrorMessage(downloadError))
    }
  }

  function requestDelete(targets: WorkspaceFile[]) {
    setError(null)
    setFilesToDelete(targets)
  }

  async function confirmDelete() {
    try {
      for (const file of filesToDelete) {
        await deleteMutation.mutateAsync({ fileId: file.id })
      }
      setSelection([])
    } catch (deleteError) {
      setError(getErrorMessage(deleteError))
    }
    setFilesToDelete([])
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
      const nextParams = sortingStateToServer(nextSorting, FILE_SORT_FIELDS, {
        sort_by: sortBy,
        sort_direction: sortDirection,
      })
      onSortChange(nextParams.sort_by, nextParams.sort_direction)
    }) satisfies OnChangeFn<SortingState>,
    rowCount: total,
    state: { pagination, sorting },
  })

  if (entries.length === 0 && total === 0) {
    return (
      <EmptyState
        action={emptyAction}
        {...(emptyClassName ? { className: emptyClassName } : {})}
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
            confirmLabel={
              filesToDelete.length > 1
                ? `Delete ${String(filesToDelete.length)} Files`
                : "Delete File"
            }
            confirmPendingLabel="Deleting"
            description={deleteDescription(filesToDelete)}
            isPending={deleteMutation.isPending}
            onConfirm={confirmDelete}
            onOpenChange={(open) => {
              if (!open) {
                setFilesToDelete([])
              }
            }}
            open={canEdit && filesToDelete.length > 0}
            title={filesToDelete.length > 1 ? "Delete files?" : "Delete file?"}
          />
          <RenameFileDialog
            file={canEdit ? fileToRename : null}
            onOpenChange={(open) => {
              if (!open) {
                setFileToRename(null)
              }
            }}
          />
          <MoveFilesDialog
            fileIds={selection.moveFileIds}
            folders={folders}
            open={canEdit && selection.moveFileIds.length > 0}
            onOpenChange={(open) => {
              if (!open) dispatchSelection({ type: "move-close" })
            }}
            onMoved={() => {
              dispatchSelection({ type: "move-success" })
            }}
          />
          {selectedFileIds.length > 0 ? (
            <div className="bg-muted/40 flex items-center justify-between gap-3 rounded-lg border py-1.5 pr-2 pl-3">
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-sm font-medium">{String(selectedFileIds.length)} selected</p>
                <div className="flex items-center gap-2">
                  <Button
                    onClick={() => {
                      openMove(selectedFileIds)
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <FolderInputIcon data-icon="inline-start" />
                    Move to Folder…
                  </Button>
                  <Button
                    disabled={deleteMutation.isPending}
                    onClick={() => {
                      requestDelete(selectedFiles)
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
              <Button
                aria-label="Clear selection"
                onClick={() => {
                  setSelection([])
                }}
                size="icon-sm"
                type="button"
                variant="ghost"
              >
                <XIcon />
              </Button>
            </div>
          ) : null}
          <table.SortMenu className="md:hidden" disabled={isChangingView} />
          <ResponsiveList className={isChangingView ? "opacity-60" : undefined}>
            {entries.map((entry) =>
              entry.kind === "folder" ? (
                <FolderMobileRow
                  canEdit={canEdit}
                  folder={entry.folder}
                  key={entry.folder.id}
                  onOpenFolder={onOpenFolder}
                />
              ) : (
                <FileMobileRow
                  canEdit={canEdit}
                  file={entry.file}
                  inFolder={inFolder}
                  isDeleting={deleteMutation.isPending}
                  key={entry.file.id}
                  onDelete={requestDelete}
                  onOpen={handleOpen}
                  onOpenFile={onOpenFile}
                  onMove={openMove}
                  selected={selection.selectedIds.has(entry.file.id)}
                  onSelectedChange={(selected) => {
                    setFileSelected(entry.file.id, selected)
                  }}
                />
              )
            )}
          </ResponsiveList>

          <div className="hidden max-w-full min-w-0 overflow-hidden md:block">
            <Table className="max-w-full table-fixed">
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <table.AppHeader header={header} key={header.id}>
                        {() => (
                          <FileHeaderCell
                            allSelected={allSelected}
                            indeterminate={selectedFileIds.length > 0 && !allSelected}
                            onToggleAll={() => {
                              setSelection(allSelected ? [] : selectableFileIds)
                            }}
                            selectable={selectableFileIds.length > 0}
                          />
                        )}
                      </table.AppHeader>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody className={isChangingView ? "opacity-60" : undefined}>
                {entries.map((entry) =>
                  entry.kind === "folder" ? (
                    <FolderRow
                      canEdit={canEdit}
                      folder={entry.folder}
                      key={entry.folder.id}
                      onOpenFolder={onOpenFolder}
                    />
                  ) : (
                    <FileRow
                      canEdit={canEdit}
                      file={entry.file}
                      inFolder={inFolder}
                      isDeleting={deleteMutation.isPending}
                      key={entry.file.id}
                      onDelete={requestDelete}
                      onOpen={handleOpen}
                      onOpenFile={onOpenFile}
                      onMove={openMove}
                      onRename={setFileToRename}
                      selected={selection.selectedIds.has(entry.file.id)}
                      onSelectedChange={(selected) => {
                        setFileSelected(entry.file.id, selected)
                      }}
                    />
                  )
                )}
              </TableBody>
            </Table>
          </div>
          {total > 0 ? <table.Pagination disabled={isChangingView} total={total} /> : null}
        </div>
      </TooltipProvider>
    </table.AppTable>
  )
}

function deleteDescription(targets: WorkspaceFile[]) {
  const [first] = targets
  if (targets.length === 1 && first) {
    return `This deletes ${first.name}.`
  }
  return `This deletes ${String(targets.length)} files.`
}

function handleRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, open: () => void) {
  if (event.target !== event.currentTarget) {
    return
  }
  if (event.key !== "Enter" && event.key !== " ") {
    return
  }

  event.preventDefault()
  open()
}

function stopRowClick(event: { stopPropagation: () => void }) {
  event.stopPropagation()
}

function FileHeaderCell({
  allSelected,
  indeterminate,
  onToggleAll,
  selectable,
}: {
  allSelected: boolean
  indeterminate: boolean
  onToggleAll: () => void
  selectable: boolean
}) {
  const header = useHeaderContext()
  if (header.isPlaceholder) {
    return <TableHead />
  }
  if (header.column.id === "select") {
    return (
      <TableHead className="w-10">
        {selectable ? (
          <Checkbox
            aria-label="Select all files on this page"
            checked={allSelected}
            indeterminate={indeterminate}
            onCheckedChange={onToggleAll}
          />
        ) : null}
      </TableHead>
    )
  }
  return <header.ColumnHeader />
}

type FileActionProps = {
  canEdit: boolean
  isDeleting: boolean
  onDelete: (files: WorkspaceFile[]) => void
  onOpen: (file: WorkspaceFile, forceDownload: boolean) => Promise<void>
  onMove: (fileIds: string[]) => void
}

function FileBodyCell({
  canEdit,
  inFolder,
  isDeleting,
  onDelete,
  onOpen,
  onRename,
  onMove,
  selected,
  onSelectedChange,
}: FileActionProps & {
  inFolder: boolean
  onRename: (file: WorkspaceFile) => void
  selected: boolean
  onSelectedChange: (selected: boolean) => void
}) {
  const cell = useCellContext()
  const row = useTableContext<WorkspaceFile>().getRow(cell.row.id)
  const file = row.original

  switch (cell.column.id) {
    case "select":
      return (
        <TableCell className="w-10" onClick={stopRowClick}>
          {canEdit && file.scope === "workspace" ? (
            <Checkbox
              aria-label={`Select ${file.name}`}
              checked={selected}
              onCheckedChange={onSelectedChange}
            />
          ) : null}
        </TableCell>
      )
    case "name":
      return (
        <TableCell className="w-auto max-w-0">
          <FileNameCell file={file} showFolder={!inFolder} />
        </TableCell>
      )
    case "actions":
      return (
        <TableCell className="w-14 text-right" onClick={stopRowClick}>
          <FileActions
            canEdit={canEdit}
            file={file}
            isDeleting={isDeleting}
            onDelete={onDelete}
            onOpen={onOpen}
            onRename={onRename}
            onMove={onMove}
          />
        </TableCell>
      )
    default:
      return (
        <TableCell className={cell.column.id === "updated_at" ? "w-32" : "w-28"}>
          <cell.FlexRender />
        </TableCell>
      )
  }
}

function resolveUpdater<T>(updater: T | ((previous: T) => T), previous: T): T {
  return typeof updater === "function" ? (updater as (value: T) => T)(previous) : updater
}

function FileNameCell({
  file,
  showFolder,
  size = "md",
}: {
  file: WorkspaceFile
  showFolder: boolean
  size?: "sm" | "md"
}) {
  const details = [
    fileTypeLabel(file),
    showFolder && file.folder_name ? `In ${file.folder_name}` : null,
    file.description,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <div className="flex max-w-full min-w-0 items-center gap-3">
      <FileThumbnail file={file} size={size} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <FileNameTooltip name={file.name} />
          {file.scope === "platform" ? <Badge variant="secondary">Shared</Badge> : null}
          {file.processing_status === "ready" ? null : (
            <FileStatusBadge status={file.processing_status} />
          )}
        </div>
        <p className="text-muted-foreground truncate text-xs">{details}</p>
      </div>
    </div>
  )
}

function FolderNameCell({ folder, size = "md" }: { folder: FileFolder; size?: "sm" | "md" }) {
  const details = [folderFileCountLabel(folder), folder.description].filter(Boolean).join(" · ")

  return (
    <span className="flex max-w-full min-w-0 items-center gap-3">
      <span
        className={cn(
          "bg-accent text-primary flex shrink-0 items-center justify-center rounded-md border",
          size === "sm" ? "size-9" : "size-10"
        )}
      >
        <FolderIcon className="size-5" />
      </span>
      <span className="block min-w-0 flex-1">
        <span className="block truncate font-medium">{folder.name}</span>
        <span className="text-muted-foreground block truncate text-xs">{details}</span>
      </span>
    </span>
  )
}

function FileRow({
  canEdit,
  file,
  inFolder,
  isDeleting,
  onDelete,
  onOpen,
  onOpenFile,
  onMove,
  onRename,
  selected,
  onSelectedChange,
}: FileActionProps & {
  file: WorkspaceFile
  inFolder: boolean
  onOpenFile: (fileId: string) => void
  onRename: (file: WorkspaceFile) => void
  selected: boolean
  onSelectedChange: (selected: boolean) => void
}) {
  const table = useTableContext<WorkspaceFile>()
  const row = table.getRow(file.id)

  return (
    <TableRow
      aria-label={`Open Details for ${file.name}`}
      className={ROW_CLASS_NAME}
      onClick={() => {
        onOpenFile(file.id)
      }}
      onKeyDown={(event) => {
        handleRowKeyDown(event, () => {
          onOpenFile(file.id)
        })
      }}
      tabIndex={0}
    >
      {row.getVisibleCells().map((cell) => (
        <table.AppCell cell={cell} key={cell.id}>
          {() => (
            <FileBodyCell
              canEdit={canEdit}
              inFolder={inFolder}
              isDeleting={isDeleting}
              onDelete={onDelete}
              onOpen={onOpen}
              onRename={onRename}
              onMove={onMove}
              selected={selected}
              onSelectedChange={onSelectedChange}
            />
          )}
        </table.AppCell>
      ))}
    </TableRow>
  )
}

function FolderRow({
  canEdit,
  folder,
  onOpenFolder,
}: {
  canEdit: boolean
  folder: FileFolder
  onOpenFolder: ((folderId: string) => void) | undefined
}) {
  function open() {
    onOpenFolder?.(folder.id)
  }

  return (
    <TableRow
      aria-label={`Open folder ${folder.name}`}
      className={ROW_CLASS_NAME}
      onClick={open}
      onKeyDown={(event) => {
        handleRowKeyDown(event, open)
      }}
      tabIndex={0}
    >
      <TableCell className="w-10" />
      <TableCell className="w-auto max-w-0">
        <FolderNameCell folder={folder} />
      </TableCell>
      <TableCell className="text-muted-foreground w-28">
        {formatBytes(folder.total_bytes)}
      </TableCell>
      <TableCell className="text-muted-foreground w-32" title={formatDateTime(folder.updated_at)}>
        {formatCompactDate(folder.updated_at)}
      </TableCell>
      <TableCell className="w-14 text-right" onClick={stopRowClick}>
        {canEdit ? <FolderActions folder={folder} /> : null}
      </TableCell>
    </TableRow>
  )
}

function FolderMobileRow({
  canEdit,
  folder,
  onOpenFolder,
}: {
  canEdit: boolean
  folder: FileFolder
  onOpenFolder: ((folderId: string) => void) | undefined
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 items-center gap-3">
        <button
          aria-label={`Open folder ${folder.name}`}
          className="focus-visible:ring-ring flex min-w-0 flex-1 items-center rounded-md text-left outline-none hover:cursor-pointer focus-visible:ring-2"
          onClick={() => {
            onOpenFolder?.(folder.id)
          }}
          type="button"
        >
          <FolderNameCell folder={folder} size="sm" />
        </button>
        {canEdit ? <FolderActions folder={folder} /> : null}
      </div>
    </ResponsiveListItem>
  )
}

function FileMobileRow({
  canEdit,
  file,
  inFolder,
  isDeleting,
  onDelete,
  onOpen,
  onOpenFile,
  onMove,
  selected,
  onSelectedChange,
}: FileActionProps & {
  file: WorkspaceFile
  inFolder: boolean
  onOpenFile: (fileId: string) => void
  selected: boolean
  onSelectedChange: (selected: boolean) => void
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-center gap-3">
          {canEdit && file.scope === "workspace" ? (
            <Checkbox
              aria-label={`Select ${file.name}`}
              checked={selected}
              onCheckedChange={onSelectedChange}
            />
          ) : null}
          <div className="min-w-0 flex-1">
            <FileNameCell file={file} showFolder={!inFolder} size="sm" />
          </div>
        </div>

        <p className="text-muted-foreground text-xs">
          {formatBytes(file.size_bytes)} · Updated {relativeDateTime(file.updated_at)}
        </p>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {canEdit && file.scope === "workspace" ? (
            <Button
              onClick={() => {
                onMove([file.id])
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              <FolderInputIcon data-icon="inline-start" />
              Move
            </Button>
          ) : null}
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
          {file.scope === "workspace" || file.is_published ? (
            <>
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
            </>
          ) : null}
          {canEdit && file.scope === "workspace" ? (
            <Button
              disabled={isDeleting}
              onClick={() => {
                onDelete([file])
              }}
              size="sm"
              type="button"
              variant="destructive"
            >
              <Trash2Icon data-icon="inline-start" />
              Delete
            </Button>
          ) : null}
        </div>
      </div>
    </ResponsiveListItem>
  )
}

function FileNameTooltip({ name }: { name: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        className="block max-w-full min-w-0 truncate text-left font-medium"
        render={<span />}
      >
        {name}
      </TooltipTrigger>
      <TooltipContent className="max-w-sm wrap-break-word">{name}</TooltipContent>
    </Tooltip>
  )
}

function FileActions({
  canEdit,
  file,
  isDeleting,
  onDelete,
  onOpen,
  onRename,
  onMove,
}: FileActionProps & {
  file: WorkspaceFile
  onRename: (file: WorkspaceFile) => void
}) {
  if (file.scope === "platform" && !file.is_published) return null
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
        {canEdit && file.scope === "workspace" ? (
          <>
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
                onMove([file.id])
              }}
            >
              <FolderInputIcon data-icon="inline-start" />
              Move to Folder…
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              disabled={isDeleting}
              onClick={() => {
                onDelete([file])
              }}
              variant="destructive"
            >
              <Trash2Icon data-icon="inline-start" />
              Delete
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
