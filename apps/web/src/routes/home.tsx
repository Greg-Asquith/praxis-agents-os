// apps/web/sec/routes/home.tsx

import { useMemo } from "react"
import { useSuspenseQueries } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { MessageSquarePlusIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { agentsQueryOptions } from "@/features/agents/api/list-agents"
import {
  conversationsQueryOptions,
  useConversationsQuery,
} from "@/features/conversations/api/list-conversations"
import { pendingApprovalsQueryOptions } from "@/features/conversations/api/list-pending-approvals"
import { sortConversations } from "@/features/conversations/sort"
import { AgentLauncher } from "@/features/home/components/agent-launcher"
import { ApprovalsInbox } from "@/features/home/components/approvals-inbox"
import { HomeStats } from "@/features/home/components/home-stats"
import { RecentConversations } from "@/features/home/components/recent-conversations"
import { ScheduleAttention } from "@/features/home/components/schedule-attention"
import { UnreadResults } from "@/features/home/components/unread-results"
import { schedulesQueryOptions } from "@/features/schedules/api/list-schedules"
import { statusSummaryQueryOptions } from "@/features/status/api/get-status-summary"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function HomeRoute() {
  const { workspace } = useActiveWorkspace()
  useSuspenseQueries({
    queries: [
      { ...statusSummaryQueryOptions(), staleTime: 0 },
      conversationsQueryOptions({ limit: 100 }),
      pendingApprovalsQueryOptions(),
      schedulesQueryOptions({ includeInactive: true, limit: 100 }),
      agentsQueryOptions({ includeInactive: false, limit: 100 }),
      agentsQueryOptions({ includeInactive: true, limit: 100 }),
    ],
  })
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

      <div className="divide-border flex min-w-0 flex-col divide-y *:py-7 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
        <HomeStats />
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
