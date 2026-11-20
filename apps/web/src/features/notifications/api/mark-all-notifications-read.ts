// apps/web/src/features/notifications/api/mark-all-notifications-read.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { notificationsQueryKeys } from "@/features/notifications/api/list-notifications"
import { apiRequest } from "@/lib/api/client"

export function useMarkAllNotificationsReadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiRequest<{ updated: number }>("/notifications/read-all", { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: notificationsQueryKeys.workspace() })
    },
  })
}
