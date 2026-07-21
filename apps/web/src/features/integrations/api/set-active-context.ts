// apps/web/src/features/integrations/api/set-active-context.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ActiveContextRead, ActiveContextSelectionValue } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type SetActiveContextInput = {
  conversationId: string
  selection: ActiveContextSelectionValue
}

async function setActiveContext({ conversationId, selection }: SetActiveContextInput) {
  return apiRequest<ActiveContextRead>(`/integrations/conversations/${conversationId}/context`, {
    body: selection,
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
