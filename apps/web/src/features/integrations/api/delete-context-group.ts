// apps/web/src/features/integrations/api/delete-context-group.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import { apiRequestNoContent } from "@/lib/api/client"

async function deleteContextGroup(groupId: string) {
  return apiRequestNoContent(`/integrations/context-groups/${groupId}`, { method: "DELETE" })
}

export function useDeleteContextGroupMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteContextGroup,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.contextGroups() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.activeContexts() }),
      ])
    },
  })
}
