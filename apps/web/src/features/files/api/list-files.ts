// apps/web/src/features/files/api/list-files.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { FileContractCategory, FileListResponse, FileProcessingStatus } from "../types"
import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"
import { apiRequest } from "@/lib/api/client"

export type ListFilesParams = {
  category?: FileContractCategory
  limit?: number
  offset?: number
  search?: string
}

export const filesQueryKeys = {
  all: ["files"] as const,
  workspace: () => [...filesQueryKeys.all, activeWorkspaceQueryScope()] as const,
  details: () => [...filesQueryKeys.workspace(), "detail"] as const,
  detail: (fileId: string) => [...filesQueryKeys.details(), fileId] as const,
  lists: () => [...filesQueryKeys.workspace(), "list"] as const,
  list: (params: ListFilesParams = {}) => [...filesQueryKeys.lists(), params] as const,
  revisionContents: (fileId: string) =>
    [...filesQueryKeys.detail(fileId), "revision-content"] as const,
  revisionContent: (fileId: string, revisionId: string) =>
    [...filesQueryKeys.revisionContents(fileId), revisionId] as const,
  revisions: (fileId: string) => [...filesQueryKeys.detail(fileId), "revisions"] as const,
}

function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
}

async function listFiles({ category, limit = 100, offset = 0, search }: ListFilesParams = {}) {
  return apiRequest<FileListResponse>("/files/", {
    query: {
      category,
      limit,
      offset,
      search,
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
