// apps/web/src/integrations/gmail/search-interaction.ts
import type { QueryClient } from "@tanstack/react-query"

import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api"

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
