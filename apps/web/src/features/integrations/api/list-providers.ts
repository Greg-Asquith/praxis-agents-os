// apps/web/src/features/integrations/api/list-providers.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { IntegrationProvider } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function listProviders() {
  return apiRequest<IntegrationProvider[]>("/integrations/providers")
}

export function integrationProvidersQueryOptions() {
  return queryOptions({
    queryKey: integrationsQueryKeys.providers(),
    queryFn: listProviders,
    staleTime: 60_000,
  })
}

export function useIntegrationProvidersQuery() {
  return useSuspenseQuery(integrationProvidersQueryOptions())
}
