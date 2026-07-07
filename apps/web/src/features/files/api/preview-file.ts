// apps/web/src/features/files/api/preview-file.ts

import { queryOptions } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { FilePreviewGrant } from "../types"
import { apiRequest } from "@/lib/api/client"

async function createFilePreview(fileId: string) {
  return apiRequest<FilePreviewGrant>(`/files/${fileId}/preview`, {
    method: "POST",
  })
}

export function filePreviewQueryOptions(fileId: string) {
  return queryOptions({
    queryKey: filesQueryKeys.preview(fileId),
    queryFn: () => createFilePreview(fileId),
    staleTime: 4 * 60 * 1000,
  })
}
