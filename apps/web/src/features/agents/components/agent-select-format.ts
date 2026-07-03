// apps/web/src/features/agents/components/agent-select-format.ts

import type { Agent } from "@/features/agents/types"

export function agentSelectSecondary(agent: Agent) {
  return agent.description ?? agent.slug
}

export function agentSelectLabel(agent: Agent, secondary = agentSelectSecondary(agent)) {
  return secondary ? `${agent.name} · ${secondary}` : agent.name
}
