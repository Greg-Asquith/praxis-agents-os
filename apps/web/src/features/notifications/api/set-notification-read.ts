// apps/web/src/features/notifications/api/set-notification-read.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { notificationsQueryKeys } from "@/features/notifications/api/list-notifications"
import type { AppNotification } from "@/features/notifications/types"
import { apiRequest } from "@/lib/api/client"

type SetNotificationReadInput = {
  notificationId: string
  read: boolean
}

export function useSetNotificationReadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ notificationId, read }: SetNotificationReadInput) =>
      apiRequest<AppNotification>(`/notifications/${notificationId}/${read ? "read" : "unread"}`, {
        method: "POST",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: notificationsQueryKeys.workspace() })
    },
  })
}
