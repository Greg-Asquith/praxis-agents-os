// apps/web/src/integrations/outlook_mail/presenters/forward-message.tsx

import { outlookForwardDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { outlookForwardArgs } from "@/integrations/outlook_mail/lib/write-args"
import {
  createOutlookWritePresenter,
  defineOutlookWriteVariant,
  MAIL_ICONS,
} from "@/integrations/outlook_mail/presenters/write-presenter"

export const outlookMailForwardPresenter = createOutlookWritePresenter({
  key: "outlook-mail-forward-message",
  variants: {
    outlook_mail_forward_message: defineOutlookWriteVariant({
      copy: {
        approveLabel: "Approve & Forward",
        check: "Sent Items and Drafts",
        effect: "forwarded",
        heading: "Forward Outlook Email",
        object: "email",
        prompt: "Your message is sent above the quoted conversation.",
        title: "Review email before forwarding",
        verb: "forward",
      },
      details: outlookForwardDetails,
      parseArgs: outlookForwardArgs,
      view: (args) => ({
        body: args?.body ?? null,
        icons: MAIL_ICONS,
        linkLabel: (outcome) =>
          outcome === "applied" ? "Open in Outlook" : "Open draft in Outlook",
        note: "Outlook accepted the forwarded email for sending.",
        rows: outlookForwardDetails(args),
        subject: null,
        titles: {
          applied: "Email forwarded",
          failed: "Email not forwarded",
          unverified: "Forward not confirmed",
        },
      }),
    }),
  },
})
