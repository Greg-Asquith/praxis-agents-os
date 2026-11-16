// apps/web/src/integrations/outlook_calendar/presenters/create-event.tsx

import {
  CalendarEventOptions,
  type CalendarEventOptionKey,
} from "@/components/tool-ui/calendar/calendar-event-options"
import { AVAILABILITY_LABELS } from "@/integrations/outlook_calendar/lib/events"
import { isRecord } from "@/lib/guards"
import { eventWriteRows } from "@/integrations/outlook_calendar/lib/tool-details"
import {
  outlookCreateEventArgs,
  validateOutlookCreateEventArgs,
} from "@/integrations/outlook_calendar/lib/write-args"
import { defineOutlookCalendarWriteVariant } from "@/integrations/outlook_calendar/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

// The options line replaces these fields, and the picker goes when there is one calendar.
const OPTION_KEYS: Record<CalendarEventOptionKey, string> = {
  allDay: "is_all_day",
  online: "is_online_meeting",
  showAs: "show_as",
}
const SHOW_AS = ["free", "tentative", "busy", "oof", "workingElsewhere"].map((value) => ({
  label: AVAILABILITY_LABELS[value] ?? value,
  value,
}))
const HIDDEN = new Set(Object.values(OPTION_KEYS))

export const outlookCalendarCreateEventPresenter = createIntegrationWritePresenter({
  variants: {
    outlook_calendar_create_event: defineOutlookCalendarWriteVariant({
      approveLabel: "Approve & Send",
      copy: {
        check: "Check the calendar in Outlook before trying again.",
        effect: "created",
        object: "event",
        verb: "Create",
      },
      details: eventWriteRows,
      parseArgs: outlookCreateEventArgs,
      prompt: "Invitations are sent to every attendee when you approve.",
      renderSummary: (value, fallback, onFieldEdit, disabled, controls) => {
        const args = outlookCreateEventArgs(value) ?? fallback
        return (
          <CalendarEventOptions
            allDay={args.allDay}
            disabled={disabled || controls.decision.decision !== "pending"}
            id="outlook-calendar-create"
            online={args.online}
            onChange={(key, next) => {
              onFieldEdit(OPTION_KEYS[key], next)
            }}
            showAs={args.showAs}
            showAsOptions={SHOW_AS}
          />
        )
      },
      validateArgs: validateOutlookCreateEventArgs,
      visibleFields: (fields, args) => {
        const single = isRecord(args) && args["_calendar_choice"] === false
        return fields.filter(
          (field) => !HIDDEN.has(field.key) && !(single && field.key === "calendar")
        )
      },
      view: (args, result) => ({
        note:
          [
            args?.attendees.length ? "Invitations were sent to every attendee." : null,
            result.joinUrl ? "The event has a Teams meeting link." : null,
          ]
            .filter(Boolean)
            .join(" ") || null,
        rows: eventWriteRows(args),
        subject: args?.title ?? null,
        titles: {
          applied: "Event created",
          failed: "Event not created",
          unverified: "Event not confirmed",
        },
      }),
    }),
  },
})
