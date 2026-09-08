// apps/web/src/integrations/outlook_mail/components/message-preview.tsx

import { use, type ReactNode } from "react"

import { ProviderContentPreview } from "@/components/tool-ui/provider-content-preview"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { outlookMessagePreviewQueryOptions } from "@/integrations/outlook_mail/api/message-preview"

export function OutlookMessageView({
  errorFallback,
  fallback,
  mailboxId,
  messageId,
}: {
  errorFallback?: ReactNode
  fallback: ReactNode
  mailboxId: string
  messageId: string
}) {
  const conversationId = use(ToolConversationContext)
  return (
    <ProviderContentPreview
      query={outlookMessagePreviewQueryOptions(conversationId, mailboxId, messageId)}
      fallback={fallback}
      errorFallback={errorFallback}
    />
  )
}
