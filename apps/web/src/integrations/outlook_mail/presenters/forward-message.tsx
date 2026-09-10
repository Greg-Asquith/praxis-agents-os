// apps/web/src/integrations/outlook_mail/presenters/forward-message.tsx

import { MAIL_OUTCOME_ICONS } from "@/components/tool-ui/message-outcome-icons"
import { outlookForwardDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { outlookForwardArgs } from "@/integrations/outlook_mail/lib/write-args"
import { defineOutlookWriteVariant } from "@/integrations/outlook_mail/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

export const outlookMailForwardPresenter = createIntegrationWritePresenter({
  variants: {
    outlook_mail_forward_message: defineOutlookWriteVariant({
      copy: {
        check: "Check Sent Items and Drafts in Outlook before trying again.",
        effect: "forwarded",
        object: "email",
        verb: "Forward",
      },
      details: outlookForwardDetails,
      parseArgs: outlookForwardArgs,
      prompt: "Your message is sent above the quoted conversation.",
      view: (args) => ({
        body: args?.body ?? null,
        icons: MAIL_OUTCOME_ICONS,
        linkLabel: (outcome) =>
          outcome === "failed" ? "Open draft in Outlook" : "Open in Outlook",
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
