// apps/web/src/features/tools/api/list-tool-presentations.ts

import { queryOptions } from "@tanstack/react-query"

import { toolsQueryKeys } from "@/features/tools/api/query-keys"
import type { ToolPresentationsResponse } from "@/features/tools/types"
import { apiRequest } from "@/lib/api/client"

async function listToolPresentations() {
  return apiRequest<ToolPresentationsResponse>("/tools/presentations")
}

export function toolPresentationsQueryOptions() {
  return queryOptions({
    queryKey: toolsQueryKeys.presentations(),
    queryFn: listToolPresentations,
    staleTime: 5 * 60_000,
  })
}
