// apps/web/src/features/conversations/message-parts.ts

import type {
  AgentRunStatus,
  ConversationMessage,
  PendingDelegatedApproval,
} from "@/features/conversations/types"
import { truncateForPreview } from "@/lib/format"
import { isRecord, stringValue, optionalString } from "@/lib/guards"

type ParsedMessageRole = "user" | "assistant" | "tool" | "system" | "unknown"

type ToolActivityKind = "call" | "result" | "approval" | "retry" | "unknown"

type ToolActivityStatus =
  "running" | "awaiting_approval" | "completed" | "failed" | "denied" | "unknown"

type ToolApprovalDecision = "approved" | "denied"

export type DelegationToolActivity = {
  status: "running" | "awaiting_approval" | "completed" | "failed" | "unknown"
  agentId: string | null
  agentName: string | null
  taskPreview: string | null
  output: string | null
  error: string | null
  runId: string | null
  conversationId: string | null
  pendingApprovalCount: number
  truncated: boolean
}

export type ToolActivity = {
  id: string
  kind: ToolActivityKind
  status: ToolActivityStatus
  name: string
  args?: unknown
  decision?: ToolApprovalDecision
  delegate?: DelegationToolActivity
  result?: unknown
  outcome?: string | null
}

type UnsupportedMessagePart = {
  id: string
  label: string
  preview: string
}

export type ParsedConversationMessage = {
  id: string
  role: ParsedMessageRole
  sequence: number
  clientMessageId: string | null
  createdAt: string
  text: string[]
  thinking: string[]
  toolActivities: ToolActivity[]
  unsupportedParts: UnsupportedMessagePart[]
}

export type PendingUserMessage = {
  clientMessageId: string
  conversationId: string | null
  text: string
  createdAt: string
}

const PREVIEW_LIMIT = 2400
const DELEGATION_TASK_PREVIEW_LIMIT = 500

const TOOL_RESULT_PART_KINDS = new Set(["tool-return", "builtin-tool-return", "native-tool-return"])

const TOOL_CALL_PART_KINDS = new Set(["tool-call", "builtin-tool-call", "native-tool-call"])

const DELEGATE_TO_AGENT_TOOL_NAME = "delegate_to_agent"

export function parseConversationMessages(
  messages: ConversationMessage[],
  activeRunStatus?: AgentRunStatus | null,
  pendingDelegations: PendingDelegatedApproval[] = []
): ParsedConversationMessage[] {
  const parsed = messages.map(parseConversationMessage)
  const { consumedResultKeys, resultsByCallKey } = pairToolResults(parsed)
  const pendingDelegationsByParentCallId = new Map(
    pendingDelegations.map((delegation) => [delegation.parent_tool_call_id, delegation])
  )

  const runAwaitsApproval = activeRunStatus === "awaiting_approval"
  const runIsExecuting = isRunStatusPolling(activeRunStatus)

  return parsed
    .map((message, messageIndex) => ({
      ...message,
      toolActivities: message.toolActivities
        .map((activity, activityIndex) => {
          if (activity.kind !== "call" || !activity.id) {
            return activity
          }

          const pendingDelegate = pendingDelegationsByParentCallId.get(activity.id)
          const activityDelegate = pendingDelegate
            ? mergeDelegationDetails(
                activity.delegate,
                delegationDetailsForPendingApproval(pendingDelegate, activity.args)
              )
            : activity.delegate
          const activityWithDelegate = activityDelegate
            ? { ...activity, delegate: activityDelegate }
            : activity

          const result = resultsByCallKey.get(toolActivityKey(messageIndex, activityIndex))
          if (result) {
            const delegate = mergeDelegationDetails(activityDelegate, result.delegate)
            const mergedActivity: ToolActivity = {
              ...activity,
              outcome: result.outcome ?? null,
              result: result.result,
              status: result.status,
            }
            if (delegate) {
              mergedActivity.delegate = delegate
            }
            if (result.args !== undefined) {
              mergedActivity.args = result.args
            }
            if (result.decision !== undefined) {
              mergedActivity.decision = result.decision
            }
            return mergedActivity
          }
          if (runAwaitsApproval) {
            return {
              ...activityWithDelegate,
              kind: "approval" as const,
              status: "awaiting_approval" as const,
            }
          }
          if (!runIsExecuting) {
            return { ...activityWithDelegate, status: "unknown" as const }
          }
          return activityWithDelegate
        })
        .filter((activity, activityIndex) => {
          if (
            (activity.kind === "result" || activity.kind === "retry") &&
            consumedResultKeys.has(toolActivityKey(messageIndex, activityIndex))
          ) {
            return false
          }
          return true
        }),
    }))
    .filter(hasRenderableMessageContent)
}

type ToolActivityPointer = {
  activityIndex: number
  messageIndex: number
}

