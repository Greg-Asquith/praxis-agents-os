// apps/web/src/features/agents/api/list-agents.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { AgentsListResponse } from "@/features/agents/types"
import { apiRequest } from "@/lib/api/client"

type ListAgentsParams = {
  includeInactive?: boolean
  limit?: number
  offset?: number
}

export const agentsQueryKeys = {
  all: ["agents"] as const,
  lists: () => [...agentsQueryKeys.all, "list"] as const,
  list: (params: ListAgentsParams = {}) => [...agentsQueryKeys.lists(), params] as const,
}

export async function listAgents({
  includeInactive = false,
  limit = 100,
  offset = 0,
}: ListAgentsParams = {}) {
  return apiRequest<AgentsListResponse>("/agents/", {
    query: {
      include_inactive: includeInactive,
      limit,
      offset,
    },
  })
}

export function agentsQueryOptions(params: ListAgentsParams = {}) {
  return queryOptions({
    queryKey: agentsQueryKeys.list(params),
    queryFn: () => listAgents(params),
    staleTime: 30_000,
  })
}

export function useAgentsQuery(params: ListAgentsParams = {}) {
  return useSuspenseQuery(agentsQueryOptions(params))
}
