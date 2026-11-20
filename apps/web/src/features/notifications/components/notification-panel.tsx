// apps/web/src/features/notifications/components/notification-panel.tsx

import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { BellIcon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { PopoverHeader, PopoverTitle } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { useArchiveNotificationMutation } from "@/features/notifications/api/archive-notification"
import { useNotificationsQuery } from "@/features/notifications/api/list-notifications"
import { useMarkAllNotificationsReadMutation } from "@/features/notifications/api/mark-all-notifications-read"
import { usePerformNotificationActionMutation } from "@/features/notifications/api/perform-notification-action"
import { useSetNotificationReadMutation } from "@/features/notifications/api/set-notification-read"
import { NotificationList } from "@/features/notifications/components/notification-list"
import { notificationTarget } from "@/features/notifications/notification-content"
import type { AppNotification, NotificationTarget } from "@/features/notifications/types"
import { getErrorMessage } from "@/lib/api/errors"
import { isNonEmptyString, isRecord } from "@/lib/guards"

const PAGE_SIZE = 20
// The API returns at most this many notifications in one request.
const MAX_LIMIT = 100

export function NotificationPanel({
  unread,
  onNavigate,
}: {
  unread: number
  onNavigate: () => void
}) {
  const [limit, setLimit] = useState(PAGE_SIZE)
  const query = useNotificationsQuery(limit)
  const navigate = useNavigate()
  const setRead = useSetNotificationReadMutation()
  const archive = useArchiveNotificationMutation()
  const markAllRead = useMarkAllNotificationsReadMutation()
  const performAction = usePerformNotificationActionMutation()
  const pending =
    setRead.isPending || archive.isPending || markAllRead.isPending || performAction.isPending
  const error =
    query.error ?? setRead.error ?? archive.error ?? markAllRead.error ?? performAction.error

  // Only the newest failure shows, so an old one doesn't outlive a later success.
  function clearErrors() {
    setRead.reset()
    archive.reset()
    markAllRead.reset()
    performAction.reset()
  }

  function go(target: NotificationTarget) {
    onNavigate()
    if (target.kind === "conversation") {
      void navigate({
        to: "/conversations/$conversationId",
        params: { conversationId: target.conversationId },
      })
      return
    }
    void navigate({
      to: "/integrations/$providerKey",
      params: { providerKey: target.providerKey },
    })
  }

  function open(notification: AppNotification) {
    if (notification.read_at === null) {
      clearErrors()
      setRead.mutate({ notificationId: notification.id, read: true })
    }
    const target = notificationTarget(notification)
    if (target !== null) {
      go(target)
    }
  }

  const notifications = query.data?.items ?? []
  const hasMore =
    query.data !== undefined && query.data.total > notifications.length && limit < MAX_LIMIT

  return (
    <>
      <PopoverHeader className="flex-row items-center justify-between gap-2 border-b px-3 py-2">
        <PopoverTitle>Notifications</PopoverTitle>
        <Button
          disabled={unread === 0 || pending}
          size="xs"
          type="button"
          variant="ghost"
          onClick={() => {
            clearErrors()
            markAllRead.mutate()
          }}
        >
          Mark All Read
        </Button>
      </PopoverHeader>
      {error ? (
        <Alert className="m-3 w-auto" variant="destructive">
          <AlertDescription>{getErrorMessage(error)}</AlertDescription>
        </Alert>
      ) : null}
      <div className="max-h-[min(28rem,70dvh)] overflow-y-auto">
        {query.isPending ? (
          <div className="flex flex-col gap-3 p-3">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : notifications.length === 0 && !query.isError ? (
          <EmptyState
            className="m-3"
            description="When background work fails or a connection needs attention, you'll see it here."
            icon={<BellIcon />}
            size="compact"
            title="No Notifications"
          />
        ) : (
          <NotificationList
            notifications={notifications}
            pending={pending}
            onAction={(notification, actionKey) => {
              clearErrors()
              performAction.mutate(
                { notificationId: notification.id, actionKey },
                {
                  onSuccess: ({ result }) => {
                    if (
                      isRecord(result) &&
                      result["status"] === "navigate" &&
                      isNonEmptyString(result["conversation_id"])
                    ) {
                      go({ kind: "conversation", conversationId: result["conversation_id"] })
                    }
                  },
                }
              )
            }}
            onArchive={(notification) => {
              clearErrors()
              archive.mutate(notification.id)
            }}
            onOpen={open}
            onToggleRead={(notification) => {
              clearErrors()
              setRead.mutate({
                notificationId: notification.id,
                read: notification.read_at === null,
              })
            }}
          />
        )}
        {hasMore ? (
          <div className="border-t p-2">
            <Button
              className="w-full"
              disabled={query.isFetching}
              size="sm"
              type="button"
              variant="ghost"
              onClick={() => {
                setLimit((current) => current + PAGE_SIZE)
              }}
            >
              Show More
            </Button>
          </div>
        ) : null}
      </div>
    </>
  )
}
