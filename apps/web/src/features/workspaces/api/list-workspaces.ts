// apps/web/src/features/workspaces/api/list-workspaces.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import type { WorkspacesListResponse } from "@/features/workspaces/types"

export const workspacesQueryKey = ["workspaces", "list"] as const

async function listWorkspaces() {
  return apiRequest<WorkspacesListResponse>("/workspaces/", {
    query: { limit: 100, offset: 0 },
  })
}

export function workspacesQueryOptions() {
  return queryOptions({
    queryKey: workspacesQueryKey,
    queryFn: listWorkspaces,
    staleTime: 30_000,
  })
}

export function useWorkspacesQuery() {
  return useSuspenseQuery(workspacesQueryOptions())
}
