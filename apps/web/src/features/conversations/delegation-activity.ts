// apps/web/src/features/conversations/delegation-activity.ts

import {
  parseConversationMessages,
  type ToolActivity,
} from "@/features/conversations/message-parts"
import { supersededWriteTodoActivityIds } from "@/features/conversations/native-tools/todo-tools"
import type { ConversationMessage } from "@/features/conversations/types"
import { optionalString } from "@/lib/guards"

// Tool calls a delegate made in its own conversation, ready to render in the parent's card.
// While the delegation is live, calls without a result count as running rather than unknown.
export function delegateToolActivities(
  messages: ConversationMessage[],
  live = false
): ToolActivity[] {
  const childRunId = live ? latestRunId(messages) : null
  const activities = parseConversationMessages(
    messages,
    childRunId ? { id: childRunId, status: "running" } : null
  ).flatMap((message) => message.toolActivities)
  const superseded = supersededWriteTodoActivityIds(activities)

  // Approvals the delegate is waiting on already appear in the parent conversation.
  return activities.filter(
    (activity) =>
      activity.kind === "call" &&
      activity.status !== "awaiting_approval" &&
      !superseded.has(activity.id)
  )
}

function latestRunId(messages: ConversationMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const runId = optionalString(messages[index]?.metadata?.["agent_run_id"])
    if (runId) {
      return runId
    }
  }
  return null
}
