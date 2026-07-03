// apps/web/src/features/schedules/api/delete-schedule.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { schedulesQueryKeys } from "@/features/schedules/api/list-schedules"
import { apiRequest } from "@/lib/api/client"

async function deleteSchedule(scheduleId: string) {
  return apiRequest<undefined>(`/schedules/${scheduleId}`, {
    method: "DELETE",
  })
}

export function useDeleteScheduleMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteSchedule,
    onSuccess: async (_result, scheduleId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.detail(scheduleId) }),
      ])
    },
  })
}
