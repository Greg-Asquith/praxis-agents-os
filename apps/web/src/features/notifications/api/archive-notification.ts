// apps/web/src/features/notifications/api/archive-notification.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { notificationsQueryKeys } from "@/features/notifications/api/list-notifications"
import type { AppNotification } from "@/features/notifications/types"
import { apiRequest } from "@/lib/api/client"

export function useArchiveNotificationMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (notificationId: string) =>
      apiRequest<AppNotification>(`/notifications/${notificationId}/archive`, { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: notificationsQueryKeys.workspace() })
    },
  })
}
