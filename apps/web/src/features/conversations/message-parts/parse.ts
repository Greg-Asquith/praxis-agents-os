// apps/web/src/features/conversations/message-parts/parse.ts

import type {
  ParsedConversationMessage,
  ParsedMessagePart,
  ParsedMessageRole,
  ParsedAttachment,
  ToolActivity,
  ToolActivityStatus,
  ToolApprovalDecision,
} from "@/features/conversations/message-parts/types"
import {
  attachmentFromBinaryUserContentPart,
  isBinaryUserContentPart,
  isBinaryUserContentLike,
} from "@/features/conversations/attachments"
import {
  delegationDetailsForPendingApproval,
  delegationDetailsForToolActivity,
  mergeDelegationDetails,
} from "@/features/conversations/message-parts/delegation"
import {
  pairToolResults,
  toolActivityKey,
} from "@/features/conversations/message-parts/pair-tool-results"
import {
  isRunStatusPolling,
  normalizeToolArgs,
  safeJsonPreview,
} from "@/features/conversations/message-parts/utils"
import type {
  AgentRunStatus,
  ConversationMessage,
  PendingDelegatedApproval,
} from "@/features/conversations/types"
import { titleCaseToken } from "@/lib/format"
import { isRecord, stringValue } from "@/lib/guards"

const TOOL_RESULT_PART_KINDS = new Set(["tool-return", "builtin-tool-return", "native-tool-return"])
const TOOL_CALL_PART_KINDS = new Set(["tool-call", "builtin-tool-call", "native-tool-call"])

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
    .map((message, messageIndex) => {
      const resolvedActivities = message.toolActivities.map((activity, activityIndex) => {
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
      const resolvedActivitiesByOriginal = new Map<ToolActivity, ToolActivity | null>()
      const visibleActivities: ToolActivity[] = []
      resolvedActivities.forEach((activity, activityIndex) => {
        const originalActivity = message.toolActivities[activityIndex]
        if (!originalActivity) {
          return
        }
        if (
          (activity.kind === "result" || activity.kind === "retry") &&
          consumedResultKeys.has(toolActivityKey(messageIndex, activityIndex))
        ) {
          resolvedActivitiesByOriginal.set(originalActivity, null)
          return
        }
        resolvedActivitiesByOriginal.set(originalActivity, activity)
        visibleActivities.push(activity)
      })

      return {
        ...message,
        parts: resolveOrderedToolParts(message.parts, resolvedActivitiesByOriginal),
        toolActivities: visibleActivities,
      }
    })
    .filter(hasRenderableMessageContent)
}

function parseConversationMessage(message: ConversationMessage): ParsedConversationMessage {
  const rawParts = getMessageParts(message.parts)
  const parsed: ParsedConversationMessage = {
    id: message.id,
    role: normalizeRole(message.role),
    sequence: message.sequence,
    agentRunId: message.metadata ? (stringValue(message.metadata["agent_run_id"]) ?? null) : null,
    clientMessageId: message.client_message_id,
    createdAt: message.created_at,
    parts: rawParts.length > 0 ? [] : null,
    text: [],
    thinking: [],
    attachments: [],
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
      const content = parseUserPromptContent(part["content"], partId)
      if (content.text) {
        parsed.text.push(content.text)
        parsed.parts?.push({ kind: "text", id: partId, content: content.text })
      }
      parsed.attachments.push(...content.attachments)
      parsed.unsupportedParts.push(...content.unsupportedParts)
      if (
        !content.text &&
        content.attachments.length === 0 &&
        content.unsupportedParts.length === 0
      ) {
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
        parsed.parts?.push({ kind: "text", id: partId, content: text })
      }
      return
    }

    if (partKind === "thinking" || partKind === "redacted-thinking") {
      // Encrypted/redacted reasoning arrives with an empty content and only a signature;
      // keep the block out of the transcript entirely rather than dumping the raw part.
      const thinking = stringValue(part["content"])
      if (thinking) {
        parsed.thinking.push(thinking)
        parsed.parts?.push({ kind: "thinking", id: partId, content: thinking })
      }
      return
    }

    if (partKind && TOOL_CALL_PART_KINDS.has(partKind)) {
      const name = stringValue(part["tool_name"]) ?? "tool"
      const args = normalizeToolArgs(part["args"])
      // Preserve capability-load tool kinds so activation rows can hide loaded instructions.
      const toolKind = stringValue(part["tool_kind"])
      const activity: ToolActivity = {
        id: stringValue(part["tool_call_id"]) ?? partId,
        kind: "call",
        status: "running",
        name,
        args,
        ...(toolKind ? { toolKind } : {}),
      }
      const delegate = delegationDetailsForToolActivity(name, args)
      if (delegate) {
        activity.delegate = delegate
      }
      parsed.toolActivities.push(activity)
      parsed.parts?.push({ kind: "tool", id: partId, activity })
      return
    }

    if (partKind && TOOL_RESULT_PART_KINDS.has(partKind)) {
      const outcome = stringValue(part["outcome"])
      const toolCallId = stringValue(part["tool_call_id"]) ?? partId
      const approvalMetadata = approvalMetadataForTool(message.metadata, toolCallId)
      const name = stringValue(part["tool_name"]) ?? "tool"
      const toolKind = stringValue(part["tool_kind"])
      const activity: ToolActivity = {
        id: toolCallId,
        kind: "result",
        status: approvalMetadata?.decision === "denied" ? "denied" : statusFromOutcome(outcome),
        name,
        result: part["content"],
        outcome,
        ...(toolKind ? { toolKind } : {}),
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
      parsed.toolActivities.push(activity)
      parsed.parts?.push({ kind: "tool", id: partId, activity })
      return
    }

    if (partKind === "retry-prompt") {
      const activity: ToolActivity = {
        id: stringValue(part["tool_call_id"]) ?? partId,
        kind: "retry",
        status: "failed",
        name: stringValue(part["tool_name"]) ?? "tool",
        result: part["content"],
        outcome: "retry",
      }
      parsed.toolActivities.push(activity)
      parsed.parts?.push({ kind: "tool", id: partId, activity })
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
      parsed.parts?.push({ kind: "text", id: partId, content: fallbackText })
      return
    }

    parsed.unsupportedParts.push({
      id: partId,
      label: partKind ? titleCaseToken(partKind, "Unsupported part") : "Unsupported part",
      preview: safeJsonPreview(part),
    })
  })

  return parsed
}

