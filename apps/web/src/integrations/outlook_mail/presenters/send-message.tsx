// apps/web/src/integrations/outlook_mail/presenters/send-message.tsx

import { MAIL_OUTCOME_ICONS } from "@/components/tool-ui/message-outcome-icons"
import {
  outlookRecipientRows,
  outlookSendDetails,
} from "@/integrations/outlook_mail/lib/tool-details"
import { outlookSendArgs } from "@/integrations/outlook_mail/lib/write-args"
import { defineOutlookWriteVariant } from "@/integrations/outlook_mail/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

export const outlookMailSendPresenter = createIntegrationWritePresenter({
  variants: {
    outlook_mail_send_message: defineOutlookWriteVariant({
      copy: {
        check: "Check Sent Items and Drafts in Outlook before trying again.",
        effect: "sent",
        object: "email",
        verb: "Send",
      },
      details: outlookSendDetails,
      parseArgs: outlookSendArgs,
      prompt: "The agent wants to send this email from the selected mailbox.",
      view: (args) => ({
        body: args?.body ?? null,
        icons: MAIL_OUTCOME_ICONS,
        linkLabel: (outcome) =>
          outcome === "failed" ? "Open draft in Outlook" : "Open in Outlook",
        note: "Outlook accepted the email for sending.",
        rows: args ? outlookRecipientRows(args) : [],
        subject: args?.subject ?? null,
        titles: {
          applied: "Email sent",
          failed: "Email not sent",
          unverified: "Send not confirmed",
        },
      }),
    }),
  },
})
