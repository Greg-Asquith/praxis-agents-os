// apps/web/src/features/agents/api/delete-agent.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import { apiRequest } from "@/lib/api/client"

export async function deleteAgent(agentId: string) {
  return apiRequest<undefined>(`/agents/${agentId}`, {
    method: "DELETE",
  })
}

export function useDeleteAgentMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteAgent,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentsQueryKeys.all })
    },
  })
}