function pairToolResults(messages: ParsedConversationMessage[]) {
  const consumedResultKeys = new Set<string>()
  const pendingCallsById = new Map<string, ToolActivityPointer[]>()
  const resultsByCallKey = new Map<string, ToolActivity>()

  messages.forEach((message, messageIndex) => {
    message.toolActivities.forEach((activity, activityIndex) => {
      if (!activity.id) {
        return
      }

      if (activity.kind === "call") {
        const pendingCalls = pendingCallsById.get(activity.id) ?? []
        pendingCalls.push({ activityIndex, messageIndex })
        pendingCallsById.set(activity.id, pendingCalls)
        return
      }

      if (activity.kind !== "result" && activity.kind !== "retry") {
        return
      }

      const pendingCalls = pendingCallsById.get(activity.id)
      const call = pendingCalls?.pop()
      if (!call) {
        return
      }

      resultsByCallKey.set(toolActivityKey(call.messageIndex, call.activityIndex), activity)
      consumedResultKeys.add(toolActivityKey(messageIndex, activityIndex))
    })
  })

  return { consumedResultKeys, resultsByCallKey }
}

function toolActivityKey(messageIndex: number, activityIndex: number) {
  return `${String(messageIndex)}:${String(activityIndex)}`
}

function parseConversationMessage(message: ConversationMessage): ParsedConversationMessage {
  const rawParts = getMessageParts(message.parts)
  const parsed: ParsedConversationMessage = {
    id: message.id,
    role: normalizeRole(message.role),
    sequence: message.sequence,
    clientMessageId: message.client_message_id,
    createdAt: message.created_at,
    text: [],
    thinking: [],
    toolActivities: [],
    unsupportedParts: [],
  }

  if (rawParts.length === 0) {
    const fallback = extractFallbackText(message.parts)
    if (fallback) {
      parsed.text.push(fallback)
    } else {
      parsed.unsupportedParts.push({
        id: `${message.id}:empty`,
        label: "Empty message",
        preview: safeJsonPreview(message.parts),
      })
    }
    return parsed
  }

  rawParts.forEach((part, index) => {
    const partKind = stringValue(part["part_kind"])
    const partId = `${message.id}:${String(index)}`

    if (partKind === "user-prompt") {
      const text = extractContentText(part["content"])
      if (text) {
        parsed.text.push(text)
      } else {
        parsed.unsupportedParts.push({
          id: partId,
          label: "User prompt",
          preview: safeJsonPreview(part["content"]),
        })
      }
      return
    }

    if (partKind === "text") {
      const text = stringValue(part["content"])
      if (text) {
        parsed.text.push(text)
      }
      return
    }

    if (partKind === "thinking" || partKind === "redacted-thinking") {
      // Encrypted/redacted reasoning arrives with an empty content and only a signature;
      // keep the block out of the transcript entirely rather than dumping the raw part.
      const thinking = stringValue(part["content"])
      if (thinking) {
        parsed.thinking.push(thinking)
      }
      return
    }

    if (partKind && TOOL_CALL_PART_KINDS.has(partKind)) {
      const name = stringValue(part["tool_name"]) ?? "tool"
      const args = normalizeToolArgs(part["args"])
      const activity: ToolActivity = {
        id: stringValue(part["tool_call_id"]) ?? partId,
        kind: "call",
        status: "running",
        name,
        args,
      }
      const delegate = delegationDetailsForToolActivity(name, args)
      if (delegate) {
        activity.delegate = delegate
      }
      parsed.toolActivities.push(activity)
      return
    }

    if (partKind && TOOL_RESULT_PART_KINDS.has(partKind)) {
      const outcome = stringValue(part["outcome"])
      const toolCallId = stringValue(part["tool_call_id"]) ?? partId
      const approvalMetadata = approvalMetadataForTool(message.metadata, toolCallId)
      const name = stringValue(part["tool_name"]) ?? "tool"
      const activity: ToolActivity = {
        id: toolCallId,
        kind: "result",
        status: approvalMetadata?.decision === "denied" ? "denied" : statusFromOutcome(outcome),
        name,
        result: part["content"],
        outcome,
      }
      const delegate = delegationDetailsForToolActivity(name, undefined, part["content"])
      if (delegate) {
        activity.delegate = delegate
      }
      if (approvalMetadata?.effectiveArgs !== undefined) {
        activity.args = normalizeToolArgs(approvalMetadata.effectiveArgs)
      }
      if (approvalMetadata?.decision !== undefined) {
        activity.decision = approvalMetadata.decision
      }
      parsed.toolActivities.push({
        ...activity,
      })
      return
    }

    if (partKind === "retry-prompt") {
      parsed.toolActivities.push({
        id: stringValue(part["tool_call_id"]) ?? partId,
        kind: "retry",
        status: "failed",
        name: stringValue(part["tool_name"]) ?? "tool",
        result: part["content"],
        outcome: "retry",
      })
      return
    }

    if (partKind === "system-prompt") {
      parsed.unsupportedParts.push({
        id: partId,
        label: "System prompt",
        preview: safeJsonPreview(part["content"]),
      })
      return
    }

    const fallbackText = extractFallbackText(part)
    if (fallbackText) {
      parsed.text.push(fallbackText)
      return
    }

    parsed.unsupportedParts.push({
      id: partId,
      label: partKind ? unsupportedLabel(partKind) : "Unsupported part",
      preview: safeJsonPreview(part),
    })
  })

  return parsed
}

