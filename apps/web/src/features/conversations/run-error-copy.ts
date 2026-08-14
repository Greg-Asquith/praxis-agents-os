// apps/web/src/features/conversations/run-error-copy.ts

import type { AgentRun } from "@/features/conversations/types"

const APPROVAL_EXPIRED = "approval_expired"
const CODE_MODE_RECOVERY = "code_mode_resume_requires_recovery"
const MAX_COMPLETED_ACTIONS = 25

export type RunInterruptionOutcome = {
  kind: "approval_expired" | "code_mode_recovery"
  title: string
  message: string
  completedActions: { id: string; toolName: string }[]
  actionsTruncated: boolean
}

export function runInterruptionOutcome(run: AgentRun | null): RunInterruptionOutcome | null {
  if (run?.status !== "failed") return null
  if (run.error_code === APPROVAL_EXPIRED) {
    return {
      kind: "approval_expired",
      title: "Approval Expired",
      message:
        run.error_message ??
        "This approval expired, so the action wasn't taken. Send a new message to try again.",
      completedActions: [],
      actionsTruncated: false,
    }
  }
  if (run.error_code !== CODE_MODE_RECOVERY) return null
  const evidence = completedActions(run.completion_json)
  return {
    kind: "code_mode_recovery",
    title: "Workflow Needs Review",
    message:
      run.error_message ??
      "This workflow couldn't resume safely after completing an action. Review what completed, then send a new instruction to continue.",
    completedActions: evidence.actions,
    actionsTruncated: evidence.truncated,
  }
}

export function approvalExpiryOutcome(run: AgentRun | null): string | null {
  const outcome = runInterruptionOutcome(run)
  return outcome?.kind === "approval_expired" ? outcome.message : null
}

export function conversationApprovalExpiryOutcome(
  activeRun: AgentRun | null,
  latestRun: AgentRun | null
): string | null {
  if (activeRun !== null) return null
  return approvalExpiryOutcome(latestRun)
}

export function conversationRunInterruptionOutcome(
  activeRun: AgentRun | null,
  latestRun: AgentRun | null
): RunInterruptionOutcome | null {
  if (activeRun !== null) return null
  return runInterruptionOutcome(latestRun)
}

function completedActions(completion: Record<string, unknown> | null): {
  actions: { id: string; toolName: string }[]
  truncated: boolean
} {
  const raw = completion?.["executed_effects"]
  if (!Array.isArray(raw)) return { actions: [], truncated: false }
  const effects: unknown[] = raw
  const actions: { id: string; toolName: string }[] = []
  const occurrences = new Map<string, number>()
  for (const item of effects.slice(0, MAX_COMPLETED_ACTIONS)) {
    if (typeof item !== "object" || item === null) continue
    const toolName = "tool_name" in item ? item.tool_name : undefined
    if (typeof toolName === "string" && toolName.trim()) {
      const occurrence = (occurrences.get(toolName) ?? 0) + 1
      occurrences.set(toolName, occurrence)
      const nestedCallId = "nested_call_id" in item ? item.nested_call_id : undefined
      actions.push({
        id:
          typeof nestedCallId === "string" && nestedCallId
            ? nestedCallId
            : `${toolName}:${String(occurrence)}`,
        toolName,
      })
    }
  }
  return { actions, truncated: effects.length > MAX_COMPLETED_ACTIONS }
}
