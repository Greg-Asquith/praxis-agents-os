// apps/web/src/integrations/outlook_mail/presenters/reply-to-message.tsx

import { outlookReplyDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { outlookReplyArgs } from "@/integrations/outlook_mail/lib/write-args"
import {
  createOutlookWritePresenter,
  defineOutlookWriteVariant,
  MAIL_ICONS,
} from "@/integrations/outlook_mail/presenters/write-presenter"

export const outlookMailReplyPresenter = createOutlookWritePresenter({
  key: "outlook-mail-reply-to-message",
  variants: {
    outlook_mail_reply_to_message: defineOutlookWriteVariant({
      copy: {
        approveLabel: "Approve & Send",
        check: "Sent Items and Drafts",
        effect: "sent",
        heading: "Reply in Outlook",
        object: "reply",
        prompt: "Your reply is sent above the quoted conversation.",
        title: "Review reply before sending",
        verb: "send",
      },
      details: outlookReplyDetails,
      parseArgs: outlookReplyArgs,
      view: (args) => ({
        body: args?.body ?? null,
        icons: MAIL_ICONS,
        linkLabel: (outcome) =>
          outcome === "applied" ? "Open in Outlook" : "Open draft in Outlook",
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
