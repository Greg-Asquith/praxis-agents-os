// apps/web/src/integrations/outlook_calendar/presenters/cancel-event.tsx

import { compactDetails } from "@/integrations/tool-details"
import {
  outlookCancelArgs,
  type OutlookCancelArgs,
} from "@/integrations/outlook_calendar/lib/write-args"
import { defineOutlookCalendarWriteVariant } from "@/integrations/outlook_calendar/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

function cancelDetails(args: OutlookCancelArgs | null) {
  if (!args) return []
  return compactDetails([args.comment ? { label: "Message", value: args.comment } : null])
}

export const outlookCalendarCancelPresenter = createIntegrationWritePresenter({
  variants: {
    outlook_calendar_cancel_event: defineOutlookCalendarWriteVariant({
      approveLabel: "Approve & Cancel",
      copy: {
        check: "Check the event in Outlook before trying again.",
        destructive: true,
        effect: "cancelled",
        object: "event",
        verb: "Cancel",
      },
      details: cancelDetails,
      parseArgs: outlookCancelArgs,
      prompt:
        "Attendees receive a cancellation when you approve. An event with no attendees is deleted.",
      view: (_args, result) => ({
        note:
          result.action === "deleted"
            ? "The event had no attendees, so it was deleted."
            : "Attendees were sent the cancellation.",
        rows: cancelDetails(_args),
        subject: null,
        titles: {
          applied: result.action === "deleted" ? "Event deleted" : "Event cancelled",
          failed: "Event not cancelled",
          unverified: "Cancellation not confirmed",
        },
      }),
    }),
  },
})
