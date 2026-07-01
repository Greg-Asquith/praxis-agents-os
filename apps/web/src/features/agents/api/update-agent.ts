// apps/web/src/features/agents/api/update-agent.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { Agent, AgentUpdateRequest } from "@/features/agents/types"
import { apiRequest } from "@/lib/api/client"

type UpdateAgentInput = {
  agentId: string
  payload: AgentUpdateRequest
}

export async function updateAgent({ agentId, payload }: UpdateAgentInput) {
  return apiRequest<Agent>(`/agents/${agentId}`, {
    body: payload,
    method: "PATCH",
  })
}

export function useUpdateAgentMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateAgent,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentsQueryKeys.all })
    },
  })
}
