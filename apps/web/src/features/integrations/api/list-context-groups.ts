// apps/web/src/features/integrations/api/list-context-groups.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ContextGroupListResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function listContextGroups() {
  return apiRequest<ContextGroupListResponse>("/integrations/context-groups")
}

export function contextGroupsQueryOptions() {
  return queryOptions({
    queryKey: integrationsQueryKeys.contextGroups(),
    queryFn: listContextGroups,
    staleTime: 30_000,
  })
}

export function useContextGroupsQuery() {
  return useSuspenseQuery(contextGroupsQueryOptions())
}
