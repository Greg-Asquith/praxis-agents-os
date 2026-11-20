// apps/web/src/features/notifications/api/list-notifications.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import type { NotificationsListResponse } from "@/features/notifications/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

// Matches the Home attention queue, so the bell and Home agree.
export const NOTIFICATIONS_REFETCH_INTERVAL_MS = 30_000

const baseNotificationsQueryKeys = createWorkspaceScopedQueryKeys("notifications")

export const notificationsQueryKeys = {
  ...baseNotificationsQueryKeys,
  unreadCount: () => [...baseNotificationsQueryKeys.workspace(), "unread-count"] as const,
}

async function listNotifications(limit: number) {
  return apiRequest<NotificationsListResponse>("/notifications/", { query: { limit } })
}

function notificationsQueryOptions(limit: number) {
  return queryOptions({
    queryKey: notificationsQueryKeys.list({ limit }),
    queryFn: () => listNotifications(limit),
    refetchInterval: NOTIFICATIONS_REFETCH_INTERVAL_MS,
    placeholderData: keepPreviousData,
  })
}

// Not suspense: the panel sits in the app header, outside any page's error boundary.
export function useNotificationsQuery(limit: number) {
  return useQuery(notificationsQueryOptions(limit))
}
