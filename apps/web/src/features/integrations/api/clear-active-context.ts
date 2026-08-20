// apps/web/src/features/integrations/api/clear-active-context.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ActiveContextRead } from "@/features/integrations/types"
import { apiRequestNoContent } from "@/lib/api/client"

async function clearActiveContext(conversationId: string) {
  return apiRequestNoContent(`/integrations/conversations/${conversationId}/context`, {
    method: "DELETE",
  })
}

export function useClearActiveContextMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: clearActiveContext,
    onSuccess: (_response, conversationId) => {
      queryClient.setQueryData<ActiveContextRead>(
        integrationsQueryKeys.activeContext(conversationId),
        { entries: [], targets: [], unavailable: [] }
      )
    },
  })
}
