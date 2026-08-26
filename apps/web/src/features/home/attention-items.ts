// apps/web/src/features/home/attention-items.ts

import type { Agent } from "@/features/agents/types"
import { conversationAgentLabel } from "@/features/conversations/format"
import type { Conversation, PendingApprovalsListResponse } from "@/features/conversations/types"
import { scheduleTitle } from "@/features/schedules/format"
import type { AgentSchedule } from "@/features/schedules/types"
import { titleCaseToken, truncateText } from "@/lib/format"

export type AttentionItem =
  | {
      kind: "approval"
      id: string
      title: string
      subtitle: string
      agentId: string | null
      agentName: string
      at: string
      conversationId: string
    }
  | {
      kind: "schedule"
      id: string
      title: string
      subtitle: string
      agentId: string
      agentName: string
      at: string | null
      scheduleId: string
      health: "needs_attention" | "retrying"
      errorMessage: string | null
    }
  | {
      kind: "unread"
      id: string
      title: string
      subtitle: string
      agentId: string | null
      agentName: string
      at: string
      conversationId: string
    }

export function buildAttentionItems(input: {
  approvals: PendingApprovalsListResponse
  schedules: AgentSchedule[]
  conversations: Conversation[]
  agentsById: Map<string, Agent>
}): AttentionItem[] {
  const approvals: AttentionItem[] = input.approvals.items.map((approval) => {
    const agentName =
      approval.agent_name ??
      (approval.agent_id ? input.agentsById.get(approval.agent_id)?.name : null) ??
      "Agent"
    const tools = approval.pending_tool_names.map((name) => titleCaseToken(name, "Tool")).join(", ")
    const delegated = approval.delegated_agent_names.join(", ")

    return {
      kind: "approval",
      id: approval.run_id,
      title: approval.conversation_title ?? "Untitled conversation",
      subtitle: `${agentName} wants to run ${tools}${delegated ? ` via ${delegated}` : ""}`,
      agentId: approval.agent_id,
      agentName,
      at: approval.awaiting_since,
      conversationId: approval.conversation_id,
    }
  })
  const schedules: AttentionItem[] = input.schedules.flatMap((schedule) => {
    if (schedule.health !== "needs_attention" && schedule.health !== "retrying") {
      return []
    }

    const agentName = input.agentsById.get(schedule.agent_id)?.name ?? "Unknown agent"
    const prompt = schedule.default_prompt ? ` · ${truncateText(schedule.default_prompt, 80)}` : ""

    return [
      {
        kind: "schedule",
        id: schedule.id,
        title: scheduleTitle(schedule),
        subtitle: `${agentName}${prompt}`,
        agentId: schedule.agent_id,
        agentName,
        at: schedule.last_run_at,
        scheduleId: schedule.id,
        health: schedule.health,
        errorMessage: schedule.latest_run?.last_error_message
          ? truncateText(schedule.latest_run.last_error_message, 120)
          : null,
      },
    ]
  })
  const unread: AttentionItem[] = input.conversations.flatMap((conversation) => {
    if (!conversation.unread || conversation.needs_approval) {
      return []
    }

    const agentName = conversationAgentLabel(conversation)
    return [
      {
        kind: "unread",
        id: conversation.id,
        title: conversation.title ?? "Untitled conversation",
        subtitle: agentName,
        agentId: conversation.active_agent_id,
        agentName,
        at: conversation.last_message_at ?? conversation.updated_at,
        conversationId: conversation.id,
      },
    ]
  })

  return [...approvals, ...schedules, ...unread]
}
