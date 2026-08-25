// apps/web/src/features/integrations/api/list-resource-tables.ts

import { infiniteQueryOptions, useInfiniteQuery } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { TableScopeTableListResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function listResourceTables({
  connectionId,
  cursor,
  resourceId,
}: {
  connectionId: string
  cursor: string | undefined
  resourceId: string
}) {
  return apiRequest<TableScopeTableListResponse>(
    `/integrations/connections/${connectionId}/resources/${resourceId}/tables`,
    { query: { cursor, limit: 100 } }
  )
}

export function useResourceTablesQuery({
  connectionId,
  enabled,
  resourceId,
}: {
  connectionId: string
  enabled: boolean
  resourceId: string
}) {
  return useInfiniteQuery(resourceTablesQueryOptions({ connectionId, enabled, resourceId }))
}

export function resourceTablesQueryOptions({
  connectionId,
  enabled,
  resourceId,
}: {
  connectionId: string
  enabled: boolean
  resourceId: string
}) {
  return infiniteQueryOptions({
    queryKey: integrationsQueryKeys.resourceTables(connectionId, resourceId),
    queryFn: ({ pageParam }) => listResourceTables({ connectionId, cursor: pageParam, resourceId }),
    enabled,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    initialPageParam: undefined as string | undefined,
  })
}
