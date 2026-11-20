// apps/web/src/features/notifications/types.ts

export type AppNotification = {
  id: string
  notification_type: string
  source: string | null
  title: string
  body: string | null
  payload: unknown
  actions: unknown
  read_at: string | null
  actioned_at: string | null
  action_taken: string | null
  created_at: string
}

export type NotificationsListResponse = {
  items: AppNotification[]
  total: number
  limit: number
  offset: number
}

export type UnreadNotificationCount = {
  unread: number
}

export type MarkAllNotificationsReadResponse = {
  updated: number
}

export type NotificationActionResponse = {
  status: string
  result: unknown
  terminal: boolean | null
  action: string | null
}

export type NotificationAction = {
  key: string
  label: string
}

export type NotificationTarget =
  { kind: "conversation"; conversationId: string } | { kind: "integration"; providerKey: string }
