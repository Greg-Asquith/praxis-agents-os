// apps/web/src/features/conversations/api/get-page-speed-report.ts

import { queryOptions } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const queryKeys = createWorkspaceScopedQueryKeys("page-speed-reports")

/** Loads a measure_page_speed report File's text; each page's report is a range of it. */
export function pageSpeedReportQueryOptions(fileId: string) {
  return queryOptions({
    queryKey: queryKeys.detail(fileId),
    queryFn: async ({ signal }): Promise<string> => {
      const { revisions } = await apiRequest<{
        revisions: { id: string; revision_number: number }[]
      }>(`/files/${fileId}/revisions`, { signal })
      // The report pins its first revision, which holds the ranges the rows name.
      const revision = revisions.find((item) => item.revision_number === 1)
      if (!revision) throw new Error("The saved report is unavailable.")
      const { content } = await apiRequest<{ content: string }>(
        `/files/${fileId}/revisions/${revision.id}/content`,
        { signal }
      )
      return content
    },
    staleTime: Infinity,
    retry: false,
  })
}
