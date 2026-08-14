// apps/web/src/integrations/gmail/api/message-preview.ts

import { queryOptions } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
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
  return queryOptions({
    queryKey: gmailQueryKeys.messagePreview(conversationId ?? "unavailable", mailboxId, messageId),
    enabled: conversationId !== null,
    queryFn: () =>
      apiRequest<GmailMessagePreview>(
        `/integrations/conversations/${conversationId ?? "unavailable"}/previews/gmail_message`,
        { query: { provider_key: "gmail", ref: messageId, scope_id: mailboxId } }
      ),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  })
}
