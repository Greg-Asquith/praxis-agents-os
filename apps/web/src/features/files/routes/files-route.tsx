// apps/web/src/features/files/routes/files-route.tsx

import { useEffect, useState, useTransition } from "react"
import { Link, Navigate, useNavigate, useRouterState } from "@tanstack/react-router"
import { useSuspenseQueries } from "@tanstack/react-query"
import { ArrowLeftIcon, SearchIcon } from "lucide-react"

import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { platformFilesQueryOptions } from "@/features/files/api/platform-list-files"
import { PageHeader } from "@/components/shell/page-header"
import { filesQueryOptions } from "@/features/files/api/list-files"
import { foldersQueryOptions } from "@/features/files/api/list-folders"
import { FileDetailModal } from "@/features/files/components/file-detail-modal"
import { FileDropZone } from "@/features/files/components/file-drop-zone"
import { FileUploadButton } from "@/features/files/components/file-upload-button"
import { FilesTable } from "@/features/files/components/files-table"
import { FolderHeader } from "@/features/files/components/folder-header"
import { NewFolderButton } from "@/features/files/components/new-folder-button"
import { fileWindow, mergeListEntries } from "@/features/files/list-entries"
import type { FilesSearch } from "@/features/files/search"
import type {
  FileFolder,
  FileScopeFilter,
  FileSortDirection,
  FileSortField,
} from "@/features/files/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { canEditWorkspace } from "@/features/workspaces/permissions"

const PAGE_SIZE = 10
const MAX_FILE_LIMIT = 100
const SEARCH_DEBOUNCE_MS = 300
const NO_FOLDERS: FileFolder[] = []

type SearchPatch = { [Key in keyof FilesSearch]?: FilesSearch[Key] | undefined }

// Drops default values so the URL only carries state that differs from a fresh visit.
function normaliseSearch(next: SearchPatch): FilesSearch {
  return {
    ...(next.direction === "asc" ? { direction: next.direction } : {}),
    ...(next.fileId ? { fileId: next.fileId } : {}),
    ...(next.folder ? { folder: next.folder } : {}),
    ...(next.page && next.page > 1 ? { page: next.page } : {}),
    ...(next.q ? { q: next.q } : {}),
    ...(next.scope && next.scope !== "all" ? { scope: next.scope } : {}),
    ...(next.sort && next.sort !== "updated_at" ? { sort: next.sort } : {}),
  }
}

