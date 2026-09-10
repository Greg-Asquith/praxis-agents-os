// apps/web/src/features/files/api/list-files.ts

import { queryOptions } from "@tanstack/react-query"

import type {
  FileContractCategory,
  FileListResponse,
  FileScopeFilter,
  FileSortDirection,
  FileSortField,
} from "../types"
import { isFileProcessing } from "../processing"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"
import { apiRequest } from "@/lib/api/client"

export type ListFilesParams = {
  category?: FileContractCategory
  limit?: number
  offset?: number
  scope?: FileScopeFilter
  search?: string
  sortBy?: FileSortField
  sortDirection?: FileSortDirection
  folderId?: string
  rootOnly?: boolean
}

const baseFilesQueryKeys = createWorkspaceScopedQueryKeys("files")

export const filesQueryKeys = {
  ...baseFilesQueryKeys,
  folders: () => [...filesQueryKeys.workspace(), "folders"] as const,
  preview: (fileId: string) => [...filesQueryKeys.detail(fileId), "preview"] as const,
  revisionContents: (fileId: string) =>
    [...filesQueryKeys.detail(fileId), "revision-content"] as const,
  revisionContent: (fileId: string, revisionId: string) =>
    [...filesQueryKeys.revisionContents(fileId), revisionId] as const,
  revisions: (fileId: string) => [...filesQueryKeys.detail(fileId), "revisions"] as const,
}

async function listFiles({
  category,
  limit = 50,
  offset = 0,
  scope,
  search,
  sortBy = "updated_at",
  sortDirection = "desc",
  folderId,
  rootOnly,
}: ListFilesParams = {}) {
  return apiRequest<FileListResponse>("/files/", {
    query: {
      category,
      limit,
      offset,
      scope,
      search,
      sort_by: sortBy,
      sort_direction: sortDirection,
      folder_id: folderId,
      root_only: rootOnly,
    },
  })
}

export function filesQueryOptions(params: ListFilesParams = {}) {
  return queryOptions({
    queryKey: filesQueryKeys.list(params),
    queryFn: () => listFiles(params),
    staleTime: 30_000,
    refetchInterval: (query) => {
      const data = query.state.data
      return data?.files.some((file) => isFileProcessing(file.processing_status)) ? 4_000 : false
    },
  })
}
