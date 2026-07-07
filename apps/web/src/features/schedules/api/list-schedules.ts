// apps/web/src/features/schedules/api/list-schedules.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { SchedulesListResponse } from "@/features/schedules/types"
import { createWorkspaceScopedQueryKeys } from "@/features/workspaces/query-keys"
import { apiRequest } from "@/lib/api/client"

type ListSchedulesParams = {
  agentId?: string
  includeInactive?: boolean
  limit?: number
  offset?: number
}

const baseSchedulesQueryKeys = createWorkspaceScopedQueryKeys("schedules")

export const schedulesQueryKeys = {
  ...baseSchedulesQueryKeys,
  runs: (scheduleId: string) => [...baseSchedulesQueryKeys.detail(scheduleId), "runs"] as const,
  runsList: (scheduleId: string, params: object = {}) =>
    [...baseSchedulesQueryKeys.detail(scheduleId), "runs", params] as const,
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
