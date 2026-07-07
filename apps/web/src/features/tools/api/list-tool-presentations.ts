// apps/web/src/features/tools/api/list-tool-presentations.ts

import { queryOptions } from "@tanstack/react-query"

import type { ToolPresentationsResponse } from "@/features/tools/types"
import { createWorkspaceScopedQueryKeys } from "@/features/workspaces/query-keys"
import { apiRequest } from "@/lib/api/client"

const baseToolPresentationsQueryKeys = createWorkspaceScopedQueryKeys("tools")

const toolPresentationsQueryKeys = {
  ...baseToolPresentationsQueryKeys,
  presentations: () => [...baseToolPresentationsQueryKeys.workspace(), "presentations"] as const,
}

async function listToolPresentations() {
  return apiRequest<ToolPresentationsResponse>("/tools/presentations")
}

export function toolPresentationsQueryOptions() {
  return queryOptions({
    queryKey: toolPresentationsQueryKeys.presentations(),
    queryFn: listToolPresentations,
    staleTime: 5 * 60_000,
  })
}
