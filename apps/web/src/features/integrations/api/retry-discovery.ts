// apps/web/src/features/integrations/api/retry-discovery.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { DiscoveryTriggerResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function retryDiscovery(connectionId: string) {
  return apiRequest<DiscoveryTriggerResponse>(
    `/integrations/connections/${connectionId}/discover`,
    { method: "POST" }
  )
}

export function useRetryDiscoveryMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: retryDiscovery,
    onSuccess: async (_response, connectionId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.resources(connectionId) }),
      ])
    },
  })
}
