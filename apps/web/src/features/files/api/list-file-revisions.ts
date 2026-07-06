// apps/web/src/features/files/api/list-file-revisions.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { FileRevisionsListResponse } from "../types"
import { apiRequest } from "@/lib/api/client"

async function listFileRevisions(fileId: string) {
  return apiRequest<FileRevisionsListResponse>(`/files/${fileId}/revisions`)
}

function fileRevisionsQueryOptions(fileId: string) {
  return queryOptions({
    queryKey: filesQueryKeys.revisions(fileId),
    queryFn: () => listFileRevisions(fileId),
    staleTime: 30_000,
  })
}

export function useFileRevisionsQuery(fileId: string) {
  return useSuspenseQuery(fileRevisionsQueryOptions(fileId))
}
