// apps/web/src/components/tool-ui/calendar/calendar-event-list.tsx

import type { ReactNode } from "react"
import { CalendarDaysIcon, MapPinIcon } from "lucide-react"

import { EmptyResult } from "@/components/tool-ui/empty-result"
import {
  formatLocalDay,
  formatLocalRange,
  groupByLocalDay,
  timeZoneLabel,
} from "@/components/tool-ui/calendar/calendar-time"
import { pluralize } from "@/lib/format"

export type CalendarEventItem = {
  allDay: boolean
  badges?: ReactNode
  end: string
  key: string
  location: string
  start: string
  timeZone: string
  title: string
}

export function CalendarEventTime({ event }: { event: CalendarEventItem }) {
  return (
    <p className="text-muted-foreground text-xs">
      {formatLocalRange(event.start, event.end, event.allDay)}
      <span aria-label="Time zone"> · {timeZoneLabel(event.timeZone)}</span>
    </p>
  )
}

function CalendarEventRow({ event }: { event: CalendarEventItem }) {
  return (
    <article className="flex w-full min-w-0 items-start gap-2.5 rounded-md border px-3 py-2.5">
      <div className="bg-muted text-muted-foreground mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md">
        <CalendarDaysIcon className="size-3.5" />
      </div>
      <div className="grid min-w-0 flex-1 gap-0.5">
        <p className="text-sm font-medium wrap-break-word">{event.title || "(No subject)"}</p>
        <CalendarEventTime event={event} />
        {event.location ? (
          <p className="text-muted-foreground flex min-w-0 items-center gap-1 text-xs">
            <MapPinIcon className="size-3 shrink-0" />
            <span className="min-w-0 wrap-break-word">{event.location}</span>
          </p>
        ) : null}
        {event.badges ? (
          <div className="mt-1 flex min-w-0 flex-wrap gap-1.5">{event.badges}</div>
        ) : null}
      </div>
    </article>
  )
}

export function CalendarDayGroups<T>({
  ariaLabel,
  items,
  keyOf,
  renderItem,
  startOf,
}: {
  ariaLabel: string
  items: T[]
  keyOf: (item: T) => string
  renderItem: (item: T) => ReactNode
  startOf: (item: T) => string
}) {
  return (
    <div
      aria-label={ariaLabel}
      className="grid max-h-[min(32rem,60vh)] min-w-0 gap-3 overflow-y-auto overscroll-contain pr-1"
    >
      {groupByLocalDay(items, startOf).map(([day, dayItems]) => (
        <section
          aria-label={formatLocalDay(startOf(dayItems[0] as T))}
          className="grid gap-2"
          key={day}
        >
          <h4 className="text-muted-foreground text-xs font-medium">
            {formatLocalDay(startOf(dayItems[0] as T))}
          </h4>
          <div className="grid min-w-0 gap-2" role="list">
            {dayItems.map((item) => (
              <div className="min-w-0" key={keyOf(item)} role="listitem">
                {renderItem(item)}
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

export function CalendarEventList({
  ariaLabel,
  emptyLabel,
  events,
}: {
  ariaLabel: string
  emptyLabel: string
  events: CalendarEventItem[]
}) {
  if (events.length === 0) {
    return <EmptyResult>{emptyLabel}</EmptyResult>
  }
  return (
    <div className="grid min-w-0 gap-2">
      <p className="text-muted-foreground text-xs">
        {String(events.length)} {pluralize(events.length, "Event")}
      </p>
      <CalendarDayGroups
        ariaLabel={ariaLabel}
        items={events}
        keyOf={(event) => event.key}
        renderItem={(event) => <CalendarEventRow event={event} />}
        startOf={(event) => event.start}
      />
    </div>
  )
}
