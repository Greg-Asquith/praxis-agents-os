// apps/web/src/features/files/api/get-file.ts

import { queryOptions } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"

async function getFile(fileId: string) {
  return apiRequest<WorkspaceFile>(`/files/${fileId}`)
}

export function fileQueryOptions(fileId: string) {
  return queryOptions({
    queryKey: filesQueryKeys.detail(fileId),
    queryFn: () => getFile(fileId),
    staleTime: 30_000,
  })
}
