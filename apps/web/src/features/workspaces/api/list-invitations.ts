// apps/web/src/features/workspaces/api/list-invitations.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import type { WorkspaceInvitationsListResponse } from "@/features/workspaces/types"

export function workspaceInvitationsQueryKey(workspaceId: string) {
  return ["workspaces", workspaceId, "invitations"] as const
}

async function listInvitations(workspaceId: string) {
  return apiRequest<WorkspaceInvitationsListResponse>(`/workspaces/${workspaceId}/invitations`, {
    query: {
      include_accepted: false,
      include_expired: false,
      limit: 100,
      offset: 0,
    },
  })
}

function workspaceInvitationsQueryOptions(workspaceId: string) {
  return queryOptions({
    queryKey: workspaceInvitationsQueryKey(workspaceId),
    queryFn: () => listInvitations(workspaceId),
    staleTime: 30_000,
  })
}

export function useWorkspaceInvitationsQuery(workspaceId: string) {
  return useSuspenseQuery(workspaceInvitationsQueryOptions(workspaceId))
}
