// apps/web/src/integrations/outlook_mail/presenters/read.tsx

import { OutlookMessageBody } from "@/integrations/outlook_mail/components/message"
import { readMessage } from "@/integrations/outlook_mail/lib/messages"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const outlookMailReadPresenter = defineIntegrationReadPresenter(outlookMailProvider, {
  ariaLabel: "Read Outlook Message results",
  emptyLabel: "No mailbox returned this message.",
  heading: "Read Outlook Message",
  parseResult: readMessage,
  progressLabel: "Reading message…",
  render: (message) => <OutlookMessageBody message={message} />,
  tool: "outlook_mail_read_message",
})
