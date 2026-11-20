// apps/web/src/features/notifications/notification-content.ts

import type {
  AppNotification,
  NotificationAction,
  NotificationTarget,
} from "@/features/notifications/types"
import { titleCaseToken } from "@/lib/format"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export function notificationTarget(notification: AppNotification): NotificationTarget | null {
  const payload = isRecord(notification.payload) ? notification.payload : {}
  const conversationId = payload["conversation_id"]
  if (isNonEmptyString(conversationId)) {
    return { kind: "conversation", conversationId }
  }
  const providerKey = payload["provider_key"]
  if (notification.notification_type.startsWith("integration_") && isNonEmptyString(providerKey)) {
    return { kind: "integration", providerKey }
  }
  return null
}

export function notificationActions(notification: AppNotification): NotificationAction[] {
  if (notification.actioned_at !== null || !Array.isArray(notification.actions)) {
    return []
  }
  return notification.actions.flatMap((action: unknown) => {
    if (!isRecord(action)) {
      return []
    }
    const key = action["key"]
    const label = action["label"]
    if (!isNonEmptyString(key)) {
      return []
    }
    return [{ key, label: isNonEmptyString(label) ? label : titleCaseToken(key, "Open") }]
  })
}
