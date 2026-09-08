// apps/web/src/integrations/outlook_mail/presenters/send-message.tsx

import {
  outlookRecipientRows,
  outlookSendDetails,
} from "@/integrations/outlook_mail/lib/tool-details"
import { outlookSendArgs } from "@/integrations/outlook_mail/lib/write-args"
import {
  createOutlookWritePresenter,
  defineOutlookWriteVariant,
  MAIL_ICONS,
} from "@/integrations/outlook_mail/presenters/write-presenter"

export const outlookMailSendPresenter = createOutlookWritePresenter({
  key: "outlook-mail-send-message",
  variants: {
    outlook_mail_send_message: defineOutlookWriteVariant({
      copy: {
        approveLabel: "Approve & Send",
        check: "Sent Items and Drafts",
        effect: "sent",
        heading: "Send Outlook Email",
        object: "email",
        prompt: "The agent wants to send this email from the selected mailbox.",
        title: "Review email before sending",
        verb: "send",
      },
      details: outlookSendDetails,
      parseArgs: outlookSendArgs,
      view: (args) => ({
        body: args?.body ?? null,
        icons: MAIL_ICONS,
        linkLabel: (outcome) =>
          outcome === "applied" ? "Open in Outlook" : "Open draft in Outlook",
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
