// apps/web/src/features/conversations/components/shared-conversation-list.tsx

import { useState } from "react"
import { clampPaginationOffset, PaginationControls } from "@/components/ui/pagination-controls"

import { Link } from "@tanstack/react-router"

import { EmptyState } from "@/components/ui/empty-state"
import { useSharedConversationsQuery } from "@/features/conversations/api/list-shared-conversations"
import { relativeDateTime } from "@/lib/format"

export function SharedConversationList() {
  const [offset, setOffset] = useState(0)
  const { data } = useSharedConversationsQuery({ offset })
  const boundedOffset = clampPaginationOffset(data.total, offset, data.limit)
  if (boundedOffset !== offset) setOffset(boundedOffset)
  if (!data.total)
    return (
      <EmptyState
        title="No shared chats"
        description="Chats shared with this workspace appear here."
      />
    )
  return (
    <div className="space-y-4">
      <div className="grid gap-1 lg:grid-cols-2">
        {data.conversations.map((conversation) => (
          <Link
            key={conversation.id}
            to="/shared-chats/$workspaceId/$conversationId"
            params={{ workspaceId: conversation.workspace_id, conversationId: conversation.id }}
            className="hover:bg-muted flex min-w-0 items-center justify-between gap-3 rounded-lg px-3 py-2.5"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">
                {conversation.title ?? "Untitled conversation"}
              </p>
              <p className="text-muted-foreground truncate text-xs">
                {conversation.owner_name
                  ? `Shared by ${conversation.owner_name}`
                  : "Shared with your workspace"}{" "}
                · {conversation.agent_name ?? "Agent"}
              </p>
            </div>
            <time className="text-muted-foreground shrink-0 text-xs">
              {relativeDateTime(conversation.last_message_at ?? conversation.updated_at)}
            </time>
          </Link>
        ))}
      </div>
      <PaginationControls
        ariaLabel="Shared chats pagination"
        limit={data.limit}
        offset={data.offset}
        total={data.total}
        onPageChange={setOffset}
      />
    </div>
  )
}
