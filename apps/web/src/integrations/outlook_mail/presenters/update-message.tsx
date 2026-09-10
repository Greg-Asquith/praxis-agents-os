// apps/web/src/integrations/outlook_mail/presenters/update-message.tsx

import { PencilLineIcon } from "lucide-react"

import { sameOutcomeIcon } from "@/components/tool-ui/message-outcome-icons"
import { outlookUpdateDetails } from "@/integrations/outlook_mail/lib/tool-details"
import {
  outlookUpdateArgs,
  validateOutlookUpdateArgs,
} from "@/integrations/outlook_mail/lib/write-args"
import { defineOutlookWriteVariant } from "@/integrations/outlook_mail/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

export const outlookMailUpdatePresenter = createIntegrationWritePresenter({
  variants: {
    outlook_mail_update_message: defineOutlookWriteVariant({
      copy: {
        check: "Check the message in Outlook before trying again.",
        effect: "updated",
        object: "message",
        verb: "Update",
      },
      details: outlookUpdateDetails,
      parseArgs: outlookUpdateArgs,
      prompt: "The agent wants to change the read or flag state of this message.",
      validateArgs: validateOutlookUpdateArgs,
      view: (args) => ({
        body: null,
        icons: sameOutcomeIcon(PencilLineIcon),
        linkLabel: () => "Open in Outlook",
        note: null,
        rows: outlookUpdateDetails(args),
        subject: null,
        titles: {
          applied: "Message updated",
          failed: "Message not updated",
          unverified: "Update not confirmed",
        },
      }),
    }),
  },
})
