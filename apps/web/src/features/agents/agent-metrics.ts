// apps/web/src/features/agents/agent-metrics.ts

import type { Agent } from "@/features/agents/types"

export function countActiveAgents(agents: Agent[]) {
  return agents.filter((agent) => agent.is_active).length
}

export function countApprovalGatedAgents(agents: Agent[]) {
  return agents.filter((agent) => countApprovalPolicyTools(agent) > 0).length
}

export function countApprovalPolicyTools(agent: Agent) {
  const policies = agent.tool_policies ?? {}
  return agent.tool_names.filter((toolName) => policies[toolName] === "approval").length
}
