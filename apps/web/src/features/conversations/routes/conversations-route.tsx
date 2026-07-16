// apps/web/src/features/conversations/routes/conversations-route.tsx

import { useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { MessageSquarePlusIcon, MessageSquareTextIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import { ConversationList } from "@/features/conversations/components/conversation-list"
import { sortConversations } from "@/features/conversations/sort"

export function ConversationsRoute() {
  const { data: conversationsData } = useConversationsQuery({ limit: 100 })
  const conversations = useMemo(
    () => sortConversations(conversationsData.conversations),
    [conversationsData.conversations]
  )
  const hasConversations = conversations.length > 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          hasConversations ? (
            <Button render={<Link to="/conversations/new" />}>
              <MessageSquarePlusIcon data-icon="inline-start" />
              New conversation
            </Button>
          ) : null
        }
        description="Recent workspace threads, approvals, and scheduled agent activity."
        title="Conversations"
      />

      {hasConversations ? (
        <ConversationList conversations={conversations} selectedConversationId={null} />
      ) : (
        <ConversationEmptyState />
      )}
    </div>
  )
}

function ConversationEmptyState() {
  return (
    <EmptyState
      action={
        <Button render={<Link to="/conversations/new" />}>
          <MessageSquarePlusIcon data-icon="inline-start" />
          New conversation
        </Button>
      }
      description="Start a blank chat, choose an active agent, and the thread will appear here."
      icon={<MessageSquareTextIcon className="size-5" />}
      title="No conversations yet"
    />
  )
}
