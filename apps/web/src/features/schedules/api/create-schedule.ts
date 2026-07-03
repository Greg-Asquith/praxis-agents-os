// apps/web/src/features/schedules/api/create-schedule.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type { AgentSchedule, ScheduleCreateRequest } from "@/features/schedules/types"
import { apiRequest } from "@/lib/api/client"

async function createSchedule(payload: ScheduleCreateRequest) {
  return apiRequest<AgentSchedule>("/schedules/", {
    body: payload,
    method: "POST",
  })
}

export function useCreateScheduleMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createSchedule,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.lists() })
    },
  })
}
