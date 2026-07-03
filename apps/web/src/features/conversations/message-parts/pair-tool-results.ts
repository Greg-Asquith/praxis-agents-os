// apps/web/src/features/conversations/message-parts/pair-tool-results.ts

import type {
  ParsedConversationMessage,
  ToolActivity,
} from "@/features/conversations/message-parts/types"

type ToolActivityPointer = {
  activityIndex: number
  messageIndex: number
}

export function pairToolResults(messages: ParsedConversationMessage[]) {
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

export function toolActivityKey(messageIndex: number, activityIndex: number) {
  return `${String(messageIndex)}:${String(activityIndex)}`
}
