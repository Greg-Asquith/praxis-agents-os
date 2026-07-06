// apps/web/src/features/files/api/get-revision-content.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { FileRevisionContent } from "../types"
import { apiRequest } from "@/lib/api/client"

async function getRevisionContent(fileId: string, revisionId: string) {
  return apiRequest<FileRevisionContent>(`/files/${fileId}/revisions/${revisionId}/content`)
}

function revisionContentQueryOptions(fileId: string, revisionId: string) {
  return queryOptions({
    queryKey: filesQueryKeys.revisionContent(fileId, revisionId),
    queryFn: () => getRevisionContent(fileId, revisionId),
    staleTime: Infinity,
  })
}

export function useRevisionContentQuery(fileId: string, revisionId: string) {
  return useSuspenseQuery(revisionContentQueryOptions(fileId, revisionId))
}
