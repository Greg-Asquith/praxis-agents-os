// apps/web/src/integrations/gmail/components/message-preview.tsx

import { use, type ReactNode } from "react"
import { MailsIcon, TagIcon } from "lucide-react"

import { ProviderContentPreview } from "@/components/tool-ui/provider-content-preview"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { Badge } from "@/components/ui/badge"
import {
  gmailMessagePreviewQueryOptions,
  type GmailMessagePreview,
} from "@/integrations/gmail/api/message-preview"

export function GmailMessageView({
  mailboxId,
  errorFallback,
  fallback,
  messageId,
}: {
  mailboxId: string
  errorFallback?: ReactNode
  fallback: ReactNode
  messageId: string
}) {
  const conversationId = use(ToolConversationContext)
  return (
    <ProviderContentPreview
      query={gmailMessagePreviewQueryOptions(conversationId, mailboxId, messageId)}
      fallback={fallback}
      errorFallback={errorFallback}
      renderMeta={(meta) => <MessageMetaChips meta={meta} />}
    />
  )
}

function MessageMetaChips({ meta }: { meta: GmailMessagePreview["meta"] }) {
  const labels = meta.labels ?? []
  const threadCount = meta.thread_message_count ?? null
  const inThread = threadCount !== null && threadCount > 1

  if (labels.length === 0 && !inThread) {
    return null
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {labels.map((label) => (
        <Badge key={label} variant="outline">
          <TagIcon /> {label}
        </Badge>
      ))}
      {inThread ? (
        <Badge variant="secondary">
          <MailsIcon /> Thread · {String(threadCount)} Messages
        </Badge>
      ) : null}
    </div>
  )
}
