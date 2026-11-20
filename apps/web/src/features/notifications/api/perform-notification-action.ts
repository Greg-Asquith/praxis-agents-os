// apps/web/src/features/notifications/api/perform-notification-action.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { notificationsQueryKeys } from "@/features/notifications/api/list-notifications"
import type { NotificationActionResponse } from "@/features/notifications/types"
import { apiRequest } from "@/lib/api/client"

type PerformNotificationActionInput = {
  notificationId: string
  actionKey: string
}

export function usePerformNotificationActionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ notificationId, actionKey }: PerformNotificationActionInput) =>
      apiRequest<NotificationActionResponse>(
        `/notifications/${notificationId}/actions/${encodeURIComponent(actionKey)}`,
        { method: "POST" }
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: notificationsQueryKeys.workspace() })
    },
  })
}
