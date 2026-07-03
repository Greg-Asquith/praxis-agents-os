// apps/web/src/features/schedules/api/list-schedule-runs.ts

import { queryOptions, useQuery } from "@tanstack/react-query"

import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type { ScheduleRunsListResponse, ScheduleRunStatus } from "@/features/schedules/types"
import { apiRequest } from "@/lib/api/client"

type ListScheduleRunsParams = {
  limit?: number
  offset?: number
  status?: ScheduleRunStatus
}

async function listScheduleRuns(
  scheduleId: string,
  { limit = 100, offset = 0, status }: ListScheduleRunsParams = {}
) {
  return apiRequest<ScheduleRunsListResponse>(`/schedules/${scheduleId}/runs`, {
    query: {
      limit,
      offset,
      status,
    },
  })
}

function scheduleRunsQueryOptions(scheduleId: string, params: ListScheduleRunsParams = {}) {
  return queryOptions({
    queryKey: schedulesQueryKeys.runsList(scheduleId, params),
    queryFn: () => listScheduleRuns(scheduleId, params),
    refetchInterval: 15_000,
  })
}

export function useScheduleRunsQuery(scheduleId: string, params: ListScheduleRunsParams = {}) {
  return useQuery(scheduleRunsQueryOptions(scheduleId, params))
}
