// apps/web/src/components/shell/sidebar-conversations.tsx

import { Link } from "@tanstack/react-router"
import {
  CircleIcon,
  MessageSquarePlusIcon,
  MessageSquareTextIcon,
  ShieldAlertIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { conversationAgentLabel } from "@/features/conversations/format"
import type { Conversation } from "@/features/conversations/types"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

type SidebarConversationsProps = {
  conversations: Conversation[]
  pathname: string
}

export function SidebarConversations({ conversations, pathname }: SidebarConversationsProps) {
  const selectedConversationId = getSelectedConversationId(pathname)

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-2" aria-labelledby="sidebar-conversations">
      <div className="flex shrink-0 items-center justify-between gap-2 px-1">
        <h2
          id="sidebar-conversations"
          className="text-muted-foreground text-xs font-medium tracking-normal"
        >
          Conversations
        </h2>
        <Button
          aria-label="New conversation"
          size="icon-xs"
          variant="ghost"
          render={<Link to="/conversations/new" />}
        >
          <MessageSquarePlusIcon />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {conversations.length > 0 ? (
          <div className="flex flex-col gap-0.5">
            {conversations.map((conversation) => (
              <ConversationRow
                key={conversation.id}
                conversation={conversation}
                isSelected={conversation.id === selectedConversationId}
              />
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground flex h-8 items-center gap-2 px-2 text-xs">
            <MessageSquareTextIcon className="size-3.5" />
            No recent conversations
          </p>
        )}
      </div>
    </section>
  )
}

function ConversationRow({
  conversation,
  isSelected,
}: {
  conversation: Conversation
  isSelected: boolean
}) {
  return (
    <Link
      to="/conversations/$conversationId"
      params={{ conversationId: conversation.id }}
      className={cn(
        "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex min-w-0 items-start gap-2 rounded-lg px-2 py-2 text-left transition-colors",
        isSelected && "bg-sidebar-accent text-sidebar-accent-foreground"
      )}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">
          {conversation.title ?? "Untitled conversation"}
        </span>
        <span className="text-muted-foreground block truncate text-xs">
          {conversationAgentLabel(conversation)}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-1 pt-0.5">
        {conversation.needs_approval && (
          <span aria-label="Needs approval" title="Needs approval">
            <ShieldAlertIcon className="text-destructive size-3.5" />
          </span>
        )}
        {conversation.unread && (
          <span aria-label="Unread" title="Unread">
            <CircleIcon className="text-primary size-2 fill-current" />
          </span>
        )}
        <span className="text-muted-foreground text-[0.7rem] leading-4">
          {formatDateTime(conversation.last_message_at ?? conversation.updated_at)}
        </span>
      </span>
    </Link>
  )
}

function getSelectedConversationId(pathname: string) {
  const [, maybeConversationId] = pathname.split("/conversations/")
  if (!maybeConversationId || maybeConversationId === "new") {
    return null
  }

  return maybeConversationId.split("/")[0] ?? null
}
