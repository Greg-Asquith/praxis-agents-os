// apps/web/src/features/conversations/components/conversation-list.tsx

import type { ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import {
  CalendarClockIcon,
  ClockIcon,
  CornerDownRightIcon,
  MessageSquareTextIcon,
} from "lucide-react"

import { EmptyState } from "@/components/ui/empty-state"
import { ConversationBadges } from "@/features/conversations/components/conversation-badges"
import { conversationAgentLabel } from "@/features/conversations/format"
import type { Conversation } from "@/features/conversations/types"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

type ConversationListProps = {
  conversations: Conversation[]
  emptyState?: ReactNode
  selectedConversationId?: string | null
  showRunStatus?: boolean
}

export function ConversationList({
  conversations,
  emptyState,
  selectedConversationId,
  showRunStatus = false,
}: ConversationListProps) {
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
    <div className="flex flex-col gap-1">
      {conversations.map((conversation) => {
        const isSelected = conversation.id === selectedConversationId

        return (
          <Link
            key={conversation.id}
            to="/conversations/$conversationId"
            params={{ conversationId: conversation.id }}
            className={cn(
              "hover:bg-muted flex min-w-0 flex-col gap-2 rounded-lg border border-transparent px-3 py-2 text-left transition-colors",
              isSelected && "bg-muted border-border"
            )}
          >
            <div className="flex min-w-0 flex-col justify-between gap-2 md:flex-row md:items-start">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {conversation.title ?? "Untitled conversation"}
                </p>
                <p className="text-muted-foreground truncate text-xs">
                  {conversationAgentLabel(conversation)}
                </p>
              </div>
              <ConversationBadges
                conversation={conversation}
                runStatus={showRunStatus ? conversation.active_run_status : null}
              />
            </div>
            <div className="text-muted-foreground flex items-center gap-1 text-xs">
              <ClockIcon aria-hidden="true" className="size-3" />
              <span>{formatDateTime(conversation.last_message_at ?? conversation.updated_at)}</span>
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
            </div>
          </Link>
        )
      })}
    </div>
  )
}
