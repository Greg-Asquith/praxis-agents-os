// apps/web/src/features/agents/api/get-agent.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { agentsQueryKeys } from "@/features/agents/api/list-agents"
import type { Agent } from "@/features/agents/types"
import { apiRequest } from "@/lib/api/client"

export async function getAgent(agentId: string) {
  return apiRequest<Agent>(`/agents/${agentId}`)
}

function agentQueryOptions(agentId: string) {
  return queryOptions({
    queryKey: agentsQueryKeys.detail(agentId),
    queryFn: () => getAgent(agentId),
    staleTime: 30_000,
  })
}

export function useAgentQuery(agentId: string) {
  return useSuspenseQuery(agentQueryOptions(agentId))
}
