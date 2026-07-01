// apps/web/src/features/conversations/format.ts

import type { Conversation } from "@/features/conversations/types"

export function conversationAgentLabel(conversation: Conversation, fallbackLabel = "No agent") {
  return (
    conversation.agent_name ??
    conversation.agent_slug ??
    shortAgentFallback(conversation.active_agent_id) ??
    fallbackLabel
  )
}

export function sourceLabel(source: string) {
  return source.replaceAll("_", " ")
}

function shortAgentFallback(agentId: string | null) {
  if (!agentId) {
    return null
  }
  return `Agent ${agentId.slice(0, 8)}`
}
