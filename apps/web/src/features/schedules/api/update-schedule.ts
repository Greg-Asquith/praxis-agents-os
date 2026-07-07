// apps/web/src/features/schedules/api/update-schedule.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type { AgentSchedule, ScheduleUpdateRequest } from "@/features/schedules/types"
import { apiRequest } from "@/lib/api/client"

type UpdateScheduleInput = {
  payload: ScheduleUpdateRequest
  scheduleId: string
}

async function updateSchedule({ payload, scheduleId }: UpdateScheduleInput) {
  return apiRequest<AgentSchedule>(`/schedules/${scheduleId}`, {
    body: payload,
    method: "PATCH",
  })
}

export function useUpdateScheduleMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateSchedule,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.workspace() })
    },
  })
}