function resolveOrderedToolParts(
  parts: ParsedMessagePart[] | null,
  resolvedActivitiesByOriginal: Map<ToolActivity, ToolActivity | null>
): ParsedMessagePart[] | null {
  if (parts === null) {
    return null
  }

  const resolvedParts: ParsedMessagePart[] = []
  for (const part of parts) {
    if (part.kind !== "tool") {
      resolvedParts.push(part)
      continue
    }
    const activity = resolvedActivitiesByOriginal.get(part.activity)
    if (activity) {
      resolvedParts.push({ ...part, activity })
    }
  }
  return resolvedParts
}

function hasRenderableMessageContent(message: ParsedConversationMessage) {
  return (
    message.text.length > 0 ||
    message.thinking.length > 0 ||
    message.attachments.length > 0 ||
    message.toolActivities.length > 0 ||
    message.unsupportedParts.length > 0
  )
}

function getMessageParts(value: Record<string, unknown>): Record<string, unknown>[] {
  const parts = value["parts"]
  if (!Array.isArray(parts)) {
    return []
  }

  return parts.filter(isRecord)
}

function parseUserPromptContent(
  value: unknown,
  partId: string
): {
  attachments: ParsedAttachment[]
  text: string | null
  unsupportedParts: ParsedConversationMessage["unsupportedParts"]
} {
  if (typeof value === "string") {
    return { attachments: [], text: value, unsupportedParts: [] }
  }

  if (!Array.isArray(value)) {
    return { attachments: [], text: null, unsupportedParts: [] }
  }

  const textSegments: string[] = []
  const attachments: ParsedAttachment[] = []
  const unsupportedParts: ParsedConversationMessage["unsupportedParts"] = []

  value.forEach((item, index) => {
    if (typeof item === "string") {
      textSegments.push(item)
      return
    }

    if (isBinaryUserContentPart(item)) {
      const binaryAttachment = attachmentFromBinaryUserContentPart(item)
      if (binaryAttachment) {
        attachments.push(binaryAttachment)
      }
      return
    }

    if (isBinaryUserContentLike(item)) {
      unsupportedParts.push({
        id: `${partId}:content:${String(index)}`,
        label: "Attachment",
        preview: "Binary attachment is missing a file reference.",
      })
      return
    }

    if (!isRecord(item)) {
      return
    }

    const text = stringValue(item["text"]) ?? stringValue(item["content"])
    if (text) {
      textSegments.push(text)
      return
    }

    unsupportedParts.push({
      id: `${partId}:content:${String(index)}`,
      label: "User prompt item",
      preview: safeJsonPreview(item),
    })
  })

  return {
    attachments,
    text: textSegments.length > 0 ? textSegments.join("\n") : null,
    unsupportedParts,
  }
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

function statusFromOutcome(outcome: string | null | undefined): ToolActivityStatus {
  if (outcome === "failed") {
    return "failed"
  }
  if (outcome === "denied") {
    return "denied"
  }
  return "completed"
}

function normalizeRole(role: string): ParsedMessageRole {
  if (role === "user" || role === "assistant" || role === "tool" || role === "system") {
    return role
  }

  return "unknown"
}
