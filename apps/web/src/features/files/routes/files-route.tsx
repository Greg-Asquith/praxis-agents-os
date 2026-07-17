// apps/web/src/features/files/routes/files-route.tsx

import { useTransition } from "react"
import { useNavigate, useRouterState } from "@tanstack/react-router"
import { PageHeader } from "@/components/shell/page-header"
import { useFilesQuery } from "@/features/files/api/list-files"
import { FileDetailModal } from "@/features/files/components/file-detail-modal"
import { FileUploadButton } from "@/features/files/components/file-upload-button"
import { FilesTable } from "@/features/files/components/files-table"
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
  const { data } = useFilesQuery({
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    sortBy,
    sortDirection,
  })
  const hasFiles = data.total > 0
  const selectedFile = search.fileId
    ? (data.files.find((file) => file.id === search.fileId) ?? null)
    : null

  function setOpenFile(fileId: string | null) {
    void navigate({
      to: "/files",
      search: {
        ...(search.direction ? { direction: search.direction } : {}),
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
          ...(nextOffset === 0 ? {} : { page: Math.floor(nextOffset / PAGE_SIZE) + 1 }),
          ...(search.sort ? { sort: search.sort } : {}),
        },
      })
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={hasFiles ? <FileUploadButton /> : null}
        description="Upload, inspect, and restore durable files shared with agents."
        title="Files"
      />

      <FilesTable
        files={data.files}
        emptyAction={<FileUploadButton />}
        isChangingView={isChangingView}
        limit={PAGE_SIZE}
        offset={(page - 1) * PAGE_SIZE}
        onPageChange={updatePage}
        onOpenFile={(fileId) => {
          setOpenFile(fileId)
        }}
        onSortChange={updateSort}
        sortBy={sortBy}
        sortDirection={sortDirection}
        total={data.total}
      />

      <FileDetailModal
        fileId={search.fileId ?? null}
        initialFile={selectedFile}
        onClose={() => {
          setOpenFile(null)
        }}
      />
    </div>
  )
}
