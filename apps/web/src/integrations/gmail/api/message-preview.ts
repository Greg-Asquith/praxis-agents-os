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
  messagePreview: (connectionId: string, messageId: string) =>
    [
      ...baseIntegrationQueryKeys.detail(connectionId),
      "gmail",
      "message-preview",
      messageId,
    ] as const,
}

export function gmailMessagePreviewQueryOptions(connectionId: string, messageId: string) {
  return queryOptions({
    queryKey: gmailQueryKeys.messagePreview(connectionId, messageId),
    queryFn: () =>
      apiRequest<GmailMessagePreview>(
        `/integrations/connections/${connectionId}/previews/gmail_message`,
        { query: { ref: messageId } }
      ),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  })
}