export function FilesRoute() {
  const search = useRouterState({
    select: (state): FilesSearch => state.location.search,
  })
  const navigate = useNavigate()
  const [isChangingView, startViewTransition] = useTransition()
  const { workspace } = useActiveWorkspace()
  const scope: FileScopeFilter = search.folder ? "workspace" : (search.scope ?? "all")
  const page = search.page ?? 1
  const sortBy = search.sort ?? "updated_at"
  const sortDirection = search.direction ?? "desc"
  const query = search.q ?? ""
  const [{ data: user }, { data: folderData }] = useSuspenseQueries({
    queries: [currentUserQueryOptions(), foldersQueryOptions()],
  })
  const platformManagement = scope === "platform" && user.is_super_admin
  const currentFolder = search.folder
    ? (folderData.folders.find((folder) => folder.id === search.folder) ?? null)
    : null
  const canUpload = scope !== "platform" && canEditWorkspace(workspace.current_user_role)
  const showFolders = !currentFolder && scope !== "platform" && !query
  const folders = showFolders ? folderData.folders : NO_FOLDERS
  const offset = (page - 1) * PAGE_SIZE
  const { fileLimit, fileOffset } = fileWindow(folders.length, offset, PAGE_SIZE)
  const filePages = useSuspenseQueries({
    queries: Array.from({ length: Math.ceil(fileLimit / MAX_FILE_LIMIT) }, (_, index) => {
      const params = {
        limit: Math.min(MAX_FILE_LIMIT, fileLimit - index * MAX_FILE_LIMIT),
        offset: fileOffset + index * MAX_FILE_LIMIT,
        sortBy,
        sortDirection,
        ...(query ? { search: query } : {}),
      }
      return platformManagement
        ? platformFilesQueryOptions(params)
        : filesQueryOptions({
            ...params,
            scope,
            ...(search.folder ? { folderId: search.folder } : query ? {} : { rootOnly: true }),
          })
    }),
  })
  const data = {
    files: filePages.flatMap((result) => result.data.files),
    total: filePages[0]?.data.total ?? 0,
  }
  const selectedFile = search.fileId
    ? (data.files.find((file) => file.id === search.fileId) ?? null)
    : null
  const entries = mergeListEntries({
    fileOffset,
    files: data.files,
    folders,
    limit: PAGE_SIZE,
    offset,
    sortBy,
    sortDirection,
  })

  if (search.folder && !currentFolder) {
    return <Navigate replace search={{}} to="/files" />
  }

  function navigateTo(next: SearchPatch, { transition = false } = {}) {
    const run = () => {
      void navigate({ to: "/files", search: normaliseSearch(next) })
    }
    if (transition) startViewTransition(run)
    else run()
  }

  function setOpenFile(fileId: string | null) {
    navigateTo({ ...search, fileId: fileId ?? undefined })
  }

  function updateSort(nextSort: FileSortField, nextDirection: FileSortDirection) {
    navigateTo(
      { ...search, direction: nextDirection, page: undefined, sort: nextSort },
      { transition: true }
    )
  }

  function updatePage(nextOffset: number) {
    navigateTo({ ...search, page: Math.floor(nextOffset / PAGE_SIZE) + 1 }, { transition: true })
  }

  function updateScope(value: unknown) {
    if (value !== "all" && value !== "workspace" && value !== "platform") return
    navigateTo(
      { direction: search.direction, q: search.q, scope: value, sort: search.sort },
      { transition: true }
    )
  }

  function updateQuery(nextQuery: string) {
    navigateTo(
      { ...search, fileId: undefined, page: undefined, q: nextQuery },
      { transition: true }
    )
  }

  const uploadButton = <FileUploadButton folderId={currentFolder?.id ?? null} />
  const emptyState = query
    ? {
        emptyDescription: "Try a different word, or clear the search to see everything.",
        emptyTitle: "No matching files",
      }
    : currentFolder
      ? {
          ...(canUpload ? { emptyAction: uploadButton } : {}),
          emptyClassName: "border-input border border-dashed",
          emptyDescription: canUpload
            ? "Drop files here or move them into this folder."
            : "Files added to this folder appear here.",
          emptyTitle: "This folder is empty",
        }
      : scope === "platform"
        ? {
            emptyDescription: "Files shared with every workspace appear here.",
            emptyTitle: "No shared files",
          }
        : {
            ...(!canUpload
              ? {
                  emptyTitle: "No files",
                  emptyDescription: "Files added to this workspace appear here.",
                }
              : {}),
            emptyAction: canUpload ? (
              <div className="flex flex-wrap justify-center gap-2">
                {uploadButton}
                <NewFolderButton />
              </div>
            ) : undefined,
            emptyClassName: "border-input border border-dashed",
          }

  const list = (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <FilesSearchInput disabled={isChangingView} onChange={updateQuery} value={query} />
          {currentFolder ? null : (
            <Tabs onValueChange={updateScope} value={scope}>
              <TabsList aria-label="Which files to show">
                <TabsTrigger value="all">All</TabsTrigger>
                <TabsTrigger className="max-w-48" value="workspace">
                  <span className="truncate">{workspace.name}</span>
                </TabsTrigger>
                <TabsTrigger value="platform">Shared</TabsTrigger>
              </TabsList>
            </Tabs>
          )}
        </div>
        {canUpload ? (
          <p className="text-muted-foreground text-xs">
            Drop files anywhere on this page to upload them
          </p>
        ) : null}
      </div>
      {scope === "platform" ? (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="text-muted-foreground max-w-xl text-sm">
            {platformManagement
              ? "Files you upload here become available in every workspace after processing."
              : "Shared files are available in every workspace."}
          </p>
          {platformManagement ? <FileUploadButton scope="platform" /> : null}
        </div>
      ) : null}
      <FilesTable
        canEdit={canEditWorkspace(workspace.current_user_role)}
        entries={entries}
        folders={folderData.folders}
        inFolder={currentFolder !== null}
        isChangingView={isChangingView}
        limit={PAGE_SIZE}
        offset={offset}
        onOpenFile={setOpenFile}
        onOpenFolder={(folder) => {
          void navigate({ to: "/files", search: { folder } })
        }}
        onPageChange={updatePage}
        onSortChange={updateSort}
        selectionScope={[
          scope,
          search.folder ?? "root",
          query,
          String(page),
          sortBy,
          sortDirection,
        ].join(":")}
        sortBy={sortBy}
        sortDirection={sortDirection}
        total={folders.length + data.total}
        {...emptyState}
      />
    </>
  )

  const content = (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        {currentFolder ? (
          <Link
            className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-sm transition-colors"
            search={{}}
            to="/files"
          >
            <ArrowLeftIcon className="size-3.5" />
            All files
          </Link>
        ) : null}
        <PageHeader
          actions={
            canUpload ? (
              <div className="flex flex-wrap items-start gap-2 md:justify-end">
                {currentFolder ? (
                  <FolderHeader
                    folder={currentFolder}
                    onDeleted={() => {
                      void navigate({ to: "/files", search: {} })
                    }}
                  />
                ) : (
                  <NewFolderButton />
                )}
                {uploadButton}
              </div>
            ) : undefined
          }
          description={
            currentFolder?.description ??
            (currentFolder
              ? "Files grouped in this folder."
              : "Documents and templates your agents can read, revise, and reuse.")
          }
          title={currentFolder?.name ?? "Files"}
        />
      </div>

      {list}

      <FileDetailModal
        platformManagement={platformManagement}
        fileId={search.fileId ?? null}
        initialFile={selectedFile}
        open={Boolean(search.fileId)}
        folders={folderData.folders}
        onOpenChange={(open) => {
          if (!open) {
            setOpenFile(null)
          }
        }}
      />
    </div>
  )

  return canUpload ? (
    <FileDropZone folderId={currentFolder?.id ?? null}>{content}</FileDropZone>
  ) : (
    content
  )
}

function FilesSearchInput({
  disabled,
  onChange,
  value,
}: {
  disabled: boolean
  onChange: (value: string) => void
  value: string
}) {
  const [draft, setDraft] = useState(value)
  const [syncedValue, setSyncedValue] = useState(value)
  if (value !== syncedValue) {
    setSyncedValue(value)
    setDraft(value)
  }

  useEffect(() => {
    const trimmed = draft.trim()
    if (trimmed === value) return
    const timer = window.setTimeout(() => {
      onChange(trimmed)
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
    }
  }, [draft, onChange, value])

  return (
    <div className="relative w-full sm:w-72">
      <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
      <Input
        aria-label="Search files"
        className="pl-8"
        disabled={disabled}
        onChange={(event) => {
          setDraft(event.target.value)
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            onChange(draft.trim())
          } else if (event.key === "Escape" && draft) {
            setDraft("")
            onChange("")
          }
        }}
        placeholder="Search files"
        type="search"
        value={draft}
      />
    </div>
  )
}
