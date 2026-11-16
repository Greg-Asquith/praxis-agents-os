// apps/web/src/integrations/outlook_calendar/components/event.tsx

import { LockIcon, VideoIcon } from "lucide-react"

import {
  CalendarEventList,
  CalendarEventTime,
  type CalendarEventItem,
} from "@/components/tool-ui/calendar/calendar-event-list"
import { DetailList } from "@/components/tool-ui/detail-list"
import { ExternalContent } from "@/components/tool-ui/external-content"
import { Badge } from "@/components/ui/badge"
import {
  AVAILABILITY_LABELS,
  RESPONSE_LABELS,
  type OutlookEvent,
  type OutlookEventDetail,
} from "@/integrations/outlook_calendar/lib/events"
import { pluralize } from "@/lib/format"

function EventBadges({ event }: { event: OutlookEvent }) {
  const response = RESPONSE_LABELS[event.response]
  return (
    <>
      {event.cancelled ? <Badge variant="destructive">Cancelled</Badge> : null}
      {response ? <Badge variant="outline">{response}</Badge> : null}
      {event.showAs !== "busy" && AVAILABILITY_LABELS[event.showAs] ? (
        <Badge variant="secondary">Shows as {AVAILABILITY_LABELS[event.showAs]}</Badge>
      ) : null}
      {event.online ? (
        <Badge variant="outline">
          <VideoIcon />
          Online Meeting
        </Badge>
      ) : null}
      {event.private ? (
        <Badge variant="outline">
          <LockIcon />
          Private
        </Badge>
      ) : null}
    </>
  )
}

function calendarEventItem(event: OutlookEvent): CalendarEventItem {
  return {
    allDay: event.allDay,
    badges: <EventBadges event={event} />,
    end: event.end,
    key: event.eventId,
    location: event.location,
    start: event.start,
    timeZone: event.timeZone,
    title: event.subject,
  }
}

export function OutlookEventList({
  ariaLabel,
  events,
}: {
  ariaLabel: string
  events: OutlookEvent[]
}) {
  return (
    <CalendarEventList
      ariaLabel={ariaLabel}
      emptyLabel="No events in this time window."
      events={events.map(calendarEventItem)}
    />
  )
}

export function OutlookEventDetailView({ event }: { event: OutlookEventDetail }) {
  const item = calendarEventItem(event)
  return (
    <article className="grid min-w-0 gap-3">
      <header className="grid min-w-0 gap-1 border-b pb-3">
        <h3 className="text-sm font-medium wrap-break-word">{event.subject || "(No subject)"}</h3>
        <CalendarEventTime event={item} />
        <div className="mt-1 flex min-w-0 flex-wrap gap-1.5">
          <EventBadges event={event} />
        </div>
      </header>
      <DetailList
        items={[
          { label: "Organiser", value: event.organizer || "Unknown" },
          ...(event.location ? [{ label: "Location", value: event.location }] : []),
          ...(event.recurrence ? [{ label: "Repeats", value: event.recurrence }] : []),
          {
            label: `${String(event.attendeeCount)} ${pluralize(event.attendeeCount, "Attendee")}`,
            value:
              event.attendees
                .map((attendee) => {
                  const status = RESPONSE_LABELS[attendee.status]
                  const label = attendee.name || attendee.address
                  return status ? `${label} (${status})` : label
                })
                .join("\n") || "No attendees",
          },
        ]}
      />
      {event.body ? (
        <ExternalContent label="Event description" showSource={false} value={event.body} />
      ) : null}
      {event.truncated ? (
        <p className="text-muted-foreground text-xs">The description was shortened.</p>
      ) : null}
    </article>
  )
}
