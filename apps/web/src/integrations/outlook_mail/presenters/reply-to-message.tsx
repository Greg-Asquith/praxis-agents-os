// apps/web/src/integrations/outlook_mail/presenters/reply-to-message.tsx

import { MAIL_OUTCOME_ICONS } from "@/components/tool-ui/message-outcome-icons"
import { outlookReplyDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { outlookReplyArgs } from "@/integrations/outlook_mail/lib/write-args"
import { defineOutlookWriteVariant } from "@/integrations/outlook_mail/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

export const outlookMailReplyPresenter = createIntegrationWritePresenter({
  variants: {
    outlook_mail_reply_to_message: defineOutlookWriteVariant({
      copy: {
        check: "Check Sent Items and Drafts in Outlook before trying again.",
        effect: "sent",
        object: "reply",
        verb: "Send",
      },
      details: outlookReplyDetails,
      parseArgs: outlookReplyArgs,
      prompt: "Your reply is sent above the quoted conversation.",
      view: (args) => ({
        body: args?.body ?? null,
        icons: MAIL_OUTCOME_ICONS,
        linkLabel: (outcome) =>
          outcome === "failed" ? "Open draft in Outlook" : "Open in Outlook",
        note: "Outlook accepted the reply for sending.",
        rows: outlookReplyDetails(args),
        subject: null,
        titles: {
          applied: "Reply sent",
          failed: "Reply not sent",
          unverified: "Reply not confirmed",
        },
      }),
    }),
  },
})
