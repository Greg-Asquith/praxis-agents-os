// apps/web/src/features/files/api/platform-list-files.ts

import { queryOptions } from "@tanstack/react-query"
import type { FileListResponse, FileSortField, FileSortDirection } from "../types"
import { isFileProcessing } from "../processing"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

export const platformFilesQueryKeys = createWorkspaceScopedQueryKeys("platform-files")

export function platformFilesQueryOptions({
  offset = 0,
  limit = 25,
  search,
  sortBy = "updated_at",
  sortDirection = "desc",
}: {
  offset?: number
  limit?: number
  search?: string
  sortBy?: FileSortField
  sortDirection?: FileSortDirection
} = {}) {
  return queryOptions({
    queryKey: platformFilesQueryKeys.list({ offset, limit, search, sortBy, sortDirection }),
    queryFn: () =>
      apiRequest<FileListResponse>("/files/platform/", {
        query: { offset, limit, search, sort_by: sortBy, sort_direction: sortDirection },
      }),
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.data?.files.some((file) => isFileProcessing(file.processing_status))
        ? 4_000
        : false,
  })
}
