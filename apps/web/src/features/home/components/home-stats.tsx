// apps/web/src/features/home/components/home-stats.tsx

import { Stat, StatGroup } from "@/components/ui/stat"
import { useStatusSummaryQuery } from "@/features/status/api/get-status-summary"

export function HomeStats() {
  const { data } = useStatusSummaryQuery()

  return (
    <StatGroup>
      <Stat label="Agents Waiting for Approval" value={data.conversations_needing_approval} />
      <Stat label="Unread Conversations" value={data.unread_conversations} />
      <Stat label="Schedules Requiring Attention" value={data.schedules_needing_attention} />
    </StatGroup>
  )
}
