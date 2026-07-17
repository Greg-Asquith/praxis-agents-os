// apps/web/src/features/schedules/api/get-schedule.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type { AgentSchedule } from "@/features/schedules/types"
import { apiRequest } from "@/lib/api/client"

export async function getSchedule(scheduleId: string) {
  return apiRequest<AgentSchedule>(`/schedules/${scheduleId}`)
}

export function scheduleQueryOptions(scheduleId: string) {
  return queryOptions({
    queryKey: schedulesQueryKeys.detail(scheduleId),
    queryFn: () => getSchedule(scheduleId),
    staleTime: 15_000,
  })
}

export function useScheduleQuery(scheduleId: string) {
  return useSuspenseQuery(scheduleQueryOptions(scheduleId))
}
