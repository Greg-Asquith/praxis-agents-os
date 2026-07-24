// apps/web/src/integrations/gmail/lib/search-interaction.ts

import type { QueryClient } from "@tanstack/react-query"

import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api/message-preview"

export function gmailSearchMessageSelectHandler({
  connectionId,
  messageId,
  onOpen,
  queryClient,
}: {
  connectionId: string
  messageId: string
  onOpen: () => void
  queryClient: QueryClient
}) {
  return () => {
    onOpen()
    void queryClient.prefetchQuery(gmailMessagePreviewQueryOptions(connectionId, messageId))
  }
}
