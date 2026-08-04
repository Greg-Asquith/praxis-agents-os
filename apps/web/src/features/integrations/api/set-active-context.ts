// apps/web/src/features/integrations/api/set-active-context.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ActiveContextRead, ActiveContextTargets } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type SetActiveContextInput = {
  conversationId: string
  activeContext: ActiveContextTargets
}

async function setActiveContext({ activeContext, conversationId }: SetActiveContextInput) {
  return apiRequest<ActiveContextRead>(`/integrations/conversations/${conversationId}/context`, {
    body: activeContext,
    method: "PUT",
  })
}

export function useSetActiveContextMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: setActiveContext,
    onSuccess: (response, { conversationId }) => {
      queryClient.setQueryData(integrationsQueryKeys.activeContext(conversationId), response)
    },
  })
}
