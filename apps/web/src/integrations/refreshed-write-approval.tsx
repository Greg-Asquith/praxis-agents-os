// apps/web/src/integrations/refreshed-write-approval.tsx

import { use, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"

import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import {
  approvalDisplayQueryOptions,
  type ApprovalDisplayRefresh,
} from "@/integrations/approval-display-query"

export function RefreshedWriteApproval({
  args,
  children,
  locked,
  refresh,
  toolName,
}: {
  args: unknown
  children: (args: unknown, error: string | null) => ReactNode
  locked: boolean
  refresh: ApprovalDisplayRefresh
  toolName: string
}) {
  const conversationId = use(ToolConversationContext)
  const result = useQuery({
    ...approvalDisplayQueryOptions(args, conversationId, toolName, refresh),
    enabled: Boolean(conversationId) && !locked,
  })
  const error =
    !conversationId || result.isError
      ? "The selected details couldn't be refreshed. Choose the targets again or decline this request."
      : result.isPending || result.isFetching
        ? "Checking the selected details before approval…"
        : null
  return children(result.data, error)
}
