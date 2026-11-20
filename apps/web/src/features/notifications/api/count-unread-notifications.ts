// apps/web/src/features/notifications/api/count-unread-notifications.ts

import { queryOptions, useQuery } from "@tanstack/react-query"

import {
  NOTIFICATIONS_REFETCH_INTERVAL_MS,
  notificationsQueryKeys,
} from "@/features/notifications/api/list-notifications"
import type { UnreadNotificationCount } from "@/features/notifications/types"
import { apiRequest } from "@/lib/api/client"

async function countUnreadNotifications() {
  return apiRequest<UnreadNotificationCount>("/notifications/unread-count")
}

function unreadNotificationCountQueryOptions() {
  return queryOptions({
    queryKey: notificationsQueryKeys.unreadCount(),
    queryFn: countUnreadNotifications,
    refetchInterval: NOTIFICATIONS_REFETCH_INTERVAL_MS,
  })
}

// Not suspense: the header renders before the count arrives.
export function useUnreadNotificationCountQuery() {
  return useQuery(unreadNotificationCountQueryOptions())
}
