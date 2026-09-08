// apps/web/src/integrations/outlook_mail/presenters/read.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import type { ToolRowPresenter } from "@/integrations/contract"
import { OutlookFanOut, OutlookSkeleton } from "@/integrations/outlook_mail/components/fan-out"
import { OutlookMessageBody } from "@/integrations/outlook_mail/components/message"
import { readMessage } from "@/integrations/outlook_mail/lib/messages"

const TITLE = "Read Outlook Message"

export const outlookMailReadPresenter: ToolRowPresenter = {
  key: "outlook-mail-read",
  matches: (activity) => activity.name === "outlook_mail_read_message",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return <OutlookSkeleton label="Reading message…" title={TITLE} />
    }
    const result = parseFanOutData(activity.result, readMessage)
    if (!result) {
      return null
    }
    return (
      <OutlookFanOut
        defaultOpen={defaultOpen}
        emptyLabel="No mailbox returned this message."
        entries={result.entries}
        title={TITLE}
      >
        {(_entry, index) => {
          const message = result.data[index]
          return message ? <OutlookMessageBody message={message} /> : null
        }}
      </OutlookFanOut>
    )
  },
}
