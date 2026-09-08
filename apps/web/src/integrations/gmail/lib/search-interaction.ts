// apps/web/src/integrations/gmail/lib/search-interaction.ts

import type { QueryClient } from "@tanstack/react-query"

import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api/message-preview"

export function gmailSearchMessageSelectHandler({
  conversationId,
  mailboxId,
  messageId,
  queryClient,
}: {
  conversationId: string | null
  mailboxId: string
  messageId: string
  queryClient: QueryClient
}) {
  return () => {
    if (conversationId !== null) {
      void queryClient.prefetchQuery(
        gmailMessagePreviewQueryOptions(conversationId, mailboxId, messageId)
      )
    }
  }
}
