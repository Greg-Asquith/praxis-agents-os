// apps/web/src/features/home/components/home-stats.tsx

import { Stat, StatGroup } from "@/components/ui/stat"
import { usePendingApprovalsQuery } from "@/features/conversations/api/list-pending-approvals"
import type { Conversation } from "@/features/conversations/types"
import { useSchedulesQuery } from "@/features/schedules/api/list-schedules"

export function HomeStats({ conversations }: { conversations: Conversation[] }) {
  const { data: approvalsData } = usePendingApprovalsQuery()
  const { data: schedulesData } = useSchedulesQuery({ includeInactive: true, limit: 100 })
  const unreadCount = conversations.filter(
    (conversation) => conversation.unread && !conversation.needs_approval
  ).length
  const attentionCount = schedulesData.items.filter(
    (schedule) => schedule.health === "needs_attention" || schedule.health === "retrying"
  ).length

  return (
    <StatGroup>
      <Stat label="Agents Waiting for Approval" value={approvalsData.total} />
      <Stat label="Unread Conversations" value={unreadCount} />
      <Stat label="Schedules Requiring Attention" value={attentionCount} />
    </StatGroup>
  )
}
