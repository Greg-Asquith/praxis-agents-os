// apps/web/src/features/integrations/api/create-context-group.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type {
  ContextGroupWriteRequest,
  IntegrationContextGroup,
} from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function createContextGroup(payload: ContextGroupWriteRequest) {
  return apiRequest<IntegrationContextGroup>("/integrations/context-groups", {
    body: payload,
    method: "POST",
  })
}

export function useCreateContextGroupMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createContextGroup,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.contextGroups() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.activeContexts() }),
      ])
    },
  })
}
