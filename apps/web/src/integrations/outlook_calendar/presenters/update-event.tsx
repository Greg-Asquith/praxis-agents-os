// apps/web/src/integrations/outlook_calendar/presenters/update-event.tsx

import { eventWriteRows } from "@/integrations/outlook_calendar/lib/tool-details"
import {
  outlookUpdateEventArgs,
  validateOutlookUpdateEventArgs,
} from "@/integrations/outlook_calendar/lib/write-args"
import { defineOutlookCalendarWriteVariant } from "@/integrations/outlook_calendar/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

export const outlookCalendarUpdateEventPresenter = createIntegrationWritePresenter({
  variants: {
    outlook_calendar_update_event: defineOutlookCalendarWriteVariant({
      approveLabel: "Approve & Send",
      copy: {
        check: "Check the event in Outlook before trying again.",
        effect: "updated",
        object: "event",
        verb: "Update",
      },
      details: eventWriteRows,
      parseArgs: outlookUpdateEventArgs,
      prompt: "Attendees receive an update when you approve.",
      validateArgs: validateOutlookUpdateEventArgs,
      view: (args) => ({
        note: "Any attendees were sent the update.",
        rows: eventWriteRows(args),
        subject: args?.title ?? null,
        titles: {
          applied: "Event updated",
          failed: "Event not updated",
          unverified: "Update not confirmed",
        },
      }),
    }),
  },
})
