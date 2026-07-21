// apps/web/src/features/integrations/api/list-context-groups.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { ContextGroupListResponse } from "@/features/integrations/types"
import { createWorkspaceScopedQueryKeys } from "@/features/workspaces/query-keys"
import { apiRequest } from "@/lib/api/client"

export const integrationContextQueryKeys = createWorkspaceScopedQueryKeys("integration-context")

async function listContextGroups() {
  return apiRequest<ContextGroupListResponse>("/integrations/context-groups")
}

export function contextGroupsQueryOptions() {
  return queryOptions({
    queryKey: integrationContextQueryKeys.list({ kind: "groups" }),
    queryFn: listContextGroups,
    staleTime: 30_000,
  })
}

export function useContextGroupsQuery() {
  return useSuspenseQuery(contextGroupsQueryOptions())
}
