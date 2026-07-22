// apps/web/src/features/integrations/api/list-integration-resources.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ConnectionListResponse, IntegrationResource } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type ResourceResponse = Omit<
  IntegrationResource,
  "connection_label" | "connection_owner_scope" | "provider_key"
>

async function listIntegrationResources() {
  const connections = await apiRequest<ConnectionListResponse>("/integrations/connections", {
    query: { limit: 200 },
  })
  const resourcesByConnection = await Promise.all(
    connections.items.map(async (connection) => {
      const resources = await apiRequest<ResourceResponse[]>(
        `/integrations/connections/${connection.id}/resources`
      )
      return resources.map((resource) => ({
        ...resource,
        connection_label: connection.label,
        connection_owner_scope: connection.owner_scope,
        connection_status: connection.status,
        provider_key: connection.provider_key,
      }))
    })
  )
  return resourcesByConnection
    .flat()
    .toSorted((left, right) =>
      left.display_name.localeCompare(right.display_name, undefined, { sensitivity: "base" })
    )
}

export function integrationResourcesQueryOptions() {
  return queryOptions({
    queryKey: integrationsQueryKeys.enabledResources(),
    queryFn: listIntegrationResources,
    staleTime: 30_000,
  })
}

export function useIntegrationResourcesQuery() {
  return useSuspenseQuery(integrationResourcesQueryOptions())
}
