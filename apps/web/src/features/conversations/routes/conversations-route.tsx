// apps/web/src/features/conversations/routes/conversations-route.tsx

import { useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { MessageSquarePlusIcon, MessageSquareTextIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import { ConversationList } from "@/features/conversations/components/conversation-list"
import { sortConversations } from "@/features/conversations/sort"
import { pluralize } from "@/lib/format"

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

      <Card size="sm">
        <CardHeader className="border-b">
          <CardTitle>
            {conversationsData.total} {pluralize(conversationsData.total, "conversation")}
          </CardTitle>
          <CardDescription>Sorted by recent activity.</CardDescription>
          {hasConversations ? (
            <CardAction>
              <Button size="sm" variant="outline" render={<Link to="/conversations/new" />}>
                <MessageSquarePlusIcon data-icon="inline-start" />
                Start new
              </Button>
            </CardAction>
          ) : null}
        </CardHeader>
        <CardContent className="px-2 md:px-3">
          {hasConversations ? (
            <ConversationList conversations={conversations} selectedConversationId={null} />
          ) : (
            <ConversationEmptyState />
          )}
        </CardContent>
      </Card>
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
