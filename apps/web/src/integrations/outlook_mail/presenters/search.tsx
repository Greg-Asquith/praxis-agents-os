// apps/web/src/integrations/outlook_mail/presenters/search.tsx

import { MessageList } from "@/components/tool-ui/message"
import { OutlookMessageRow } from "@/integrations/outlook_mail/components/message"
import { searchMessages } from "@/integrations/outlook_mail/lib/messages"
import { outlookSearchDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const outlookMailSearchPresenter = defineIntegrationReadPresenter(outlookMailProvider, {
  ariaLabel: "Search Outlook Mail results",
  details: outlookSearchDetails,
  emptyLabel: "No mailboxes were searched.",
  heading: "Search Outlook Mail",
  parseResult: searchMessages,
  progressLabel: "Searching mailboxes…",
  render: (messages, entry) => (
    <MessageList
      ariaLabel={`Messages in ${entry.displayName}`}
      emptyLabel="No matching messages found."
      items={messages}
      keyOf={(message) => message.messageId}
      renderItem={(message) => <OutlookMessageRow message={message} />}
    />
  ),
  tool: "outlook_mail_search_messages",
})
