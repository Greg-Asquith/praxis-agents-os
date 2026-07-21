// apps/web/src/features/integrations/api/test-connection.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ConnectionTestResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function testConnection(connectionId: string) {
  return apiRequest<ConnectionTestResponse>(`/integrations/connections/${connectionId}/test`, {
    method: "POST",
  })
}

export function useTestConnectionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: testConnection,
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() })
    },
  })
}
