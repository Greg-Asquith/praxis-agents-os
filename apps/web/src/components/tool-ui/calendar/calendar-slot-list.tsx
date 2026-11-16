// apps/web/src/components/tool-ui/calendar/calendar-slot-list.tsx

import type { ReactNode } from "react"
import { ClockIcon } from "lucide-react"

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { CalendarDayGroups } from "@/components/tool-ui/calendar/calendar-event-list"
import { formatLocalRange, timeZoneLabel } from "@/components/tool-ui/calendar/calendar-time"

export type CalendarSlot = {
  badge?: ReactNode
  detail?: ReactNode
  end: string
  key: string
  start: string
  timeZone: string
}

export function CalendarSlotList({
  ariaLabel,
  emptyLabel,
  slots,
}: {
  ariaLabel: string
  emptyLabel: string
  slots: CalendarSlot[]
}) {
  if (slots.length === 0) {
    return <EmptyResult>{emptyLabel}</EmptyResult>
  }
  return (
    <CalendarDayGroups
      ariaLabel={ariaLabel}
      items={slots}
      keyOf={(slot) => slot.key}
      renderItem={(slot) => (
        <div className="flex min-w-0 items-start gap-2.5 rounded-md border px-3 py-2">
          <ClockIcon className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />
          <div className="grid min-w-0 flex-1 gap-0.5">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{formatLocalRange(slot.start, slot.end)}</span>
              <span className="text-muted-foreground text-xs">{timeZoneLabel(slot.timeZone)}</span>
              {slot.badge}
            </div>
            {slot.detail ? (
              <div className="text-muted-foreground text-xs wrap-break-word">{slot.detail}</div>
            ) : null}
          </div>
        </div>
      )}
      startOf={(slot) => slot.start}
    />
  )
}
