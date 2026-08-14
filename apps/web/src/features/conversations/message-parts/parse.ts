// apps/web/src/features/conversations/message-parts/parse.ts

import type {
  ParsedConversationMessage,
  ParsedMessagePart,
  ParsedMessageRole,
  ParsedAttachment,
  CodeModeScriptActivity,
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
  traceExcerptResult,
  toolActivityIdentity,
} from "@/features/conversations/message-parts/utils"
import type {
  AgentRun,
  ConversationMessage,
  PendingDelegatedApproval,
  PendingWorkflowState,
} from "@/features/conversations/types"
import { titleCaseToken } from "@/lib/format"
import { isRecord, stringValue } from "@/lib/guards"

const TOOL_RESULT_PART_KINDS = new Set(["tool-return", "builtin-tool-return", "native-tool-return"])
const TOOL_CALL_PART_KINDS = new Set(["tool-call", "builtin-tool-call", "native-tool-call"])

export type LiveToolResult = {
  result: unknown
  status: "running" | "completed" | "failed" | "denied"
}

export function parseConversationMessages(
  messages: ConversationMessage[],
  activeRun?: Pick<AgentRun, "id" | "status"> | null,
  pendingDelegations: PendingDelegatedApproval[] = [],
  liveResultsByCallIdentity?: ReadonlyMap<string, LiveToolResult>,
  pendingWorkflow?: PendingWorkflowState | null
): ParsedConversationMessage[] {
  const parsed = messages.map(parseConversationMessage)
  const { consumedResultKeys, resultsByCallKey, retryCallKeys } = pairToolResults(parsed)
  const pendingDelegationsByParentCallId = new Map(
    pendingDelegations.map((delegation) => [delegation.parent_tool_call_id, delegation])
  )

  const runAwaitsApproval = activeRun?.status === "awaiting_approval"
  const runIsExecuting = isRunStatusPolling(activeRun?.status)
  const runStoppedBeforeToolResult =
    activeRun?.status === "failed" || activeRun?.status === "cancelled"

  return parsed
    .map((message, messageIndex) => {
      const resolvedActivities = message.toolActivities.map((activity, activityIndex) => {
        if (activity.kind !== "call" || !activity.id) {
          return activity
        }

        const belongsToActiveRun =
          activeRun !== null && activeRun !== undefined && activity.agentRunId === activeRun.id
        const pendingDelegate = belongsToActiveRun
          ? pendingDelegationsByParentCallId.get(activity.id)
          : undefined
        const activityDelegate = pendingDelegate
          ? mergeDelegationDetails(
              activity.delegate,
              delegationDetailsForPendingApproval(pendingDelegate, activity.args)
            )
          : activity.delegate
        const activityWithDelegate = activityDelegate
          ? { ...activity, delegate: activityDelegate }
          : activity
        const activityWithPendingWorkflow =
          pendingWorkflow &&
          belongsToActiveRun &&
          activity.id === pendingWorkflow.outer_tool_call_id
            ? {
                ...activityWithDelegate,
                script: codeModeScriptFromPendingWorkflow(
                  pendingWorkflow,
                  activity.agentRunId ?? null,
                  liveResultsByCallIdentity
                ),
              }
            : activityWithDelegate

        const result = resultsByCallKey.get(toolActivityKey(messageIndex, activityIndex))
        if (result) {
          const delegate = mergeDelegationDetails(activityDelegate, result.delegate)
          const script = result.script
            ? mergeCodeModeScriptArgs(result.script, activity.args)
            : activityWithPendingWorkflow.script
          const mergedActivity: ToolActivity = {
            ...activityWithPendingWorkflow,
            outcome: result.outcome ?? null,
            result: result.result,
            status: result.status,
            ...(script ? { script: { ...script, status: result.status } } : {}),
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
        // A result that streamed live but is not persisted yet still completes
        // the transcript row, so resumed tools never linger as skeletons.
        const liveResult = belongsToActiveRun
          ? liveResultsByCallIdentity?.get(toolActivityIdentity(activity.agentRunId, activity.id))
          : undefined
        if (liveResult && liveResult.status === "completed") {
          return {
            ...activityWithPendingWorkflow,
            result: liveResult.result,
            status: "completed" as const,
          }
        }
        if (belongsToActiveRun && runAwaitsApproval) {
          return {
            ...activityWithPendingWorkflow,
            kind: "approval" as const,
            status: "awaiting_approval" as const,
          }
        }
        if (belongsToActiveRun && runStoppedBeforeToolResult) {
          return (
            stoppedWorkflowActivity(activityWithPendingWorkflow) ?? {
              ...activityWithPendingWorkflow,
              status: "failed" as const,
            }
          )
        }
        if (!belongsToActiveRun || !runIsExecuting) {
          return (
            stoppedWorkflowActivity(activityWithPendingWorkflow) ?? {
              ...activityWithPendingWorkflow,
              status: "unknown" as const,
            }
          )
        }
        return activityWithPendingWorkflow
      })
      const resolvedActivitiesByOriginal = new Map<ToolActivity, ToolActivity | null>()
      const visibleActivities: ToolActivity[] = []
      resolvedActivities.forEach((activity, activityIndex) => {
        const originalActivity = message.toolActivities[activityIndex]
        if (!originalActivity) {
          return
        }
        if (retryCallKeys.has(toolActivityKey(messageIndex, activityIndex))) {
          resolvedActivitiesByOriginal.set(originalActivity, null)
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
  const agentRunId = message.metadata
    ? (stringValue(message.metadata["agent_run_id"]) ?? null)
    : null
  const parsed: ParsedConversationMessage = {
    id: message.id,
    role: normalizeRole(message.role),
    sequence: message.sequence,
    agentRunId,
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
        agentRunId,
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
      const partMetadata = isRecord(part["metadata"]) ? part["metadata"] : null
      const hasPublicResult = partMetadata !== null && Object.hasOwn(partMetadata, "public_result")
      const script = codeModeScriptFromMetadata(partMetadata, statusFromOutcome(outcome))
      const activity: ToolActivity = {
        id: toolCallId,
        agentRunId,
        kind: "result",
        status: approvalMetadata?.decision === "denied" ? "denied" : statusFromOutcome(outcome),
        name,
        result: hasPublicResult ? partMetadata["public_result"] : part["content"],
        outcome,
        ...(script ? { script } : {}),
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
        agentRunId,
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

function codeModeScriptFromMetadata(
  metadata: Record<string, unknown> | null,
  status: ToolActivityStatus = "completed"
): CodeModeScriptActivity | null {
  if (!metadata) {
    return null
  }
  const trace = metadata["code_mode_trace"]
  if (!isRecord(trace) || !Array.isArray(trace["calls"])) {
    return null
  }

  const children = trace["calls"].flatMap((value): ToolActivity[] => {
    if (!isRecord(value)) {
      return []
    }
    const id = stringValue(value["tool_call_id"])
    const name = stringValue(value["tool_name"])
    if (!id || !name) {
      return []
    }
    const traceStatus = codeModeTraceStatus(value["status"])
    const excerpt = stringValue(value["excerpt"])
    const hasPresentationResult = Object.hasOwn(value, "presentation_result")
    return [
      {
        id,
        kind: traceStatus === "awaiting_approval" ? "approval" : "result",
        name,
        status: traceStatus,
        ...(hasPresentationResult
          ? {
              result: value["presentation_result"],
              ...(excerpt === null ? {} : { resultExcerpt: excerpt }),
            }
          : excerpt === null
            ? {}
            : {
                result: traceExcerptResult(excerpt),
                resultExcerpt: excerpt,
              }),
      },
    ]
  })

  return {
    children,
    code: null,
    error: null,
    output: stringValue(trace["output_excerpt"]),
    reason: null,
    status,
  }
}

function codeModeScriptFromPendingWorkflow(
  workflow: PendingWorkflowState,
  agentRunId: string | null,
  liveResultsByCallIdentity?: ReadonlyMap<string, LiveToolResult>
): CodeModeScriptActivity {
  const children = workflow.nested_trace.map((entry): ToolActivity => ({
    id: entry.tool_call_id,
    agentRunId,
    kind: entry.status === "pending" ? "approval" : "result",
    name: entry.tool_name,
    status: codeModeTraceStatus(entry.status),
    ...(entry.result_excerpt === null
      ? {}
      : {
          result: traceExcerptResult(entry.result_excerpt),
          resultExcerpt: entry.result_excerpt,
        }),
  }))
  const pendingIndex = children.findIndex((child) => child.id === workflow.pending.tool_call_id)
  const pendingFields = {
    args: normalizeToolArgs(workflow.pending.args),
    ...(workflow.pending.derived_from_untrusted === true ? { derivedFromUntrusted: true } : {}),
    ...(workflow.pending.taint_sources === undefined
      ? {}
      : { taintSources: workflow.pending.taint_sources }),
  }
  if (pendingIndex === -1) {
    children.push({
      ...pendingFields,
      id: workflow.pending.tool_call_id,
      agentRunId,
      kind: "approval",
      name: workflow.pending.name,
      status: "awaiting_approval",
    })
  } else {
    const pendingChild = children[pendingIndex]
    if (pendingChild) {
      children[pendingIndex] = { ...pendingChild, ...pendingFields }
    }
  }
  // After an approval is submitted the suspended snapshot stays cached, so live
  // stream progress for the resumed nested calls must win over its stale states.
  const mergedChildren = children.map((child): ToolActivity => {
    const live = liveResultsByCallIdentity?.get(toolActivityIdentity(agentRunId, child.id))
    if (!live) {
      return child
    }
    return {
      ...child,
      kind: live.status === "running" ? "call" : "result",
      status: live.status,
      ...(live.result === undefined ? {} : { result: live.result }),
    }
  })
  return {
    children: mergedChildren,
    code: workflow.code,
    error: null,
    output: null,
    reason: workflow.reason,
    status: "awaiting_approval",
  }
}

// A workflow call the run never answered renders as a stopped workflow card,
// not as a generic completed tool row.
function stoppedWorkflowActivity(activity: ToolActivity): ToolActivity | null {
  if (activity.name !== "run_workflow" || activity.script) {
    return null
  }
  const args = isRecord(activity.args) ? activity.args : null
  return {
    ...activity,
    status: "failed",
    script: {
      children: [],
      code: args ? stringValue(args["code"]) : null,
      error: null,
      output: null,
      reason: args ? stringValue(args["reason"]) : null,
      status: "failed",
    },
  }
}

function mergeCodeModeScriptArgs(
  script: CodeModeScriptActivity,
  args: unknown
): CodeModeScriptActivity {
  if (!isRecord(args)) {
    return script
  }
  return {
    ...script,
    code: stringValue(args["code"]),
    reason: stringValue(args["reason"]),
  }
}

function codeModeTraceStatus(value: unknown): ToolActivityStatus {
  if (value === "succeeded") {
    return "completed"
  }
  if (value === "failed") {
    return "failed"
  }
  if (value === "pending") {
    return "awaiting_approval"
  }
  if (value === "denied") {
    return "denied"
  }
  return "unknown"
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
