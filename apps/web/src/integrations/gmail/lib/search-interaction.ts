// apps/web/src/integrations/gmail/lib/search-interaction.ts

import type { QueryClient } from "@tanstack/react-query"

import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api/message-preview"

export function gmailSearchMessageSelectHandler({
  conversationId,
  mailboxId,
  messageId,
  onOpen,
  queryClient,
}: {
  conversationId: string | null
  mailboxId: string
  messageId: string
  onOpen: () => void
  queryClient: QueryClient
}) {
  return () => {
    onOpen()
    if (conversationId !== null) {
      void queryClient.prefetchQuery(
        gmailMessagePreviewQueryOptions(conversationId, mailboxId, messageId)
      )
    }
  }
}
