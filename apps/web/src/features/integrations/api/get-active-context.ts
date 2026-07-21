// apps/web/src/features/integrations/api/get-active-context.ts

import { queryOptions } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { ActiveContextRead } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function getActiveContext(conversationId: string) {
  return apiRequest<ActiveContextRead>(`/integrations/conversations/${conversationId}/context`)
}

export function activeContextQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: integrationsQueryKeys.activeContext(conversationId),
    queryFn: () => getActiveContext(conversationId),
  })
}
