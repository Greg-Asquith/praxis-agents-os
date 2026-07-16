// apps/web/src/routes/home.tsx

import { useMemo, type ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { useSuspenseQuery } from "@tanstack/react-query"
import { InboxIcon, MessageSquarePlusIcon, MessageSquareTextIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { conversationsQueryOptions } from "@/features/conversations/api/list-conversations"
import { ConversationList } from "@/features/conversations/components/conversation-list"
import { sortConversations } from "@/features/conversations/sort"
import { pluralize } from "@/lib/format"

const ATTENTION_LIMIT = 5
const RECENT_LIMIT = 6

export function HomeRoute() {
  const conversationsQuery = useSuspenseQuery(conversationsQueryOptions({ limit: 10 }))
  const conversations = useMemo(
    () => sortConversations(conversationsQuery.data.conversations),
    [conversationsQuery.data.conversations]
  )
  const attentionConversations = useMemo(
    () =>
      conversations.filter((conversation) => conversation.needs_approval || conversation.unread),
    [conversations]
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          <Button render={<Link to="/conversations/new" />}>
            <MessageSquarePlusIcon data-icon="inline-start" />
            New Conversation
          </Button>
        }
        description="Live agent state, approvals, and recent workspace conversations."
        title="Dashboard"
      />

      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <DashboardPanel
          description={`${String(attentionConversations.length)} ${pluralize(
            attentionConversations.length,
            "conversation"
          )} unread or awaiting approval`}
          title="Needs attention"
        >
          <ConversationList
            conversations={attentionConversations.slice(0, ATTENTION_LIMIT)}
            emptyState={
              <EmptyState
                action={
                  <Button variant="outline" render={<Link to="/conversations" />}>
                    Open Conversations
                  </Button>
                }
                description="No unread or approval-gated conversations right now."
                icon={<InboxIcon className="size-5" />}
                size="compact"
                title="Nothing pending"
              />
            }
            showRunStatus
            sourceVisibility="none"
          />
        </DashboardPanel>

        <DashboardPanel
          action={
            <Button variant="outline" render={<Link to="/conversations" />}>
              View All
            </Button>
          }
          description={`${String(conversationsQuery.data.total)} ${pluralize(
            conversationsQuery.data.total,
            "conversation"
          )} in this workspace`}
          title="Recent conversations"
        >
          <ConversationList
            conversations={conversations.slice(0, RECENT_LIMIT)}
            emptyState={
              <EmptyState
                action={
                  <Button variant="secondary" render={<Link to="/conversations/new" />}>
                    <MessageSquarePlusIcon data-icon="inline-start" />
                    New Conversation
                  </Button>
                }
                description="Start a blank chat and choose an active agent."
                icon={<MessageSquareTextIcon className="size-5" />}
                size="compact"
                title="No conversations yet"
              />
            }
            showRunStatus
            sourceVisibility="always"
          />
        </DashboardPanel>
      </section>
    </div>
  )
}

function DashboardPanel({
  action,
  children,
  description,
  title,
}: {
  action?: ReactNode
  children: ReactNode
  description: string
  title: string
}) {
  return (
    <section className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
          <h2 className="text-sm font-medium">{title}</h2>
          <p className="text-muted-foreground text-xs">{description}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}
