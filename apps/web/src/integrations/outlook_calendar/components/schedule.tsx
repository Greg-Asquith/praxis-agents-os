// apps/web/src/integrations/outlook_calendar/components/schedule.tsx

import { CalendarSlotList } from "@/components/tool-ui/calendar/calendar-slot-list"
import { Badge } from "@/components/ui/badge"
import {
  AVAILABILITY_LABELS,
  type OutlookSchedule,
} from "@/integrations/outlook_calendar/lib/events"

export function PersonSchedule({
  schedule,
  timeZone,
}: {
  schedule: OutlookSchedule
  timeZone: string
}) {
  return (
    <section aria-label={schedule.address} className="grid min-w-0 gap-2">
      <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-medium wrap-break-word">{schedule.address}</h4>
        {schedule.workingHours ? (
          <p className="text-muted-foreground text-xs">Works {schedule.workingHours}</p>
        ) : null}
      </div>
      {schedule.available ? (
        <CalendarSlotList
          ariaLabel={`Busy times for ${schedule.address}`}
          emptyLabel="Free for the whole time window."
          slots={schedule.busyPeriods.map((period, index) => ({
            badge: (
              <Badge
                variant={
                  period.status === "busy" || period.status === "oof" ? "warning" : "secondary"
                }
              >
                {AVAILABILITY_LABELS[period.status] ?? "Busy"}
              </Badge>
            ),
            end: period.end,
            key: `${period.start}-${String(index)}`,
            start: period.start,
            timeZone,
          }))}
        />
      ) : (
        <p className="text-muted-foreground text-sm">
          Outlook couldn't share this person's availability.
        </p>
      )}
    </section>
  )
}
