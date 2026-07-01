// apps/web/src/features/conversations/routes/conversations-route.tsx

import { useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { MessageSquarePlusIcon, MessageSquareTextIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { Separator } from "@/components/ui/separator"
import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import { ConversationList } from "@/features/conversations/components/conversation-list"
import { sortConversations } from "@/features/conversations/sort"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { pluralize } from "@/lib/format"

export function ConversationsRoute() {
  const { workspace } = useActiveWorkspace()
  const { data: conversationsData } = useConversationsQuery({ limit: 100 })
  const conversations = useMemo(
    () => sortConversations(conversationsData.conversations),
    [conversationsData.conversations]
  )
  const hasConversations = conversations.length > 0

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">{workspace.name}</p>
          <div>
            <h1 className="font-heading text-2xl font-semibold tracking-normal">Conversations</h1>
            <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
              Recent workspace threads, approvals, and scheduled agent activity.
            </p>
          </div>
        </div>
        {hasConversations ? (
          <Button render={<Link to="/conversations/new" />}>
            <MessageSquarePlusIcon data-icon="inline-start" />
            New conversation
          </Button>
        ) : null}
      </div>

      <section className="bg-background rounded-xl border">
        <div className="flex flex-col justify-between gap-3 p-4 md:flex-row md:items-center">
          <div className="min-w-0">
            <h2 className="text-sm font-medium">
              {conversationsData.total} {pluralize(conversationsData.total, "conversation")}
            </h2>
            <p className="text-muted-foreground text-xs">Sorted by recent activity.</p>
          </div>
          {hasConversations ? (
            <Button size="sm" variant="outline" render={<Link to="/conversations/new" />}>
              <MessageSquarePlusIcon data-icon="inline-start" />
              Start new
            </Button>
          ) : null}
        </div>
        <Separator />
        <div className="p-2 md:p-3">
          {hasConversations ? (
            <ConversationList conversations={conversations} selectedConversationId={null} />
          ) : (
            <ConversationEmptyState />
          )}
        </div>
      </section>
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
