// apps/web/src/features/conversations/run-error-copy.ts

import { isRecord } from "@/lib/guards"
import { ApiError } from "@/lib/api/errors"
import type { AgentRun } from "@/features/conversations/types"
import type { StreamError } from "@/features/conversations/stream/protocol"

const MODEL_PROVIDER_NOT_CONFIGURED = "model_provider_not_configured"
const APPROVAL_EXPIRED = "approval_expired"
const CODE_MODE_RECOVERY = "code_mode_resume_requires_recovery"
const MAX_COMPLETED_ACTIONS = 25

export type RunInterruptionOutcome = {
  kind:
    "approval_expired" | "code_mode_recovery" | "run_recovery" | "budget_exhausted" | "run_failed"
  title: string
  message: string
  completedActions: { id: string; toolName: string }[]
  actionsTruncated: boolean
  uncertainActions?: { id: string; toolName: string }[]
  childConversations?: string[]
}

export function runInterruptionOutcome(run: AgentRun | null): RunInterruptionOutcome | null {
  if (run?.status === "cancelled" && isRecord(run.completion_json?.["recovery"])) {
    return {
      kind: "run_recovery",
      title: "Stopped actions need review",
      message:
        "This run was stopped. An action already sent may still have completed. Check completed and uncertain actions before giving a new instruction.",
      ...recoveryEvidence(run.completion_json["recovery"]),
    }
  }
  if (run?.status !== "failed") return null
  if (run.outcome === "budget_exhausted") {
    return {
      kind: "budget_exhausted",
      title: "Run limit reached",
      message:
        tokenBudgetMessage(run.completion_json) ??
        run.error_message ??
        "This run reached its usage limit. Start a new conversation or shorten the context to continue.",
      ...recoveryEvidence(run.completion_json?.["recovery"]),
    }
  }
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
  if (run.error_code === "agent_run_resume_requires_recovery") {
    return {
      kind: "run_recovery",
      title: "Actions need review",
      message:
        "This run stopped because its approved actions couldn't continue safely. Check completed and uncertain actions before giving a new instruction.",
      ...recoveryEvidence(run.completion_json?.["recovery"]),
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

export function runFailureOutcome(run: AgentRun): RunInterruptionOutcome | null {
  if (run.status !== "failed") return null
  return (
    runInterruptionOutcome(run) ?? {
      kind: "run_failed",
      title: "Run stopped",
      message: formatStreamError({
        code: run.error_code ?? "run_failed",
        message:
          run.error_message ??
          "This run stopped before it finished. Send a new message to try again.",
      }),
      completedActions: [],
      actionsTruncated: false,
    }
  )
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

export function tokenBudgetMessage(completion: Record<string, unknown> | null): string | null {
  const budget = completion?.["tripped_budget"]
  if (!isRecord(budget) || budget["kind"] !== "total_tokens") return null
  const limit = budget["limit"]
  const observed = completion?.["observed_total_tokens"]
  const requests = completion?.["requests"]
  if (!isUsageCount(limit) || !isUsageCount(observed) || !isUsageCount(requests)) return null
  return (
    `This run stopped after counting ${observed.toLocaleString("en-GB")} tokens across ` +
    `${requests.toLocaleString("en-GB")} ${requests === 1 ? "request" : "requests"}; ` +
    `the limit for this run is ${limit.toLocaleString("en-GB")}. ` +
    "Start a new conversation or shorten the context to continue."
  )
}

function isUsageCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
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

export function approvalConflictMessage(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  if (error.problem?.["code"] === "approval_already_reserved") {
    return "Your decisions were already accepted. The conversation is refreshing to show their progress."
  }
  if (error.problem?.["code"] === "approval_decisions_conflict") {
    return "Different decisions were already accepted. Your latest changes were not applied. Review the refreshed conversation."
  }
  if (error.problem?.["code"] === "delegated_run_requires_root_approval") {
    return "Review these requests in the main conversation. Open the main conversation link to continue."
  }
  return "These requests have changed. Refresh and review them again."
}

function recoveryEvidence(
  raw: unknown
): Pick<
  RunInterruptionOutcome,
  "completedActions" | "uncertainActions" | "childConversations" | "actionsTruncated"
> {
  const completed: { id: string; toolName: string }[] = []
  const uncertain: { id: string; toolName: string }[] = []
  const children: string[] = []
  if (!isRecord(raw)) {
    return {
      completedActions: completed,
      uncertainActions: uncertain,
      childConversations: children,
      actionsTruncated: false,
    }
  }
  const actions: unknown[] = Array.isArray(raw["actions"]) ? raw["actions"] : []
  for (const item of actions.slice(0, MAX_COMPLETED_ACTIONS)) {
    if (!isRecord(item)) continue
    const owner = item["owner_run_id"]
    const call = item["tool_call_id"]
    const tool = item["tool_name"]
    if (
      typeof owner !== "string" ||
      typeof call !== "string" ||
      typeof tool !== "string" ||
      !tool.trim()
    )
      continue
    const action = { id: `${owner}:${call}`, toolName: tool }
    if (item["status"] === "completed") completed.push(action)
    if (item["status"] === "uncertain") uncertain.push(action)
  }
  const references: unknown[] = Array.isArray(raw["children"]) ? raw["children"] : []
  for (const item of references.slice(0, 1024)) {
    if (!isRecord(item)) continue
    const conversation = item["conversation_id"]
    if (
      typeof conversation === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(conversation) &&
      !children.includes(conversation)
    )
      children.push(conversation)
  }
  return {
    completedActions: completed,
    uncertainActions: uncertain,
    childConversations: children,
    actionsTruncated: raw["truncated"] === true || actions.length > MAX_COMPLETED_ACTIONS,
  }
}

export function formatStreamError(error: StreamError): string {
  if (error.code === MODEL_PROVIDER_NOT_CONFIGURED) {
    return (
      `${error.message} Add the provider's API key to .local/targets/local.secrets.env ` +
      "(Docker stack) or apps/api/.env (make dev), then restart the system."
    )
  }
  return error.message
}
