// apps/web/src/features/notifications/components/notification-list.tsx

import { ArchiveIcon, MailIcon, MailOpenIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { notificationActions } from "@/features/notifications/notification-content"
import type { AppNotification } from "@/features/notifications/types"
import { relativeDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

type NotificationListProps = {
  notifications: AppNotification[]
  pending: boolean
  onAction: (notification: AppNotification, actionKey: string) => void
  onArchive: (notification: AppNotification) => void
  onOpen: (notification: AppNotification) => void
  onToggleRead: (notification: AppNotification) => void
}

export function NotificationList({
  notifications,
  pending,
  onAction,
  onArchive,
  onOpen,
  onToggleRead,
}: NotificationListProps) {
  return (
    <ul className="divide-y">
      {notifications.map((notification) => {
        const unread = notification.read_at === null
        const actions = notificationActions(notification)
        return (
          <li key={notification.id} className="hover:bg-muted/40 flex gap-2 px-3 py-2.5">
            <span
              aria-hidden="true"
              className={cn("mt-1.5 size-2 shrink-0 rounded-full", unread && "bg-primary")}
            />
            <div className="min-w-0 flex-1">
              <button
                type="button"
                className="focus-visible:ring-ring w-full rounded-sm text-left outline-none focus-visible:ring-2 hover:cursor-pointer"
                onClick={() => {
                  onOpen(notification)
                }}
              >
                <span className={cn("block text-sm wrap-break-word", unread && "font-medium")}>
                  {unread ? <span className="sr-only">Unread: </span> : null}
                  {notification.title}
                </span>
                {notification.body ? (
                  <span className="text-muted-foreground mt-0.5 line-clamp-2 block text-xs wrap-break-word">
                    {notification.body}
                  </span>
                ) : null}
                <span className="text-muted-foreground mt-1 block text-xs">
                  {relativeDateTime(notification.created_at)}
                </span>
              </button>
              {actions.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {actions.map((action) => (
                    <Button
                      key={action.key}
                      disabled={pending}
                      size="xs"
                      type="button"
                      variant="outline"
                      onClick={() => {
                        onAction(notification, action.key)
                      }}
                    >
                      {action.label}
                    </Button>
                  ))}
                </div>
              ) : null}
            </div>
            <div className="flex shrink-0 items-start gap-0.5">
              <Button
                aria-label={unread ? "Mark as Read" : "Mark as Unread"}
                disabled={pending}
                size="icon-xs"
                title={unread ? "Mark as Read" : "Mark as Unread"}
                type="button"
                variant="ghost"
                onClick={() => {
                  onToggleRead(notification)
                }}
              >
                {unread ? <MailOpenIcon /> : <MailIcon />}
              </Button>
              <Button
                aria-label="Archive"
                disabled={pending}
                size="icon-xs"
                title="Archive"
                type="button"
                variant="ghost"
                onClick={() => {
                  onArchive(notification)
                }}
              >
                <ArchiveIcon />
              </Button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
