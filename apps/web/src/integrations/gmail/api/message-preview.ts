// apps/web/src/integrations/gmail/api/message-preview.ts

import { providerPreviewQueryOptions } from "@/components/tool-ui/provider-preview-queries"

export type GmailMessagePreviewMeta = {
  message_id?: string
  subject?: string
  from?: string
  to?: string
  cc?: string
  date?: string
  labels?: string[]
  thread_message_count?: number | null
}

export function gmailMessagePreviewQueryOptions(
  conversationId: string | null,
  mailboxId: string,
  messageId: string
) {
  return providerPreviewQueryOptions<GmailMessagePreviewMeta>({
    conversationId,
    providerKey: "gmail",
    kind: "gmail_message",
    scopeId: mailboxId,
    ref: messageId,
  })
}
