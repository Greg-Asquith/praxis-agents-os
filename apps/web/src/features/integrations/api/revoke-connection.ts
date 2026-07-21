// apps/web/src/features/integrations/api/revoke-connection.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { IntegrationConnection } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function revokeConnection(connectionId: string) {
  return apiRequest<IntegrationConnection>(`/integrations/connections/${connectionId}/revoke`, {
    method: "POST",
  })
}

export function useRevokeConnectionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: revokeConnection,
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() })
    },
  })
}
