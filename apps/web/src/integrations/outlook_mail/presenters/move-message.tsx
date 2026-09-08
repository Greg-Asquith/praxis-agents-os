// apps/web/src/integrations/outlook_mail/presenters/move-message.tsx

import { FolderInputIcon } from "lucide-react"

import { outlookMoveDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { outlookMoveArgs } from "@/integrations/outlook_mail/lib/write-args"
import {
  createOutlookWritePresenter,
  defineOutlookWriteVariant,
  outcomeIcons,
} from "@/integrations/outlook_mail/presenters/write-presenter"

export const outlookMailMovePresenter = createOutlookWritePresenter({
  key: "outlook-mail-move-message",
  variants: {
    outlook_mail_move_message: defineOutlookWriteVariant({
      copy: {
        approveLabel: "Approve & Move",
        check: "the destination folder",
        effect: "moved",
        heading: "Move Outlook Message",
        object: "message",
        prompt: "The agent wants to move this message to the selected folder.",
        title: "Review message move",
        verb: "move",
      },
      details: outlookMoveDetails,
      parseArgs: outlookMoveArgs,
      view: (args) => ({
        body: null,
        icons: outcomeIcons(FolderInputIcon),
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
