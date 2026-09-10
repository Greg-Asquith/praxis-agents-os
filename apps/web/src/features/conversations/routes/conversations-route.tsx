// apps/web/src/features/conversations/routes/conversations-route.tsx

import { Suspense, useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { MessageSquarePlusIcon, MessageSquareTextIcon } from "lucide-react"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { SharedConversationList } from "@/features/conversations/components/shared-conversation-list"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import { ConversationList } from "@/features/conversations/components/conversation-list"
import { sortConversations } from "@/features/conversations/sort"

export function ConversationsRoute() {
  const { workspace } = useActiveWorkspace()
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
              New Conversation
            </Button>
          ) : null
        }
        description="Recent workspace threads, approvals, and scheduled agent activity."
        title="Conversations"
      />

      <Tabs defaultValue="mine">
        {!workspace.is_personal ? (
          <TabsList>
            <TabsTrigger value="mine">My Conversations</TabsTrigger>
            <TabsTrigger value="shared">Shared</TabsTrigger>
          </TabsList>
        ) : null}
        <TabsContent value="mine">
          {hasConversations ? (
            <ConversationList
              className="lg:grid-cols-2"
              conversations={conversations}
              selectedConversationId={null}
            />
          ) : (
            <ConversationEmptyState />
          )}
        </TabsContent>
        {!workspace.is_personal ? (
          <TabsContent value="shared">
            <Suspense fallback={<p role="status">Loading shared conversations</p>}>
              <SharedConversationList key={workspace.id} />
            </Suspense>
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  )
}

function ConversationEmptyState() {
  return (
    <EmptyState
      action={
        <Button render={<Link to="/conversations/new" />}>
          <MessageSquarePlusIcon data-icon="inline-start" />
          New Conversation
        </Button>
      }
      description="Start a blank chat, choose an active agent, and the thread will appear here."
      icon={<MessageSquareTextIcon className="size-5" />}
      title="No conversations yet"
    />
  )
}
