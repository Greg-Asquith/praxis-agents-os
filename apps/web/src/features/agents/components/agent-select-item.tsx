// apps/web/src/features/agents/components/agent-select-item.tsx

import { agentSelectSecondary } from "@/features/agents/components/agent-select-format"
import type { Agent } from "@/features/agents/types"

export function AgentSelectItem({ agent, secondary }: { agent: Agent; secondary?: string | null }) {
  const description = secondary ?? agentSelectSecondary(agent)

  return (
    <span className="flex min-w-0 flex-col">
      <span className="truncate">{agent.name}</span>
      {description ? (
        <span className="text-muted-foreground truncate text-xs">{description}</span>
      ) : null}
    </span>
  )
}
