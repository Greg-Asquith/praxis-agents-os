// apps/web/src/integrations/gmail/read-presenter.tsx

import { ExternalContent } from "@/components/tool-ui/external-content"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { MessageDetail } from "@/components/tool-ui/message"
import { isUntrustedNode, nodeText, type UntrustedNode } from "@/components/tool-ui/untrusted-node"
import type { ToolRowPresenter } from "@/integrations/contract"
import { GmailMessageView } from "@/integrations/gmail/message-preview"
import { GmailToolHeading } from "@/integrations/gmail/tool-heading"
import { relativeDateTime } from "@/lib/format"
import { isRecord } from "@/lib/guards"

type GmailMessage = {
  body: string | UntrustedNode
  date: string
  messageId: string
  sender: string
  subject: string
  to: string
  truncated: boolean
}

export const gmailReadPresenter: ToolRowPresenter = {
  key: "gmail-read-message",
  matches: (activity) => activity.name === "gmail_read_message",
  render: ({ activity }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GmailToolHeading>Read Gmail Message</GmailToolHeading>}
          label="Reading message…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, readMessage)
    if (!fanOut) {
      return null
    }
    const { data: messagesByEntry, entries } = fanOut
    return (
      <div aria-label="Gmail message" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Mailbox"
          entries={entries}
          emptyLabel="No mailbox returned this message."
          externalLabel="Email"
          heading={<GmailToolHeading>Read Gmail Message</GmailToolHeading>}
        >
          {(entry, index) => {
            const message = messagesByEntry[index]
            if (!message) {
              return null
            }
            const plainBody = (
              <div className="grid gap-2">
                <ExternalContent label="Email body" showSource={false} value={message.body} />
                {message.truncated ? (
                  <p className="text-warning-foreground bg-warning/10 rounded-md px-2.5 py-2 text-xs">
                    This message was shortened to fit the tool result limit.
                  </p>
                ) : null}
              </div>
            )
            return (
              <MessageDetail
                body={
                  <GmailMessageView
                    connectionId={entry.connectionId}
                    fallback={plainBody}
                    messageId={message.messageId}
                  />
                }
                date={relativeDateTime(message.date)}
                from={message.sender}
                subject={message.subject}
                to={message.to}
              />
            )
          }}
        </FanOutShell>
      </div>
    )
  },
}

function readMessage(value: unknown): GmailMessage | null {
  if (
    !isRecord(value) ||
    typeof value["message_id"] !== "string" ||
    typeof value["truncated"] !== "boolean"
  ) {
    return null
  }
  const sender = nodeText(value["sender"])
  const subject = nodeText(value["subject"])
  const to = nodeText(value["to"])
  const date = nodeText(value["date"])
  const body = value["body"]
  if (
    sender === null ||
    subject === null ||
    to === null ||
    date === null ||
    (typeof body !== "string" && !isUntrustedNode(body))
  ) {
    return null
  }
  return {
    body,
    date,
    messageId: value["message_id"],
    sender,
    subject,
    to,
    truncated: value["truncated"],
  }
}
