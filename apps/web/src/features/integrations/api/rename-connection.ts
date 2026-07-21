// apps/web/src/features/integrations/api/rename-connection.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ConnectionListResponse, IntegrationConnection } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type RenameConnectionInput = {
  connectionId: string
  label: string
}

async function renameConnection({ connectionId, label }: RenameConnectionInput) {
  return apiRequest<IntegrationConnection>(`/integrations/connections/${connectionId}`, {
    body: { label },
    method: "PATCH",
  })
}

export function useRenameConnectionMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: renameConnection,
    onSuccess: async (connection) => {
      queryClient.setQueryData<ConnectionListResponse>(
        integrationsQueryKeys.connections(),
        (current) =>
          current
            ? {
                ...current,
                items: current.items.map((item) => (item.id === connection.id ? connection : item)),
              }
            : current
      )
      await queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() })
    },
  })
}
