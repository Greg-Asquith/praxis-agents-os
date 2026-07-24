// apps/web/src/integrations/gmail/search-presenter.tsx

import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { ToolRowPresenter } from "@/integrations/contract"
import {
  GmailSearchMessageRow,
  type GmailMessageSummary,
} from "@/integrations/gmail/search-message-row"
import { gmailSearchDetails } from "@/integrations/gmail/tool-details"
import { GmailToolHeading } from "@/integrations/gmail/tool-heading"
import { pluralize } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const gmailSearchPresenter: ToolRowPresenter = {
  key: "gmail-search-messages",
  matches: (activity) => activity.name === "gmail_search_messages",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GmailToolHeading>Search Gmail</GmailToolHeading>}
          label="Searching mailboxes…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, searchMessages)
    if (!fanOut) {
      return null
    }
    const { data: messagesByEntry, entries } = fanOut
    return (
      <div aria-label="Gmail search results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Mailbox"
          defaultOpen={defaultOpen}
          details={gmailSearchDetails(activity.args)}
          entries={entries}
          emptyLabel="No mailboxes were searched."
          externalLabel="Email"
          heading={<GmailToolHeading>Search Gmail</GmailToolHeading>}
        >
          {(entry, index) => {
            const entryMessages = messagesByEntry[index]
            if (!entryMessages) {
              return null
            }
            return entryMessages.length > 0 ? (
              <div className="grid min-w-0 gap-2">
                <p className="text-muted-foreground text-xs">
                  {String(entryMessages.length)} {pluralize(entryMessages.length, "Message")}
                </p>
                <div
                  aria-label={`Messages in ${entry.displayName}`}
                  className="grid max-h-[min(32rem,60vh)] min-w-0 gap-2 overflow-y-auto overscroll-contain pr-1"
                  role="list"
                >
                  {entryMessages.map((message) => (
                    <div className="min-w-0" key={message.messageId} role="listitem">
                      <GmailSearchMessageRow connectionId={entry.connectionId} message={message} />
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground py-3 text-center text-sm">
                No matching messages found.
              </p>
            )
          }}
        </FanOutShell>
      </div>
    )
  },
}

function searchMessages(value: unknown): GmailMessageSummary[] | null {
  if (!isRecord(value) || !Array.isArray(value["messages"]) || typeof value["total"] !== "number") {
    return null
  }
  const messages: GmailMessageSummary[] = []
  for (const item of value["messages"]) {
    if (!isRecord(item) || typeof item["message_id"] !== "string") {
      return null
    }
    const sender = nodeText(item["sender"])
    const subject = nodeText(item["subject"])
    const date = nodeText(item["date"])
    const snippet = nodeText(item["snippet"])
    if (sender === null || subject === null || date === null || snippet === null) {
      return null
    }
    messages.push({
      date,
      messageId: item["message_id"],
      sender,
      snippet,
      subject,
    })
  }
  return messages
}
