// apps/web/src/features/workspaces/api/list-memberships.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import type { WorkspaceMembershipsListResponse } from "@/features/workspaces/types"

function workspaceMembershipsQueryKey(workspaceId: string) {
  return ["workspaces", workspaceId, "memberships"] as const
}

async function listMemberships(workspaceId: string) {
  return apiRequest<WorkspaceMembershipsListResponse>(`/workspaces/${workspaceId}/memberships`, {
    query: { limit: 100, offset: 0 },
  })
}

function workspaceMembershipsQueryOptions(workspaceId: string) {
  return queryOptions({
    queryKey: workspaceMembershipsQueryKey(workspaceId),
    queryFn: () => listMemberships(workspaceId),
    staleTime: 30_000,
  })
}

export function useWorkspaceMembershipsQuery(workspaceId: string) {
  return useSuspenseQuery(workspaceMembershipsQueryOptions(workspaceId))
}
