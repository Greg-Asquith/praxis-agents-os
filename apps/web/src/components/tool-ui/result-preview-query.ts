// apps/web/src/components/tool-ui/result-preview-query.ts

import { queryOptions } from "@tanstack/react-query"

import { type ResultPreview, resultListLength } from "@/components/tool-ui/result-preview"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const queryKeys = createWorkspaceScopedQueryKeys("retained-tool-results")

export function retainedResultQueryOptions(preview: ResultPreview) {
  return queryOptions({
    queryKey: [...queryKeys.workspace(), preview.fileId],
    queryFn: async ({ signal }): Promise<unknown> => {
      const { revisions } = await apiRequest<{
        revisions: { id: string; revision_number: number }[]
      }>(`/files/${preview.fileId}/revisions`, { signal })
      // Snapshots pin their initial revision even if the File is edited later.
      const revision = revisions.find((item) => item.revision_number === 1)
      if (!revision) throw new Error("The saved result is unavailable.")
      const { content } = await apiRequest<{ content: string }>(
        `/files/${preview.fileId}/revisions/${revision.id}/content`,
        { signal }
      )
      const data: unknown = JSON.parse(content)
      if (preview.lists.some(({ path, total }) => resultListLength(data, path) !== total)) {
        throw new Error("The saved result does not match this report.")
      }
      return data
    },
    staleTime: Infinity,
    retry: false,
  })
}
