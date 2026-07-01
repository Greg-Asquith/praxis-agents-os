// apps/web/src/features/conversations/components/conversation-list.tsx

import { Link } from "@tanstack/react-router"
import { ClockIcon, MessageSquareTextIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
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
      <div className="flex min-h-56 flex-col items-center justify-center rounded-lg border border-dashed p-5 text-center">
        <div className="bg-muted text-muted-foreground mb-3 flex size-9 items-center justify-center rounded-full">
          <MessageSquareTextIcon className="size-4" />
        </div>
        <p className="text-sm font-medium">No conversations</p>
        <p className="text-muted-foreground mt-1 text-xs">
          Start a new conversation from the action above.
        </p>
      </div>
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
                  {conversation.agent_slug ?? conversation.active_agent_id ?? "No agent"}
                </p>
              </div>
              {conversation.source !== "direct" && (
                <Badge variant="outline">{conversation.source}</Badge>
              )}
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
