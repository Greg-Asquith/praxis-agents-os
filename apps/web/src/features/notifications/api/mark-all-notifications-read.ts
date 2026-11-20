// apps/web/src/features/notifications/api/mark-all-notifications-read.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { notificationsQueryKeys } from "@/features/notifications/api/list-notifications"
import type { MarkAllNotificationsReadResponse } from "@/features/notifications/types"
import { apiRequest } from "@/lib/api/client"

export function useMarkAllNotificationsReadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiRequest<MarkAllNotificationsReadResponse>("/notifications/read-all", { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: notificationsQueryKeys.workspace() })
    },
  })
}
