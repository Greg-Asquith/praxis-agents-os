// apps/web/src/integrations/outlook_calendar/presenters/respond-to-event.tsx

import { compactDetails } from "@/integrations/tool-details"
import {
  outlookRespondArgs,
  type OutlookRespondArgs,
} from "@/integrations/outlook_calendar/lib/write-args"
import { defineOutlookCalendarWriteVariant } from "@/integrations/outlook_calendar/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

const RESPONSES = { accept: "Accept", decline: "Decline", tentative: "Tentative" }
const SENT = { accept: "Accepted", decline: "Declined", tentative: "Tentatively accepted" }

function respondDetails(args: OutlookRespondArgs | null) {
  if (!args) return []
  return compactDetails([
    { label: "Response", value: RESPONSES[args.response] },
    { label: "Organiser Told", value: args.sendResponse ? "Yes" : "No" },
    args.comment ? { label: "Comment", value: args.comment } : null,
  ])
}

export const outlookCalendarRespondPresenter = createIntegrationWritePresenter({
  variants: {
    outlook_calendar_respond_to_event: defineOutlookCalendarWriteVariant({
      approveLabel: "Approve & Respond",
      copy: {
        check: "Check the invitation in Outlook before trying again.",
        effect: "sent",
        object: "response",
        verb: "Respond",
      },
      details: respondDetails,
      parseArgs: outlookRespondArgs,
      prompt: "The organiser is told your response when Send Response is on.",
      view: (args) => ({
        note: args?.sendResponse === false ? "Only your calendar changed." : null,
        rows: respondDetails(args),
        subject: null,
        titles: {
          applied: args ? SENT[args.response] : "Response sent",
          failed: "Response not sent",
          unverified: "Response not confirmed",
        },
      }),
    }),
  },
})
