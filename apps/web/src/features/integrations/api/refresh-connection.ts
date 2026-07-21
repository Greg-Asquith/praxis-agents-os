// apps/web/src/features/integrations/api/refresh-connection.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ConnectionRefreshResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function refreshConnection(connectionId: string) {
  return apiRequest<ConnectionRefreshResponse>(
    `/integrations/connections/${connectionId}/refresh`,
    { method: "POST" }
  )
}

export function useRefreshConnectionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: refreshConnection,
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() })
    },
  })
}
