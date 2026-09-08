// apps/web/src/integrations/approval-display-query.ts

import { queryOptions } from "@tanstack/react-query"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const queryKeys = createWorkspaceScopedQueryKeys("approval-display")

export type ApprovalDisplayRefresh = (
  args: unknown,
  conversationId: string,
  signal: AbortSignal
) => Promise<Record<string, unknown>>

export function approvalDisplayQueryOptions(
  args: unknown,
  conversationId: string | null,
  toolName: string,
  refresh: ApprovalDisplayRefresh
) {
  return queryOptions({
    queryKey: [...queryKeys.workspace(), conversationId, toolName, args],
    queryFn: ({ signal }) => {
      if (!conversationId) throw new Error("Conversation unavailable")
      return refresh(args, conversationId, signal)
    },
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}
