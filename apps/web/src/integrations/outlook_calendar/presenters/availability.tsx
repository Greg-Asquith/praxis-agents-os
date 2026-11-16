// apps/web/src/integrations/outlook_calendar/presenters/availability.tsx

import { PersonSchedule } from "@/integrations/outlook_calendar/components/schedule"
import { parseAvailability } from "@/integrations/outlook_calendar/lib/events"
import { availabilityDetails } from "@/integrations/outlook_calendar/lib/tool-details"
import { outlookCalendarProvider } from "@/integrations/outlook_calendar/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const outlookCalendarAvailabilityPresenter = defineIntegrationReadPresenter(
  outlookCalendarProvider,
  {
    ariaLabel: "Check Outlook Availability results",
    details: availabilityDetails,
    emptyLabel: "No calendars were checked.",
    heading: "Check Outlook Availability",
    parseResult: parseAvailability,
    progressLabel: "Checking availability…",
    render: (result) => (
      <div className="grid min-w-0 gap-4">
        {result.schedules.map((schedule) => (
          <PersonSchedule key={schedule.address} schedule={schedule} timeZone={result.timeZone} />
        ))}
      </div>
    ),
    tool: "outlook_calendar_get_availability",
  }
)
