// apps/web/src/features/conversations/message-parts/delegation.ts

import type { PendingDelegatedApproval } from "@/features/conversations/types"
import type { DelegationToolActivity } from "@/features/conversations/message-parts/types"
import { normalizeToolArgs } from "@/features/conversations/message-parts/utils"
import { truncateText } from "@/lib/format"
import { isRecord, optionalString } from "@/lib/guards"

const DELEGATION_TASK_PREVIEW_LIMIT = 500
const DELEGATE_TO_AGENT_TOOL_NAME = "delegate_to_agent"

export function delegationDetailsForToolActivity(
  name: string,
  args: unknown,
  result?: unknown
): DelegationToolActivity | undefined {
  if (name !== DELEGATE_TO_AGENT_TOOL_NAME) {
    return undefined
  }

  const normalizedArgs = normalizeToolArgs(args)
  const argRecord = isRecord(normalizedArgs) ? normalizedArgs : null
  const resultRecord = isRecord(result) ? result : null
  const pendingApprovals = resultRecord?.["pending_approvals"]
  const pendingApprovalCount = Array.isArray(pendingApprovals) ? pendingApprovals.length : 0
  const task = optionalString(argRecord?.["task"])

  return {
    status: delegationStatus(resultRecord?.["status"]) ?? "running",
    agentId: optionalString(resultRecord?.["agent_id"]) ?? optionalString(argRecord?.["agent_id"]),
    agentName: optionalString(resultRecord?.["agent_name"]),
    taskPreview: task === null ? null : truncateText(task, DELEGATION_TASK_PREVIEW_LIMIT),
    output: optionalString(resultRecord?.["output"]),
    error: optionalString(resultRecord?.["error"]),
    runId: optionalString(resultRecord?.["run_id"]),
    conversationId: optionalString(resultRecord?.["conversation_id"]),
    pendingApprovalCount,
    truncated: resultRecord?.["truncated"] === true,
  }
}

export function delegationDetailsForPendingApproval(
  delegation: PendingDelegatedApproval,
  args?: unknown
): DelegationToolActivity {
  const normalizedArgs = normalizeToolArgs(args)
  const argRecord = isRecord(normalizedArgs) ? normalizedArgs : null
  const task = optionalString(argRecord?.["task"])

  return {
    status: "awaiting_approval",
    agentId: delegation.child_agent_id,
    agentName: delegation.child_agent_name,
    taskPreview: task === null ? null : truncateText(task, DELEGATION_TASK_PREVIEW_LIMIT),
    output: null,
    error: null,
    runId: delegation.child_run_id,
    conversationId: delegation.child_conversation_id,
    pendingApprovalCount: delegation.pending_approval_count,
    truncated: false,
  }
}

export function mergeDelegationDetails(
  callDelegate: DelegationToolActivity | undefined,
  resultDelegate: DelegationToolActivity | undefined
): DelegationToolActivity | undefined {
  if (!callDelegate) {
    return resultDelegate
  }
  if (!resultDelegate) {
    return callDelegate
  }

  return {
    status: resultDelegate.status,
    agentId: resultDelegate.agentId ?? callDelegate.agentId,
    agentName: resultDelegate.agentName ?? callDelegate.agentName,
    taskPreview: callDelegate.taskPreview ?? resultDelegate.taskPreview,
    output: resultDelegate.output,
    error: resultDelegate.error,
    runId: resultDelegate.runId,
    conversationId: resultDelegate.conversationId,
    pendingApprovalCount: resultDelegate.pendingApprovalCount,
    truncated: resultDelegate.truncated,
  }
}

function delegationStatus(value: unknown): DelegationToolActivity["status"] | null {
  if (
    value === "running" ||
    value === "awaiting_approval" ||
    value === "completed" ||
    value === "failed" ||
    value === "unknown"
  ) {
    return value
  }
  return null
}
