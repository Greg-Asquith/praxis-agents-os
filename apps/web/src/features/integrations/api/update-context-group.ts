// apps/web/src/features/integrations/api/update-context-group.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type {
  ContextGroupWriteRequest,
  IntegrationContextGroup,
} from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type UpdateContextGroupInput = {
  groupId: string
  payload: ContextGroupWriteRequest
}

async function updateContextGroup({ groupId, payload }: UpdateContextGroupInput) {
  return apiRequest<IntegrationContextGroup>(`/integrations/context-groups/${groupId}`, {
    body: payload,
    method: "PATCH",
  })
}

export function useUpdateContextGroupMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateContextGroup,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.contextGroups() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.activeContexts() }),
      ])
    },
  })
}
