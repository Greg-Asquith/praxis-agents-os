// apps/web/src/integrations/outlook_mail/presenters/search.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import type { ToolRowPresenter } from "@/integrations/contract"
import { OutlookFanOut, OutlookSkeleton } from "@/integrations/outlook_mail/components/fan-out"
import { OutlookMessageRow } from "@/integrations/outlook_mail/components/message"
import { searchMessages } from "@/integrations/outlook_mail/lib/messages"
import { outlookSearchDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { pluralize } from "@/lib/format"

const TITLE = "Search Outlook Mail"

export const outlookMailSearchPresenter: ToolRowPresenter = {
  key: "outlook-mail-search",
  matches: (activity) => activity.name === "outlook_mail_search_messages",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return <OutlookSkeleton label="Searching mailboxes…" title={TITLE} />
    }
    const result = parseFanOutData(activity.result, searchMessages)
    if (!result) {
      return null
    }
    return (
      <OutlookFanOut
        defaultOpen={defaultOpen}
        details={outlookSearchDetails(activity.args)}
        emptyLabel="No mailboxes were searched."
        entries={result.entries}
        title={TITLE}
      >
        {(entry, index) => {
          const messages = result.data[index]
          if (!messages) {
            return null
          }
          return messages.length > 0 ? (
            <div className="grid min-w-0 gap-2">
              <p className="text-muted-foreground text-xs">
                {String(messages.length)} {pluralize(messages.length, "Message")}
              </p>
              <div
                aria-label={`Messages in ${entry.displayName}`}
                className="grid max-h-[min(32rem,60vh)] min-w-0 gap-2 overflow-y-auto overscroll-contain pr-1"
                role="list"
              >
                {messages.map((message) => (
                  <div className="min-w-0" key={message.messageId} role="listitem">
                    <OutlookMessageRow message={message} />
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
      </OutlookFanOut>
    )
  },
}
