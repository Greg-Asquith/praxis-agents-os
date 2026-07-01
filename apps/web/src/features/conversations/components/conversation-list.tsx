// apps/web/src/features/conversations/components/conversation-list.tsx

import { Link } from "@tanstack/react-router"
import { CircleIcon, ClockIcon, MessageSquareTextIcon, ShieldAlertIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/ui/empty-state"
import { conversationAgentLabel, sourceLabel } from "@/features/conversations/format"
import type { Conversation } from "@/features/conversations/types"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

type ConversationListProps = {
  conversations: Conversation[]
  selectedConversationId?: string | null
}

export function ConversationList({ conversations, selectedConversationId }: ConversationListProps) {
  if (conversations.length === 0) {
    return (
      <EmptyState
        description="Start a new conversation from the action above."
        icon={<MessageSquareTextIcon className="size-5" />}
        size="compact"
        title="No conversations"
      />
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
            <div className="flex min-w-0 items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {conversation.title ?? "Untitled conversation"}
                </p>
                <p className="text-muted-foreground truncate text-xs">
                  {conversationAgentLabel(conversation)}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap justify-end gap-1">
                {conversation.needs_approval && (
                  <Badge variant="secondary">
                    <ShieldAlertIcon data-icon="inline-start" />
                    Approval
                  </Badge>
                )}
                {conversation.unread && (
                  <Badge variant="outline">
                    <CircleIcon className="fill-current" data-icon="inline-start" />
                    Unread
                  </Badge>
                )}
                {conversation.source !== "direct" && (
                  <Badge variant="outline">{sourceLabel(conversation.source)}</Badge>
                )}
              </div>
            </div>
            <div className="text-muted-foreground flex items-center gap-1 text-xs">
              <ClockIcon className="size-3" />
              {formatDateTime(conversation.last_message_at ?? conversation.updated_at)}
            </div>
          </Link>
        )
      })}
    </div>
  )
}
