// apps/web/src/features/conversations/api/review-approval.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { conversationRecoveryQueryOptions } from "@/features/conversations/api/get-conversation-recovery"
import { reconcileApprovalSubmission } from "@/features/conversations/approval-submission"
import type { AgentRunApprovalStateResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export type ApprovalReviewInput = {
  runId: string
  approval_revision: string
  approval_id: string
  override_args: Record<string, unknown>
}

export function useReviewApprovalMutation(conversationId: string) {
  const client = useQueryClient()
  const recovery = conversationRecoveryQueryOptions(client, conversationId)
  return useMutation({
    mutationFn: ({ runId, ...body }: ApprovalReviewInput) =>
      reconcileApprovalSubmission(
        () =>
          apiRequest<AgentRunApprovalStateResponse>(`/agent-runs/${runId}/review-approval`, {
            method: "POST",
            body,
          }),
        () => client.fetchQuery({ ...recovery, staleTime: 0 })
      ),
  })
}
