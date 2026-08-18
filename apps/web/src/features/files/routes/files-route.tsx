// apps/web/src/features/files/routes/files-route.tsx

import { useTransition } from "react"
import { Navigate, useNavigate, useRouterState } from "@tanstack/react-router"
import { useSuspenseQueries } from "@tanstack/react-query"
import { PageHeader } from "@/components/shell/page-header"
import { filesQueryOptions } from "@/features/files/api/list-files"
import { foldersQueryOptions } from "@/features/files/api/list-folders"
import { FileDetailModal } from "@/features/files/components/file-detail-modal"
import { FileUploadButton } from "@/features/files/components/file-upload-button"
import { FilesTable } from "@/features/files/components/files-table"
import { FoldersGrid, NewFolderButton } from "@/features/files/components/folders-grid"
import { FolderHeader } from "@/features/files/components/folder-header"
import type { FilesSearch } from "@/features/files/search"
import type { FileSortDirection, FileSortField } from "@/features/files/types"

const PAGE_SIZE = 25

export function FilesRoute() {
  const search = useRouterState({
    select: (state): FilesSearch => state.location.search,
  })
  const navigate = useNavigate()
  const [isChangingView, startViewTransition] = useTransition()
  const page = search.page ?? 1
  const sortBy = search.sort ?? "updated_at"
  const sortDirection = search.direction ?? "desc"
  const [{ data }, { data: folderData }] = useSuspenseQueries({
    queries: [
      filesQueryOptions({
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        sortBy,
        sortDirection,
        ...(search.folder ? { folderId: search.folder } : { rootOnly: true }),
      }),
      foldersQueryOptions(),
    ],
  })
  const currentFolder = search.folder
    ? (folderData.folders.find((folder) => folder.id === search.folder) ?? null)
    : null
  const selectedFile = search.fileId
    ? (data.files.find((file) => file.id === search.fileId) ?? null)
    : null

  if (search.folder && !currentFolder) {
    return <Navigate replace search={{}} to="/files" />
  }

  function setOpenFile(fileId: string | null) {
    void navigate({
      to: "/files",
      search: {
        ...(search.direction ? { direction: search.direction } : {}),
        ...(search.folder ? { folder: search.folder } : {}),
        ...(fileId ? { fileId } : {}),
        ...(search.page ? { page: search.page } : {}),
        ...(search.sort ? { sort: search.sort } : {}),
      },
    })
  }

  function updateSort(nextSort: FileSortField, nextDirection: FileSortDirection) {
    startViewTransition(() => {
      void navigate({
        to: "/files",
        search: {
          ...(nextDirection === "asc" ? { direction: nextDirection } : {}),
          ...(search.fileId ? { fileId: search.fileId } : {}),
          ...(search.folder ? { folder: search.folder } : {}),
          ...(nextSort === "updated_at" ? {} : { sort: nextSort }),
        },
      })
    })
  }

  function updatePage(nextOffset: number) {
    startViewTransition(() => {
      void navigate({
        to: "/files",
        search: {
          ...(search.direction ? { direction: search.direction } : {}),
          ...(search.fileId ? { fileId: search.fileId } : {}),
          ...(search.folder ? { folder: search.folder } : {}),
          ...(nextOffset === 0 ? {} : { page: Math.floor(nextOffset / PAGE_SIZE) + 1 }),
          ...(search.sort ? { sort: search.sort } : {}),
        },
      })
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          <div className="flex items-center gap-2">
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
            <FileUploadButton folderId={currentFolder?.id ?? null} />
          </div>
        }
        description={
          currentFolder?.description ??
          (currentFolder
            ? "Files grouped in this folder."
            : "Upload, inspect, and restore durable files shared with agents.")
        }
        title={currentFolder?.name ?? "Files"}
      />

      {!currentFolder ? (
        <FoldersGrid
          folders={folderData.folders}
          onOpenFolder={(folder) => {
            void navigate({ to: "/files", search: { folder } })
          }}
        />
      ) : null}

      <FilesTable
        files={data.files}
        emptyAction={<FileUploadButton folderId={currentFolder?.id ?? null} />}
        {...(currentFolder
          ? {
              emptyDescription: "Nothing here yet — upload files or move them in.",
              emptyTitle: "This folder is empty",
            }
          : {})}
        isChangingView={isChangingView}
        folders={folderData.folders}
        limit={PAGE_SIZE}
        offset={(page - 1) * PAGE_SIZE}
        onPageChange={updatePage}
        onOpenFile={(fileId) => {
          setOpenFile(fileId)
        }}
        onSortChange={updateSort}
        selectionScope={[search.folder ?? "root", String(page), sortBy, sortDirection].join(":")}
        sortBy={sortBy}
        sortDirection={sortDirection}
        total={data.total}
      />

      <FileDetailModal
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
}
