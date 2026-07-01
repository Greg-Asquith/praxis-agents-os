// apps/web/src/features/agents/api/list-agents.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { AgentsListResponse } from "@/features/agents/types"
import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"
import { apiRequest } from "@/lib/api/client"

type ListAgentsParams = {
  includeInactive?: boolean
  limit?: number
  offset?: number
}

export const agentsQueryKeys = {
  all: ["agents"] as const,
  workspace: () => [...agentsQueryKeys.all, activeWorkspaceQueryScope()] as const,
  details: () => [...agentsQueryKeys.workspace(), "detail"] as const,
  detail: (agentId: string) => [...agentsQueryKeys.details(), agentId] as const,
  lists: () => [...agentsQueryKeys.workspace(), "list"] as const,
  list: (params: ListAgentsParams = {}) => [...agentsQueryKeys.lists(), params] as const,
}

function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
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
