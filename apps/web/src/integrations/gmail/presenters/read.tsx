// apps/web/src/integrations/gmail/presenters/read.tsx

import { GmailMessageBody } from "@/integrations/gmail/components/message"
import { parseGmailMessage } from "@/integrations/gmail/lib/messages"
import { gmailProvider } from "@/integrations/gmail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const gmailReadPresenter = defineIntegrationReadPresenter(gmailProvider, {
  ariaLabel: "Gmail message",
  emptyLabel: "No mailbox returned this message.",
  heading: "Read Gmail Message",
  parseResult: parseGmailMessage,
  progressLabel: "Reading message…",
  render: (message, entry) => <GmailMessageBody mailboxId={entry.externalId} message={message} />,
  tool: "gmail_read_message",
})
