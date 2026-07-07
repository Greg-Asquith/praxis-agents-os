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
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: schedulesQueryKeys.workspace() })
    },
  })
}
