// apps/web/src/features/workspaces/api/list-memberships.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { listAllPages } from "@/lib/api/list-all-pages"
import { apiRequest } from "@/lib/api/client"
import type { WorkspaceMembershipsListResponse } from "@/features/workspaces/types"

function workspaceMembershipsQueryKey(workspaceId: string) {
  return ["workspaces", workspaceId, "memberships"] as const
}

async function listMemberships(workspaceId: string) {
  const memberships = await listAllPages(async (offset) => {
    const page = await apiRequest<WorkspaceMembershipsListResponse>(
      `/workspaces/${workspaceId}/memberships`,
      {
        query: { limit: 100, offset },
      }
    )
    return { items: page.memberships, total: page.total }
  })
  return { memberships, total: memberships.length, limit: memberships.length, offset: 0 }
}

export function workspaceMembershipsQueryOptions(workspaceId: string) {
  return queryOptions({
    queryKey: workspaceMembershipsQueryKey(workspaceId),
    queryFn: () => listMemberships(workspaceId),
    staleTime: 30_000,
  })
}

export function useWorkspaceMembershipsQuery(workspaceId: string) {
  return useSuspenseQuery(workspaceMembershipsQueryOptions(workspaceId))
}
