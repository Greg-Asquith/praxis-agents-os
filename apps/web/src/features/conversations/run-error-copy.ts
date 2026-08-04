// apps/web/src/features/conversations/run-error-copy.ts

import type { AgentRun } from "@/features/conversations/types"

const APPROVAL_EXPIRED = "approval_expired"

export function approvalExpiryOutcome(run: AgentRun | null): string | null {
  if (run?.status !== "failed" || run.error_code !== APPROVAL_EXPIRED) {
    return null
  }

  return (
    run.error_message ??
    "This approval expired, so the action wasn't taken. Send a new message to try again."
  )
}

export function conversationApprovalExpiryOutcome(
  activeRun: AgentRun | null,
  latestRun: AgentRun | null
): string | null {
  if (activeRun !== null) {
    return null
  }
  return approvalExpiryOutcome(latestRun)
}
