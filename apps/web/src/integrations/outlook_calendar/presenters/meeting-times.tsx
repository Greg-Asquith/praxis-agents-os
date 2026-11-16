// apps/web/src/integrations/outlook_calendar/presenters/meeting-times.tsx

import { CalendarSlotList } from "@/components/tool-ui/calendar/calendar-slot-list"
import { Badge } from "@/components/ui/badge"
import {
  AVAILABILITY_LABELS,
  parseMeetingTimes,
  type OutlookSuggestion,
} from "@/integrations/outlook_calendar/lib/events"
import { meetingTimesDetails } from "@/integrations/outlook_calendar/lib/tool-details"
import { outlookCalendarProvider } from "@/integrations/outlook_calendar/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

const EMPTY_REASONS: Record<string, string> = {
  attendeesUnavailable: "No time works for every attendee.",
  attendeesUnavailableOrUnknown: "No time works for every attendee, or their calendars are hidden.",
  organizerUnavailable: "You're busy at every possible time.",
}

function attendeeSummary(suggestion: OutlookSuggestion): string {
  const unavailable = suggestion.attendees.filter((attendee) => attendee.availability !== "free")
  if (unavailable.length === 0) return "Every attendee is free."
  return unavailable
    .map(
      (attendee) =>
        `${attendee.address}: ${AVAILABILITY_LABELS[attendee.availability] ?? "Unknown"}`
    )
    .join(", ")
}

export const outlookCalendarMeetingTimesPresenter = defineIntegrationReadPresenter(
  outlookCalendarProvider,
  {
    ariaLabel: "Find Outlook Meeting Times results",
    details: meetingTimesDetails,
    emptyLabel: "No calendars were checked.",
    heading: "Find Outlook Meeting Times",
    parseResult: parseMeetingTimes,
    progressLabel: "Finding meeting times…",
    render: (result) => (
      <CalendarSlotList
        ariaLabel="Suggested meeting times"
        emptyLabel={
          (result.emptyReason ? EMPTY_REASONS[result.emptyReason] : undefined) ??
          "Outlook didn't suggest any times in this window."
        }
        slots={result.suggestions.map((suggestion) => ({
          badge:
            suggestion.confidence === null ? undefined : (
              <Badge variant={suggestion.confidence >= 100 ? "success" : "secondary"}>
                {String(Math.round(suggestion.confidence))}% Likely
              </Badge>
            ),
          detail: attendeeSummary(suggestion),
          end: suggestion.end,
          key: suggestion.start,
          start: suggestion.start,
          timeZone: result.timeZone,
        }))}
      />
    ),
    tool: "outlook_calendar_find_meeting_times",
  }
)
