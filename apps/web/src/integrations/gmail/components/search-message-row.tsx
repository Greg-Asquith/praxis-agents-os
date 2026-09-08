// apps/web/src/integrations/gmail/components/search-message-row.tsx

import { use } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { MessageDetailSkeleton, MessagePreviewRow } from "@/components/tool-ui/message"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { GmailMessageView } from "@/integrations/gmail/components/message-preview"
import { gmailSearchMessageSelectHandler } from "@/integrations/gmail/lib/search-interaction"
import { relativeDateTime } from "@/lib/format"

export type GmailMessageSummary = {
  date: string
  messageId: string
  sender: string
  snippet: string
  subject: string
}

export function GmailSearchMessageRow({
  mailboxId,
  message,
}: {
  mailboxId: string
  message: GmailMessageSummary
}) {
  const queryClient = useQueryClient()
  const conversationId = use(ToolConversationContext)
  const prefetchMessage = gmailSearchMessageSelectHandler({
    conversationId,
    mailboxId,
    messageId: message.messageId,
    queryClient,
  })

  return (
    <MessagePreviewRow
      date={relativeDateTime(message.date)}
      onOpen={prefetchMessage}
      sender={message.sender}
      snippet={message.snippet}
      subject={message.subject}
    >
      <GmailMessageView
        mailboxId={mailboxId}
        errorFallback={
          <p className="text-destructive py-4 text-center text-sm">
            This message preview could not be loaded.
          </p>
        }
        fallback={<MessageDetailSkeleton label="Loading full message…" />}
        messageId={message.messageId}
      />
    </MessagePreviewRow>
  )
}
