// apps/web/src/integrations/outlook_mail/presenters/move-message.tsx

import { FolderInputIcon } from "lucide-react"

import { sameOutcomeIcon } from "@/components/tool-ui/message-outcome-icons"
import { outlookMoveDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { outlookMoveArgs } from "@/integrations/outlook_mail/lib/write-args"
import { defineOutlookWriteVariant } from "@/integrations/outlook_mail/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

export const outlookMailMovePresenter = createIntegrationWritePresenter({
  variants: {
    outlook_mail_move_message: defineOutlookWriteVariant({
      copy: {
        check: "Check the destination folder in Outlook before trying again.",
        effect: "moved",
        object: "message",
        verb: "Move",
      },
      details: outlookMoveDetails,
      parseArgs: outlookMoveArgs,
      prompt: "The agent wants to move this message to the selected folder.",
      view: (args) => ({
        body: null,
        icons: sameOutcomeIcon(FolderInputIcon),
        linkLabel: () => "Open in Outlook",
        note: null,
        rows: outlookMoveDetails(args),
        subject: null,
        titles: {
          applied: "Message moved",
          failed: "Message not moved",
          unverified: "Move not confirmed",
        },
      }),
    }),
  },
})
