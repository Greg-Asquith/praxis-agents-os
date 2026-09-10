// apps/web/src/features/files/api/platform-file-preview.ts

import { queryOptions } from "@tanstack/react-query"
import { platformFilesQueryKeys } from "./platform-list-files"
import type { FileRevisionContent, WorkspaceFile } from "../types"
import { apiFetch, apiRequest } from "@/lib/api/client"
import { parseApiError } from "@/lib/api/errors"

export function platformFilePreviewQueryOptions(file: WorkspaceFile) {
  return queryOptions({
    queryKey: [
      ...platformFilesQueryKeys.detail(file.id),
      "preview",
      file.current_revision_id,
      file.category,
      file.content_type,
    ],
    queryFn: async ({ signal }) => {
      if (file.category === "audio") {
        return { blob: null, content: null, mediaType: null }
      }
      const query = { revision_id: file.current_revision_id }
      if (file.category === "image" || file.category === "video") {
        const response = await apiFetch(`/files/platform/${file.id}/preview`, {
          query,
          signal,
          cache: "no-store",
        })
        if (!response.ok) throw await parseApiError(response)
        return { blob: await response.blob(), content: null, mediaType: null }
      }
      const result = await apiRequest<FileRevisionContent>(`/files/platform/${file.id}/content`, {
        query,
        signal,
        cache: "no-store",
      })
      return { blob: null, content: result.content, mediaType: result.content_type }
    },
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
}
