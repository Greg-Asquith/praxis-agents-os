// apps/web/src/features/integrations/api/update-resource-selection.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ResourceSelectionResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type UpdateResourceSelectionInput = {
  connectionId: string
  enabledResourceIds: string[]
}

async function updateResourceSelection({
  connectionId,
  enabledResourceIds,
}: UpdateResourceSelectionInput) {
  return apiRequest<ResourceSelectionResponse>(
    `/integrations/connections/${connectionId}/resources/selection`,
    {
      body: { enabled_resource_ids: enabledResourceIds },
      method: "PUT",
    }
  )
}

export function useUpdateResourceSelectionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateResourceSelection,
    onSuccess: async (_response, { connectionId }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.resources(connectionId) }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.enabledResources() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.activeContexts() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.contextGroups() }),
      ])
    },
  })
}
