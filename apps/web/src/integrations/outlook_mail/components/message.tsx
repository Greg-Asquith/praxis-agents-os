// apps/web/src/integrations/outlook_mail/components/message.tsx

import { use } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { AlertCircleIcon, PaperclipIcon } from "lucide-react"

import { ExternalContent } from "@/components/tool-ui/external-content"
import {
  MessageDetail,
  MessageDetailSkeleton,
  MessagePreviewRow,
} from "@/components/tool-ui/message"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { Badge } from "@/components/ui/badge"
import { outlookMessagePreviewQueryOptions } from "@/integrations/outlook_mail/api/message-preview"
import { OutlookMessageView } from "@/integrations/outlook_mail/components/message-preview"
import {
  messageDate,
  type OutlookAttachment,
  type OutlookMessage,
  type OutlookMessageDetail,
} from "@/integrations/outlook_mail/lib/messages"
import { formatBytes, pluralize } from "@/lib/format"

export function OutlookMessageRow({ message }: { message: OutlookMessage }) {
  const queryClient = useQueryClient()
  const conversationId = use(ToolConversationContext)
  const prefetchMessage = () => {
    if (conversationId !== null) {
      void queryClient.prefetchQuery(
        outlookMessagePreviewQueryOptions(conversationId, message.mailboxId, message.messageId)
      )
    }
  }

  return (
    <MessagePreviewRow
      date={messageDate(message)}
      onOpen={prefetchMessage}
      provenance={<MessageFlags message={message} />}
      sender={message.sender}
      snippet={message.preview}
      subject={message.subject}
    >
      <OutlookMessageView
        mailboxId={message.mailboxId}
        errorFallback={
          <p className="text-muted-foreground py-4 text-center text-sm">
            This message preview is unavailable.
          </p>
        }
        fallback={<MessageDetailSkeleton label="Loading message preview…" />}
        messageId={message.messageId}
      />
    </MessagePreviewRow>
  )
}

function MessageFlags({ message }: { message: OutlookMessage }) {
  if (!message.unread && !message.important && !message.hasAttachments) {
    return null
  }
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {message.unread ? <Badge variant="secondary">Unread</Badge> : null}
      {message.important ? (
        <Badge variant="warning">
          <AlertCircleIcon />
          High importance
        </Badge>
      ) : null}
      {message.hasAttachments ? (
        <Badge variant="outline">
          <PaperclipIcon />
          Attachment
        </Badge>
      ) : null}
    </div>
  )
}

export function OutlookMessageBody({ message }: { message: OutlookMessageDetail }) {
  const plainBody = (
    <div className="grid min-w-0 gap-2">
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
        <div className="grid min-w-0 gap-3">
          <AttachmentList attachments={message.attachments} />
          <OutlookMessageView
            mailboxId={message.mailboxId}
            fallback={plainBody}
            messageId={message.messageId}
          />
        </div>
      }
      date={messageDate(message)}
      from={message.sender}
      subject={message.subject}
      to={message.to}
    />
  )
}

function AttachmentList({ attachments }: { attachments: OutlookAttachment[] }) {
  if (attachments.length === 0) {
    return null
  }
  return (
    <section aria-label="Attachments" className="grid min-w-0 gap-1.5">
      <p className="text-muted-foreground text-xs">
        {String(attachments.length)} {pluralize(attachments.length, "Attachment")}
      </p>
      <ul className="flex min-w-0 flex-wrap gap-1.5">
        {attachments.map((attachment, index) => (
          <li className="min-w-0" key={`${String(index)}-${attachment.name}`}>
            <Badge className="max-w-full font-normal" title={attachment.name} variant="outline">
              <PaperclipIcon />
              <span className="truncate">{attachment.name}</span>
              {attachment.sizeBytes !== null ? (
                <span className="text-muted-foreground">{formatBytes(attachment.sizeBytes)}</span>
              ) : null}
            </Badge>
          </li>
        ))}
      </ul>
    </section>
  )
}
