// apps/web/src/features/agents/api/create-agent.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { Agent, AgentCreateRequest } from "@/features/agents/types"
import { apiRequest } from "@/lib/api/client"

export async function createAgent(payload: AgentCreateRequest) {
  return apiRequest<Agent>("/agents/", {
    body: payload,
    method: "POST",
  })
}

export function useCreateAgentMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createAgent,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentsQueryKeys.lists() })
    },
  })
}
