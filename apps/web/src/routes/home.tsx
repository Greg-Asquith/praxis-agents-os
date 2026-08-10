import { useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { MessageSquarePlusIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import { sortConversations } from "@/features/conversations/sort"
import { AgentLauncher } from "@/features/home/components/agent-launcher"
import { ApprovalsInbox } from "@/features/home/components/approvals-inbox"
import { HomeStats } from "@/features/home/components/home-stats"
import { RecentConversations } from "@/features/home/components/recent-conversations"
import { ScheduleAttention } from "@/features/home/components/schedule-attention"
import { UnreadResults } from "@/features/home/components/unread-results"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function HomeRoute() {
  const { workspace } = useActiveWorkspace()
  const conversationsQuery = useConversationsQuery({ limit: 100 })
  const conversations = useMemo(
    () => sortConversations(conversationsQuery.data.conversations),
    [conversationsQuery.data.conversations]
  )
  const hasHistory = conversationsQuery.data.total > 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          <Button
            variant="outline"
            className={`rounded-sm`}
            render={<Link to="/conversations/new" />}
          >
            <MessageSquarePlusIcon data-icon="inline-start" />
            New Conversation
          </Button>
        }
        description={`${workspace.name} · Review work that needs you, read new results, or start something.`}
        title="Home"
      />

      <div className="divide-border flex min-w-0 flex-col divide-y [&>*]:py-7 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
        <HomeStats conversations={conversations} />
        {hasHistory ? null : <AgentLauncher />}
        <ApprovalsInbox />
        <ScheduleAttention />
        <UnreadResults conversations={conversations} />
        {hasHistory ? <AgentLauncher /> : null}
        <RecentConversations conversations={conversations} />
      </div>
    </div>
  )
}
