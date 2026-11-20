// apps/web/src/features/notifications/components/notification-bell.tsx

import { useState } from "react"
import { BellIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useUnreadNotificationCountQuery } from "@/features/notifications/api/count-unread-notifications"
import { NotificationPanel } from "@/features/notifications/components/notification-panel"

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const { data } = useUnreadNotificationCountQuery()
  const unread = data?.unread ?? 0

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            aria-label={unread > 0 ? `Notifications, ${String(unread)} unread` : "Notifications"}
            className="relative"
            size="icon"
            type="button"
            variant="ghost"
          >
            <BellIcon />
            {unread > 0 ? (
              <span
                aria-hidden="true"
                className="bg-primary text-primary-foreground absolute -top-0.5 -right-0.5 h-4 min-w-4 rounded-full px-1 text-[10px] leading-4 font-medium tabular-nums"
              >
                {unread > 99 ? "99+" : unread}
              </span>
            ) : null}
          </Button>
        }
      />
      <PopoverContent align="end" className="w-[min(24rem,calc(100vw-2rem))] gap-0 p-0">
        <NotificationPanel
          unread={unread}
          onNavigate={() => {
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
