// apps/web/src/integrations/outlook_calendar/presenters/events.tsx

import {
  OutlookEventDetailView,
  OutlookEventList,
} from "@/integrations/outlook_calendar/components/event"
import { parseEventDetail, parseEvents } from "@/integrations/outlook_calendar/lib/events"
import { listEventsDetails } from "@/integrations/outlook_calendar/lib/tool-details"
import { outlookCalendarProvider } from "@/integrations/outlook_calendar/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const outlookCalendarListEventsPresenter = defineIntegrationReadPresenter(
  outlookCalendarProvider,
  {
    ariaLabel: "List Outlook Events results",
    details: listEventsDetails,
    emptyLabel: "No calendars were checked.",
    heading: "List Outlook Events",
    parseResult: parseEvents,
    progressLabel: "Listing events…",
    render: (result, entry) => (
      <OutlookEventList ariaLabel={`Events in ${entry.displayName}`} events={result.events} />
    ),
    tool: "outlook_calendar_list_events",
  }
)

export const outlookCalendarReadEventPresenter = defineIntegrationReadPresenter(
  outlookCalendarProvider,
  {
    ariaLabel: "Read Outlook Event results",
    emptyLabel: "No calendar returned this event.",
    heading: "Read Outlook Event",
    parseResult: parseEventDetail,
    progressLabel: "Reading event…",
    render: (event) => <OutlookEventDetailView event={event} />,
    tool: "outlook_calendar_read_event",
  }
)
