// apps/web/src/integrations/outlook_mail/presenters/update-message.tsx

import { PencilLineIcon } from "lucide-react"

import { outlookUpdateDetails } from "@/integrations/outlook_mail/lib/tool-details"
import {
  outlookUpdateArgs,
  validateOutlookUpdateArgs,
} from "@/integrations/outlook_mail/lib/write-args"
import {
  createOutlookWritePresenter,
  defineOutlookWriteVariant,
  outcomeIcons,
} from "@/integrations/outlook_mail/presenters/write-presenter"

export const outlookMailUpdatePresenter = createOutlookWritePresenter({
  key: "outlook-mail-update-message",
  variants: {
    outlook_mail_update_message: defineOutlookWriteVariant({
      copy: {
        approveLabel: "Approve & Update",
        check: "the message",
        effect: "updated",
        heading: "Update Outlook Message",
        object: "message",
        prompt: "The agent wants to change the read or flag state of this message.",
        title: "Review message update",
        verb: "update",
      },
      details: outlookUpdateDetails,
      parseArgs: outlookUpdateArgs,
      validateArgs: validateOutlookUpdateArgs,
      view: (args) => ({
        body: null,
        icons: outcomeIcons(PencilLineIcon),
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
