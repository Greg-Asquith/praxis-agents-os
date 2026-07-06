// apps/web/src/features/tools/api/list-tool-presentations.ts

import { queryOptions } from "@tanstack/react-query"

import type { ToolPresentationsResponse } from "@/features/tools/types"
import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"
import { apiRequest } from "@/lib/api/client"

const toolPresentationsQueryKeys = {
  all: ["tools"] as const,
  workspace: () => [...toolPresentationsQueryKeys.all, activeWorkspaceQueryScope()] as const,
  presentations: () => [...toolPresentationsQueryKeys.workspace(), "presentations"] as const,
}

function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
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
