// apps/web/src/features/integrations/api/list-table-scopes.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { TableScopeListResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function listTableScopes(connectionId: string) {
  return apiRequest<TableScopeListResponse>(
    `/integrations/connections/${connectionId}/table-scopes`
  )
}

export function tableScopesQueryOptions(connectionId: string) {
  return queryOptions({
    queryKey: integrationsQueryKeys.tableScopes(connectionId),
    queryFn: () => listTableScopes(connectionId),
    staleTime: 15_000,
  })
}

export function useTableScopesQuery(connectionId: string) {
  return useSuspenseQuery(tableScopesQueryOptions(connectionId))
}
