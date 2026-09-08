// apps/web/src/features/agents/use-agent-identity-metadata.ts

import { useQuery } from "@tanstack/react-query"

import { agentsQueryOptions } from "@/features/agents/api/list-agents"

// Resolves an agent's configured identity colour without suspending, so rows
// that only know an agent id still match the colour shown elsewhere.
export function useAgentIdentityMetadata(agentId: string | null) {
  const { data } = useQuery({ ...agentsQueryOptions(), enabled: agentId !== null })

  if (agentId === null) {
    return null
  }
  return data?.agents.find((agent) => agent.id === agentId)?.metadata ?? null
}
