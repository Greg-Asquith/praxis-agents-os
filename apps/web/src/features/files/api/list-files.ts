// apps/web/src/features/files/api/list-files.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type {
  FileContractCategory,
  FileListResponse,
  FileProcessingStatus,
  FileSortDirection,
  FileSortField,
} from "../types"
import { createWorkspaceScopedQueryKeys } from "@/features/workspaces/query-keys"
import { apiRequest } from "@/lib/api/client"

export type ListFilesParams = {
  category?: FileContractCategory
  limit?: number
  offset?: number
  search?: string
  sortBy?: FileSortField
  sortDirection?: FileSortDirection
}

const baseFilesQueryKeys = createWorkspaceScopedQueryKeys("files")

export const filesQueryKeys = {
  ...baseFilesQueryKeys,
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
  search,
  sortBy = "updated_at",
  sortDirection = "desc",
}: ListFilesParams = {}) {
  return apiRequest<FileListResponse>("/files/", {
    query: {
      category,
      limit,
      offset,
      search,
      sort_by: sortBy,
      sort_direction: sortDirection,
    },
  })
}

function filesQueryOptions(params: ListFilesParams = {}) {
  return queryOptions({
    queryKey: filesQueryKeys.list(params),
    queryFn: () => listFiles(params),
    staleTime: 30_000,
    refetchInterval: (query) => {
      const data = query.state.data
      return data?.files.some((file) => isInFlightStatus(file.processing_status)) ? 4_000 : false
    },
  })
}

export function useFilesQuery(params: ListFilesParams = {}) {
  return useSuspenseQuery(filesQueryOptions(params))
}

function isInFlightStatus(status: FileProcessingStatus) {
  return status === "pending" || status === "processing"
}
