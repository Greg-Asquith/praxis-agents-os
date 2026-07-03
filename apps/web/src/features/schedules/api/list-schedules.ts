// apps/web/src/features/schedules/api/list-schedules.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { SchedulesListResponse } from "@/features/schedules/types"
import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"
import { apiRequest } from "@/lib/api/client"

type ListSchedulesParams = {
  agentId?: string
  includeInactive?: boolean
  limit?: number
  offset?: number
}

export const schedulesQueryKeys = {
  all: ["schedules"] as const,
  workspace: () => [...schedulesQueryKeys.all, activeWorkspaceQueryScope()] as const,
  details: () => [...schedulesQueryKeys.workspace(), "detail"] as const,
  detail: (scheduleId: string) => [...schedulesQueryKeys.details(), scheduleId] as const,
  lists: () => [...schedulesQueryKeys.workspace(), "list"] as const,
  list: (params: ListSchedulesParams = {}) => [...schedulesQueryKeys.lists(), params] as const,
  runs: (scheduleId: string) => [...schedulesQueryKeys.detail(scheduleId), "runs"] as const,
  runsList: (scheduleId: string, params: object = {}) =>
    [...schedulesQueryKeys.runs(scheduleId), params] as const,
}

function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
}

async function listSchedules({
  agentId,
  includeInactive = false,
  limit = 100,
  offset = 0,
}: ListSchedulesParams = {}) {
  return apiRequest<SchedulesListResponse>("/schedules/", {
    query: {
      agent_id: agentId,
      include_inactive: includeInactive,
      limit,
      offset,
    },
  })
}

function schedulesQueryOptions(params: ListSchedulesParams = {}) {
  return queryOptions({
    queryKey: schedulesQueryKeys.list(params),
    queryFn: () => listSchedules(params),
    staleTime: 15_000,
  })
}

export function useSchedulesQuery(params: ListSchedulesParams = {}) {
  return useSuspenseQuery(schedulesQueryOptions(params))
}