function hasRenderableMessageContent(message: ParsedConversationMessage) {
  return (
    message.text.length > 0 ||
    message.thinking.length > 0 ||
    message.toolActivities.length > 0 ||
    message.unsupportedParts.length > 0
  )
}

export function pendingMessagesForConversation(
  pendingMessages: PendingUserMessage[],
  conversationId: string,
  persistedMessages: ConversationMessage[],
  pendingConversationIdAlias: string | null = null
): PendingUserMessage[] {
  const persistedClientIds = new Set(
    persistedMessages
      .map((message) => message.client_message_id)
      .filter((value): value is string => typeof value === "string" && value.length > 0)
  )

  return pendingMessages.filter(
    (message) =>
      (message.conversationId === conversationId ||
        (message.conversationId === null && pendingConversationIdAlias === conversationId)) &&
      !persistedClientIds.has(message.clientMessageId)
  )
}

export function isRunStatusPolling(status: AgentRunStatus | null | undefined) {
  return status === "pending" || status === "running"
}

export function safeJsonPreview(value: unknown, limit = PREVIEW_LIMIT) {
  let raw: string
  try {
    raw = JSON.stringify(value, null, 2)
  } catch {
    raw = String(value)
  }

  if (raw.length <= limit) {
    return raw
  }

  return `${raw.slice(0, limit)}\n...`
}

function getMessageParts(value: Record<string, unknown>): Record<string, unknown>[] {
  const parts = value["parts"]
  if (!Array.isArray(parts)) {
    return []
  }

  return parts.filter(isRecord)
}

function extractContentText(value: unknown): string | null {
  if (typeof value === "string") {
    return value
  }

  if (!Array.isArray(value)) {
    return null
  }

  const segments = value
    .map((item) => {
      if (typeof item === "string") {
        return item
      }
      if (!isRecord(item)) {
        return null
      }
      return stringValue(item["text"]) ?? stringValue(item["content"])
    })
    .filter((item): item is string => typeof item === "string" && item.length > 0)

  return segments.length > 0 ? segments.join("\n") : null
}

function extractFallbackText(value: unknown): string | null {
  if (!isRecord(value)) {
    return null
  }

  return stringValue(value["text"]) ?? stringValue(value["content"])
}

function approvalMetadataForTool(
  metadata: Record<string, unknown> | null,
  toolCallId: string
): { decision: ToolApprovalDecision; effectiveArgs?: unknown } | null {
  if (!metadata) {
    return null
  }

  const approvalResults = metadata["approval_results"]
  if (!isRecord(approvalResults)) {
    return null
  }

  const approvalMetadata = approvalResults[toolCallId]
  if (!isRecord(approvalMetadata)) {
    return null
  }

  const decision = toolApprovalDecision(approvalMetadata["decision"])
  if (decision === null) {
    return null
  }

  const result: { decision: ToolApprovalDecision; effectiveArgs?: unknown } = {
    decision,
  }
  if ("effective_args" in approvalMetadata) {
    result.effectiveArgs = approvalMetadata["effective_args"]
  }
  return result
}

function toolApprovalDecision(value: unknown): ToolApprovalDecision | null {
  if (value === "approved" || value === "denied") {
    return value
  }
  return null
}

export function normalizeToolArgs(value: unknown) {
  if (typeof value !== "string") {
    return value
  }

  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

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

  return {
    status: delegationStatus(resultRecord?.["status"]) ?? "running",
    agentId: optionalString(resultRecord?.["agent_id"]) ?? optionalString(argRecord?.["agent_id"]),
    agentName: optionalString(resultRecord?.["agent_name"]),
    taskPreview: truncateForPreview(
      optionalString(argRecord?.["task"]),
      DELEGATION_TASK_PREVIEW_LIMIT
    ),
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

  return {
    status: "awaiting_approval",
    agentId: delegation.child_agent_id,
    agentName: delegation.child_agent_name,
    taskPreview: truncateForPreview(
      optionalString(argRecord?.["task"]),
      DELEGATION_TASK_PREVIEW_LIMIT
    ),
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

function statusFromOutcome(outcome: string | null | undefined): ToolActivityStatus {
  if (outcome === "failed") {
    return "failed"
  }
  if (outcome === "denied") {
    return "denied"
  }
  if (outcome === "success") {
    return "completed"
  }
  return "completed"
}

function unsupportedLabel(partKind: string) {
  return partKind
    .split("-")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ")
}

function normalizeRole(role: string): ParsedMessageRole {
  if (role === "user" || role === "assistant" || role === "tool" || role === "system") {
    return role
  }

  return "unknown"
}
