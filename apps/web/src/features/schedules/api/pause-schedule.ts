// apps/web/src/features/schedules/api/pause-schedule.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type { AgentSchedule } from "@/features/schedules/types"
import { apiRequest } from "@/lib/api/client"

async function pauseSchedule(scheduleId: string) {
  return apiRequest<AgentSchedule>(`/schedules/${scheduleId}/pause`, {
    method: "POST",
  })
}

export function usePauseScheduleMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: pauseSchedule,
    onSuccess: async (_schedule, scheduleId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.detail(scheduleId) }),
      ])
    },
  })
}
