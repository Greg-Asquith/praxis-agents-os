// apps/web/src/integrations/gmail/presenters/search.tsx

import { MessageList } from "@/components/tool-ui/message"
import { GmailMessageRow } from "@/integrations/gmail/components/message"
import { parseGmailSearchResult } from "@/integrations/gmail/lib/messages"
import { gmailSearchDetails } from "@/integrations/gmail/lib/tool-details"
import { gmailProvider } from "@/integrations/gmail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const gmailSearchPresenter = defineIntegrationReadPresenter(gmailProvider, {
  ariaLabel: "Gmail search results",
  details: gmailSearchDetails,
  emptyLabel: "No mailboxes were searched.",
  heading: "Search Gmail",
  parseResult: parseGmailSearchResult,
  progressLabel: "Searching mailboxes…",
  render: (messages, entry) => (
    <MessageList
      ariaLabel={`Messages in ${entry.displayName}`}
      emptyLabel="No matching messages found."
      items={messages}
      keyOf={(message) => message.messageId}
      renderItem={(message) => <GmailMessageRow mailboxId={entry.externalId} message={message} />}
    />
  ),
  tool: "gmail_search_messages",
})
