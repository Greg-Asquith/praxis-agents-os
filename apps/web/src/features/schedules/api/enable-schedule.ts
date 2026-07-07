// apps/web/src/features/schedules/api/enable-schedule.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import type { AgentSchedule } from "@/features/schedules/types"
import { apiRequest } from "@/lib/api/client"

async function enableSchedule(scheduleId: string) {
  return apiRequest<AgentSchedule>(`/schedules/${scheduleId}/enable`, {
    method: "POST",
  })
}

export function useEnableScheduleMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: enableSchedule,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.workspace() })
    },
  })
}
