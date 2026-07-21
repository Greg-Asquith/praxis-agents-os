// apps/web/src/features/integrations/api/list-resources.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { IntegrationResource } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function listResources(connectionId: string) {
  return apiRequest<IntegrationResource[]>(`/integrations/connections/${connectionId}/resources`)
}

export function integrationResourcesForConnectionQueryOptions(connectionId: string) {
  return queryOptions({
    queryKey: integrationsQueryKeys.resources(connectionId),
    queryFn: () => listResources(connectionId),
    staleTime: 15_000,
  })
}

export function useIntegrationResourcesForConnectionQuery(connectionId: string) {
  return useSuspenseQuery(integrationResourcesForConnectionQueryOptions(connectionId))
}
