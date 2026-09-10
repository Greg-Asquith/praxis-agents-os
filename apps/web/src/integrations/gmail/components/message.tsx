// apps/web/src/integrations/gmail/components/message.tsx

import { use } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { ExternalContent } from "@/components/tool-ui/external-content"
import {
  MessageDetail,
  MessageDetailSkeleton,
  MessagePreviewRow,
} from "@/components/tool-ui/message"
import { prefetchProviderPreview } from "@/components/tool-ui/provider-preview-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api/message-preview"
import { GmailMessageView } from "@/integrations/gmail/components/message-preview"
import type { GmailMessage, GmailMessageSummary } from "@/integrations/gmail/lib/messages"
import { relativeDateTime } from "@/lib/format"

export function GmailMessageRow({
  mailboxId,
  message,
}: {
  mailboxId: string
  message: GmailMessageSummary
}) {
  const queryClient = useQueryClient()
  const conversationId = use(ToolConversationContext)
  return (
    <MessagePreviewRow
      date={relativeDateTime(message.date)}
      onOpen={prefetchProviderPreview(queryClient, conversationId, (id) =>
        gmailMessagePreviewQueryOptions(id, mailboxId, message.messageId)
      )}
      sender={message.sender}
      snippet={message.snippet}
      subject={message.subject}
    >
      <GmailMessageView
        mailboxId={mailboxId}
        errorFallback={
          <p className="text-muted-foreground py-4 text-center text-sm">
            This message preview is unavailable.
          </p>
        }
        fallback={<MessageDetailSkeleton label="Loading full message…" />}
        messageId={message.messageId}
      />
    </MessagePreviewRow>
  )
}

export function GmailMessageBody({
  mailboxId,
  message,
}: {
  mailboxId: string
  message: GmailMessage
}) {
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
          mailboxId={mailboxId}
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
}
