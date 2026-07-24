// apps/web/src/features/integrations/api/list-connections.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ConnectionListResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function listConnections() {
  return apiRequest<ConnectionListResponse>("/integrations/connections", {
    query: { limit: 200 },
  })
}

export function integrationConnectionsQueryOptions() {
  return queryOptions({
    queryKey: integrationsQueryKeys.connections(),
    queryFn: listConnections,
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (connection) =>
          connection.status === "auth_pending" ||
          (connection.status === "discovery_pending" && connection.discovery_in_flight)
      )
        ? 5_000
        : false,
    staleTime: 15_000,
  })
}

export function useIntegrationConnectionsQuery() {
  return useSuspenseQuery(integrationConnectionsQueryOptions())
}
