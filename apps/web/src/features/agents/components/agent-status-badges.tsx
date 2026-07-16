// apps/web/src/features/agents/components/agent-status-badges.tsx

import { Badge } from "@/components/ui/badge"
import type { Agent } from "@/features/agents/types"

export function AgentStatusBadges({ agent }: { agent: Agent }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant={agent.is_active ? "success" : "outline"}>
        {agent.is_active ? "Active" : "Inactive"}
      </Badge>
      {agent.is_favorite && <Badge variant="secondary">Favorite</Badge>}
    </div>
  )
}
