// apps/web/src/features/files/api/platform-get-file.ts

import { queryOptions } from "@tanstack/react-query"
import { platformFilesQueryKeys } from "./platform-list-files"
import type { WorkspaceFile } from "../types"
import { isFileProcessing } from "../processing"
import { apiRequest } from "@/lib/api/client"

export function platformFileQueryOptions(fileId: string) {
  return queryOptions({
    queryKey: platformFilesQueryKeys.detail(fileId),
    queryFn: () => apiRequest<WorkspaceFile>(`/files/platform/${fileId}`),
    staleTime: 0,
    refetchInterval: (query) =>
      isFileProcessing(query.state.data?.processing_status) ? 4_000 : false,
  })
}
