// apps/web/src/features/schedules/api/run-schedule-now.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type { AgentSchedule } from "@/features/schedules/types"
import { apiRequest } from "@/lib/api/client"

async function runScheduleNow(scheduleId: string) {
  return apiRequest<AgentSchedule>(`/schedules/${scheduleId}/run-now`, {
    method: "POST",
  })
}

export function useRunScheduleNowMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: runScheduleNow,
    onSuccess: async (_schedule, scheduleId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.detail(scheduleId) }),
        queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.runs(scheduleId) }),
      ])
    },
  })
}
