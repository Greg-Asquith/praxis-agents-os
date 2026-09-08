// apps/web/src/integrations/gmail/api/message-preview.ts

import { providerPreviewQueryOptions } from "@/components/tool-ui/provider-preview-queries"
import { baseIntegrationQueryKeys } from "@/lib/integration-query-keys"

export type GmailMessagePreview = {
  kind: string
  content_type: "html" | "text"
  content: string
  meta: {
    message_id?: string
    subject?: string
    from?: string
    to?: string
    cc?: string
    date?: string
    labels?: string[]
    thread_message_count?: number | null
  }
}

const gmailQueryKeys = {
  messagePreview: (conversationId: string, mailboxId: string, messageId: string) =>
    [
      ...baseIntegrationQueryKeys.workspace(),
      "conversation",
      conversationId,
      "gmail",
      "message-preview",
      mailboxId,
      messageId,
    ] as const,
}

export function gmailMessagePreviewQueryOptions(
  conversationId: string | null,
  mailboxId: string,
  messageId: string
) {
  return providerPreviewQueryOptions<GmailMessagePreview["meta"]>({
    conversationId,
    providerKey: "gmail",
    kind: "gmail_message",
    scopeId: mailboxId,
    ref: messageId,
    queryKey: gmailQueryKeys.messagePreview(conversationId ?? "unavailable", mailboxId, messageId),
  })
}
