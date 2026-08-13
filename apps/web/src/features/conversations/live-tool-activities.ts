// apps/web/src/features/conversations/live-tool-activities.ts

import {
  delegationDetailsForPendingApproval,
  delegationDetailsForToolActivity,
  mergeDelegationDetails,
  normalizeToolArgs,
  type ToolActivity,
} from "@/features/conversations/message-parts"
import { LOAD_CAPABILITY_TOOL_NAME } from "@/features/conversations/skills/skill-activation"
import {
  selectChildToolCalls,
  type ApprovalState,
  type ToolCallState,
} from "@/features/conversations/stream/reducer"
import type { PendingDelegatedApproval } from "@/features/conversations/types"
import { isRecord, stringValue } from "@/lib/guards"

export function buildLiveToolActivities(
  toolCalls: ToolCallState[],
  approvals: ApprovalState[],
  agentRunId: string | null
): ToolActivity[] {
  const activities = toolCalls.map((toolCall): ToolActivity => {
    const args = normalizeToolArgs(toolCall.args)
    const activity: ToolActivity = {
      id: toolCall.tool_call_id,
      agentRunId,
      kind: toolCall.status === "awaiting_approval" ? "approval" : "call",
      status: toolCall.status,
      name: toolCall.name,
      args,
      result: toolCall.result,
      ...(toolCall.name === LOAD_CAPABILITY_TOOL_NAME ? { toolKind: "capability-load" } : {}),
    }
    const delegate = delegationDetailsForToolActivity(toolCall.name, args, toolCall.result)
    if (delegate) {
      activity.delegate = delegate
    }
    return activity
  })
  const activityIndexesById = new Map(activities.map((activity, index) => [activity.id, index]))

  for (const delegation of approvals
    .map((approval) => approval.delegation)
    .filter((value): value is PendingDelegatedApproval => Boolean(value))) {
    const existingIndex = activityIndexesById.get(delegation.parent_tool_call_id)
    if (existingIndex === undefined) {
      activities.push({
        id: delegation.parent_tool_call_id,
        agentRunId,
        kind: "approval",
        status: "awaiting_approval",
        name: "delegate_to_agent",
        delegate: delegationDetailsForPendingApproval(delegation),
      })
      activityIndexesById.set(delegation.parent_tool_call_id, activities.length - 1)
      continue
    }

    const existing = activities[existingIndex]
    if (existing === undefined) {
      continue
    }
    const pendingDelegate = delegationDetailsForPendingApproval(delegation, existing.args)
    const delegate = mergeDelegationDetails(existing.delegate, pendingDelegate) ?? pendingDelegate
    activities[existingIndex] = {
      ...existing,
      delegate,
      kind: "approval",
      status: "awaiting_approval",
    }
  }

  for (const approval of approvals) {
    if (activities.some((activity) => activity.id === approval.tool_call_id)) {
      continue
    }
    const args = normalizeToolArgs(approval.args)
    const activity: ToolActivity = {
      id: approval.tool_call_id,
      agentRunId,
      kind: "approval",
      status: "awaiting_approval",
      name: approval.name,
      args,
    }
    const delegate = delegationDetailsForToolActivity(approval.name, args)
    if (delegate) {
      activity.delegate = delegate
    }
    activities.push(activity)
    activityIndexesById.set(activity.id, activities.length - 1)
  }

  for (const toolCall of toolCalls) {
    if (toolCall.parentToolCallId || toolCall.name !== "run_workflow") {
      continue
    }
    const parentIndex = activityIndexesById.get(toolCall.tool_call_id)
    const parent = parentIndex === undefined ? undefined : activities[parentIndex]
    if (parentIndex === undefined || !parent) {
      continue
    }
    const args = isRecord(toolCall.args) ? toolCall.args : null
    const children = selectChildToolCalls(toolCalls, toolCall.tool_call_id).flatMap(
      (candidate): ToolActivity[] => {
        const childIndex = activityIndexesById.get(candidate.tool_call_id)
        const child = childIndex === undefined ? undefined : activities[childIndex]
        return child ? [codeModeTraceProjection(child)] : []
      }
    )
    activities[parentIndex] = {
      ...parent,
      outcome:
        parent.outcome ??
        (parent.status === "completed" ? "success" : parent.status === "failed" ? "failed" : null),
      script: {
        children,
        code: args ? stringValue(args["code"]) : null,
        error: toolCall.workflowErrorExcerpt ?? null,
        output: toolCall.workflowOutputExcerpt ?? null,
        reason: args ? stringValue(args["reason"]) : null,
        status: parent.status,
      },
    }
  }
  return activities
}

function codeModeTraceProjection(activity: ToolActivity): ToolActivity {
  if (activity.status === "awaiting_approval") {
    return activity
  }
  const error = isRecord(activity.result) ? stringValue(activity.result["error"]) : null
  const resultExcerpt = error ?? boundedCodeModeExcerpt(activity.result)
  return {
    id: activity.id,
    kind: "result",
    name: activity.name,
    status: activity.status,
    ...(resultExcerpt === null
      ? {}
      : {
          result: error ?? activity.result,
          resultExcerpt,
        }),
  }
}

function boundedCodeModeExcerpt(value: unknown): string | null {
  if (value === null || value === undefined) {
    return null
  }
  const rendered = typeof value === "string" ? value : JSON.stringify(sortJsonValue(value))
  if (rendered.length <= 1_000) {
    return rendered
  }
  const marker = "…[excerpt truncated]…"
  const remaining = 1_000 - marker.length
  const head = Math.floor(remaining * 0.8)
  return `${rendered.slice(0, head)}${marker}${rendered.slice(-(remaining - head))}`
}

function sortJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortJsonValue)
  }
  if (!isRecord(value)) {
    return value
  }
  return Object.fromEntries(
    Object.entries(value)
      .toSorted(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, sortJsonValue(item)])
  )
}
