// apps/web/src/features/conversations/components/conversation-list.tsx

import { useMemo, type ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import {
  CalendarClockIcon,
  Clock3Icon,
  CornerDownRightIcon,
  MessageSquareTextIcon,
  WebhookIcon,
} from "lucide-react"

import { EmptyState } from "@/components/ui/empty-state"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { ConversationBadges } from "@/features/conversations/components/conversation-badges"
import { conversationAgentLabel } from "@/features/conversations/format"
import type { Conversation } from "@/features/conversations/types"
import { relativeDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

type ConversationListProps = {
  className?: string
  conversations: Conversation[]
  emptyState?: ReactNode
  selectedConversationId?: string | null
  showRunStatus?: boolean
}

export function ConversationList({
  className,
  conversations,
  emptyState,
  selectedConversationId,
  showRunStatus = false,
}: ConversationListProps) {
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const agentsById = useMemo(
    () => new Map(agentsData.agents.map((agent) => [agent.id, agent])),
    [agentsData.agents]
  )

  if (conversations.length === 0) {
    return (
      emptyState ?? (
        <EmptyState
          description="Start a new conversation from the action above."
          icon={<MessageSquareTextIcon className="size-5" />}
          size="compact"
          title="No conversations"
        />
      )
    )
  }

  return (
    <div className={cn("grid gap-1", className)}>
      {conversations.map((conversation) => {
        const isSelected = conversation.id === selectedConversationId

        return (
          <Link
            key={conversation.id}
            to="/conversations/$conversationId"
            params={{ conversationId: conversation.id }}
            className={cn(
              "hover:bg-muted flex min-w-0 items-center gap-3 rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors",
              isSelected && "bg-muted border-border"
            )}
          >
            <AgentIdentityIcon
              agentId={conversation.active_agent_id ?? conversation.id}
              decorative
              metadata={
                conversation.active_agent_id
                  ? agentsById.get(conversation.active_agent_id)?.metadata
                  : null
              }
              name={conversationAgentLabel(conversation)}
              size="md"
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">
                {conversation.title ?? "Untitled conversation"}
              </span>
              <span className="text-muted-foreground block truncate text-xs">
                {conversationAgentLabel(conversation)}
              </span>
            </span>
            <ConversationBadges
              conversation={conversation}
              runStatus={showRunStatus ? conversation.active_run_status : null}
            />
            <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs">
              <Clock3Icon aria-hidden="true" className="size-3" />
              {relativeDateTime(conversation.last_message_at ?? conversation.updated_at)}
              {conversation.source === "scheduled" ? (
                <>
                  <CalendarClockIcon aria-hidden="true" className="ml-1 size-3" />
                  <span className="sr-only">Scheduled</span>
                </>
              ) : null}
              {conversation.source === "delegated" ? (
                <>
                  <CornerDownRightIcon aria-hidden="true" className="ml-1 size-3" />
                  <span className="sr-only">Delegated</span>
                </>
              ) : null}
              {conversation.source === "event" ? (
                <>
                  <WebhookIcon aria-hidden="true" className="ml-1 size-3" />
                  <span className="sr-only">Triggered by an event</span>
                </>
              ) : null}
            </span>
          </Link>
        )
      })}
    </div>
  )
}
